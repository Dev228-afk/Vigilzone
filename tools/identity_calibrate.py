"""
Per-camera identity threshold calibration tool (offline).

Usage
-----
    python -m tools.identity_calibrate \\
        --enrolled-db data/entities.db \\
        --videos path/to/test_clips/ \\
        --camera_id cam1 \\
        --modality face

Workflow:
  1. Load enrolled embeddings from the entity DB.
  2. Process video frames — detect faces/pets, embed, match.
  3. Collect similarity scores (genuine-ish via track continuity,
     impostor-ish via cross-entity).
  4. Output:
     - CSV dump:  ts, track_id, best_id, best_sim, second_sim, margin, quality_ok
     - Similarity histograms (printed + optional matplotlib)
     - Recommended thresholds (95th-percentile impostor + margin)

Requires the full ai_module to be importable (run from workspace root).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# Ensure project root is on path
_PROJ_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJ_ROOT))


def _load_config():
    """Load models.yaml config."""
    import yaml
    cfg_path = _PROJ_ROOT / "configs" / "models.yaml"
    with open(cfg_path, "r") as f:
        return yaml.safe_load(f)


def _setup_identity(cfg: dict, modality: str):
    """Initialise embedder + matcher from config."""
    from src.identity.store import EntityStore
    from src.identity.matcher import IdentityMatcher

    id_cfg = cfg.get("identity", {})
    store = EntityStore()

    face_cfg = id_cfg.get("face", {})
    pet_cfg = id_cfg.get("pet", {})
    matcher_cfg = id_cfg.get("matcher", {})

    face_embedder = None
    pet_embedder = None

    if modality == "face":
        from src.identity.face_embedder import FaceEmbedder
        face_cfg["enabled"] = True
        face_embedder = FaceEmbedder(face_cfg)

    if modality == "pet":
        from src.identity.pet_embedder import PetEmbedder
        pet_embedder = PetEmbedder(pet_cfg)

    matcher = IdentityMatcher(
        store,
        cfg=matcher_cfg,
        face_threshold=face_cfg.get("match_threshold_sim", 0.50),
        pet_threshold=pet_cfg.get("match_threshold_sim", 0.30),
        face_margin=face_cfg.get("top2_margin", 0.08),
        pet_margin=pet_cfg.get("top2_margin", 0.05),
    )

    return store, matcher, face_embedder, pet_embedder


def _process_video(video_path: str, modality: str, matcher, face_embedder, pet_embedder,
                   camera_id: str, sample_hz: float = 2.0) -> List[dict]:
    """Process one video, return list of per-sample match records."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"  [WARN] Cannot open {video_path}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    skip = max(1, int(fps / sample_hz))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    records = []
    frame_idx = 0
    track_counter = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        if frame_idx % skip != 0:
            continue

        ts = frame_idx / fps

        if modality == "face" and face_embedder and face_embedder.available:
            faces = face_embedder.detect_faces(frame)
            for i, fr in enumerate(faces):
                match = matcher.match_face(fr.embedding)
                records.append({
                    "ts": round(ts, 3),
                    "frame_idx": frame_idx,
                    "track_id": f"face_{track_counter + i}",
                    "best_id": match.entity_id or "UNKNOWN",
                    "best_sim": round(match.best_sim, 4),
                    "second_sim": round(match.second_sim, 4),
                    "margin": round(match.margin, 4),
                    "quality_ok": fr.quality_ok,
                    "sharpness": round(fr.sharpness, 1),
                })
            track_counter += len(faces)

        elif modality == "pet" and pet_embedder and pet_embedder.available:
            # Simple: embed full frame as pet (for calibration)
            frame_area = frame.shape[0] * frame.shape[1]
            emb = pet_embedder.embed(frame, frame_area=frame_area)
            if emb is not None:
                match = matcher.match_pet(emb)
                records.append({
                    "ts": round(ts, 3),
                    "frame_idx": frame_idx,
                    "track_id": f"pet_{track_counter}",
                    "best_id": match.entity_id or "UNKNOWN",
                    "best_sim": round(match.best_sim, 4),
                    "second_sim": round(match.second_sim, 4),
                    "margin": round(match.margin, 4),
                    "quality_ok": True,
                    "sharpness": 0.0,
                })
                track_counter += 1

        if total > 0 and frame_idx % (skip * 50) == 0:
            pct = round(frame_idx / total * 100, 1)
            print(f"  Progress: {pct}%  ({len(records)} samples)")

    cap.release()
    return records


def _compute_stats(records: List[dict]) -> dict:
    """Compute histogram and threshold recommendations from records."""
    known_sims = [r["best_sim"] for r in records if r["best_id"] != "UNKNOWN"]
    unknown_sims = [r["best_sim"] for r in records if r["best_id"] == "UNKNOWN"]
    margins = [r["margin"] for r in records if r["best_id"] != "UNKNOWN"]
    all_sims = [r["best_sim"] for r in records]

    stats = {
        "total_samples": len(records),
        "known_matches": len(known_sims),
        "unknown_matches": len(unknown_sims),
    }

    if known_sims:
        stats["known_sim_mean"] = round(float(np.mean(known_sims)), 4)
        stats["known_sim_std"] = round(float(np.std(known_sims)), 4)
        stats["known_sim_min"] = round(float(np.min(known_sims)), 4)
        stats["known_sim_p25"] = round(float(np.percentile(known_sims, 25)), 4)
        stats["known_sim_p50"] = round(float(np.percentile(known_sims, 50)), 4)
        stats["known_sim_p75"] = round(float(np.percentile(known_sims, 75)), 4)
    if margins:
        stats["margin_mean"] = round(float(np.mean(margins)), 4)
        stats["margin_min"] = round(float(np.min(margins)), 4)
        stats["margin_p25"] = round(float(np.percentile(margins, 25)), 4)

    # Impostor-ish: all best_sims for unknown matches (these are false alarms if high)
    if unknown_sims:
        stats["impostor_sim_mean"] = round(float(np.mean(unknown_sims)), 4)
        stats["impostor_sim_p95"] = round(float(np.percentile(unknown_sims, 95)), 4)
        stats["impostor_sim_max"] = round(float(np.max(unknown_sims)), 4)

    # Recommend threshold
    if all_sims:
        p95_impostor = float(np.percentile(unknown_sims, 95)) if unknown_sims else 0.0
        stats["recommended_threshold_sim"] = round(max(p95_impostor + 0.05, 0.40), 3)
        stats["recommended_top2_margin"] = 0.08  # safe default

    return stats


def _write_csv(records: List[dict], out_path: str):
    """Dump records to CSV."""
    if not records:
        return
    keys = records[0].keys()
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(records)
    print(f"CSV written to: {out_path}")


def _print_histogram(values: list, label: str, bins: int = 10):
    """Print a simple text histogram."""
    if not values:
        print(f"  {label}: no data")
        return
    arr = np.array(values)
    counts, edges = np.histogram(arr, bins=bins)
    max_count = max(counts)
    print(f"\n  {label} histogram ({len(values)} values):")
    for i, c in enumerate(counts):
        bar = "#" * int(c / max(max_count, 1) * 40)
        lo, hi = edges[i], edges[i + 1]
        print(f"    [{lo:6.3f}, {hi:6.3f}) {c:5d}  {bar}")


def main():
    parser = argparse.ArgumentParser(description="Identity threshold calibration tool")
    parser.add_argument("--enrolled-db", default="data/entities.db",
                        help="Path to entities.db (default: data/entities.db)")
    parser.add_argument("--videos", required=True,
                        help="Path to video file or directory of videos")
    parser.add_argument("--camera_id", default="calibrate",
                        help="Camera ID label for output")
    parser.add_argument("--modality", choices=["face", "pet"], default="face",
                        help="Which modality to calibrate")
    parser.add_argument("--sample_hz", type=float, default=2.0,
                        help="Frames per second to sample")
    parser.add_argument("--output_csv", default=None,
                        help="Output CSV path (default: calibrate_<modality>.csv)")
    args = parser.parse_args()

    print("=" * 60)
    print("Identity Calibration Tool")
    print("=" * 60)

    cfg = _load_config()
    store, matcher, face_emb, pet_emb = _setup_identity(cfg, args.modality)

    entities = store.list_entities()
    print(f"Enrolled entities: {len(entities)}")
    if not entities:
        print("WARNING: No enrolled entities — all matches will be UNKNOWN.")
        print("         This is still useful to measure impostor similarity distribution.")

    # Collect video files
    vpath = Path(args.videos)
    if vpath.is_file():
        video_files = [str(vpath)]
    elif vpath.is_dir():
        video_files = sorted(
            str(p) for p in vpath.glob("*")
            if p.suffix.lower() in (".mp4", ".avi", ".mov", ".mkv", ".webm")
        )
    else:
        print(f"ERROR: {args.videos} not found")
        sys.exit(1)

    print(f"Videos to process: {len(video_files)}")

    all_records = []
    for vf in video_files:
        print(f"\nProcessing: {vf}")
        records = _process_video(
            vf, args.modality, matcher, face_emb, pet_emb,
            args.camera_id, args.sample_hz,
        )
        all_records.extend(records)
        print(f"  Samples collected: {len(records)}")

    print(f"\n{'=' * 60}")
    print(f"Total samples: {len(all_records)}")

    if not all_records:
        print("No samples collected — check video files and embedder availability.")
        sys.exit(0)

    # Compute stats
    stats = _compute_stats(all_records)
    print(f"\nStatistics:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # Histograms
    known_sims = [r["best_sim"] for r in all_records if r["best_id"] != "UNKNOWN"]
    unknown_sims = [r["best_sim"] for r in all_records if r["best_id"] == "UNKNOWN"]
    _print_histogram(known_sims, "Known match similarities")
    _print_histogram(unknown_sims, "Impostor similarities")

    # Recommendations
    print(f"\n{'=' * 60}")
    print("RECOMMENDED THRESHOLDS:")
    print(f"  match_threshold_sim: {stats.get('recommended_threshold_sim', 0.50)}")
    print(f"  top2_margin:         {stats.get('recommended_top2_margin', 0.08)}")
    print(f"\nPer-camera override (add to cameras.yaml):")
    print(f"  - camera_id: {args.camera_id}")
    print(f"    identity_overrides:")
    print(f"      {args.modality}:")
    print(f"        match_threshold_sim: {stats.get('recommended_threshold_sim', 0.50)}")
    print(f"        top2_margin: {stats.get('recommended_top2_margin', 0.08)}")

    # CSV dump
    csv_path = args.output_csv or f"calibrate_{args.modality}_{args.camera_id}.csv"
    _write_csv(all_records, csv_path)

    print(f"\nCalibration complete.")


if __name__ == "__main__":
    main()
