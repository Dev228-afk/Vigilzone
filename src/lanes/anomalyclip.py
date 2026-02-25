"""
AnomalyCLIP lane – lighter CLIP-based anomaly scoring.

Uses image + context to produce a fast anomaly score.
Acts as a lighter alternative to AnyAnomaly for low-GPU targets.
"""
import time
import numpy as np
import cv2
from pathlib import Path
from typing import Dict, Any

from .base import BaseLane
from ..common.types import Observation
from ..common.log import setup_logger


class AnomalyCLIPLane(BaseLane):
    """CLIP-based anomaly scoring or motion-energy stub."""

    def __init__(self, lane_name: str, camera_id: str,
                 models_cfg: Dict[str, Any], device: str):
        super().__init__(lane_name, camera_id, models_cfg, device)
        self.sensitivity = 0.5
        self.logger = setup_logger(f"AnomalyCLIP-{camera_id}")
        self._stub = True
        self._model = None
        self._prev_gray = None

        # §4.2 — motion gating config (set in init())
        self._min_motion_area_ratio = 0.02
        self._max_global_change_ratio = 0.70
        self._min_persistence_hits = 3
        self._persistence_window_n = 6
        self._min_interval_s = 30.0

        # Persistence ring buffer for gate
        self._persistence_ring: list = []
        self._last_alert_time: float = 0.0

    # ------------------------------------------------------------------
    def init(self):
        cfg = self.models_cfg.get("models", {}).get("anomalyclip", {})
        self.sensitivity = cfg.get("sensitivity", 0.5)
        model_path = cfg.get("model_path", "models/anomalyclip.pt")
        hf_repo = cfg.get("hf_repo_id", "")
        hf_file = cfg.get("hf_filename", "")

        # §4.2 — load motion gating config from anomaly_stub section
        stub_cfg = self.models_cfg.get("models", {}).get("anomaly_stub", {})
        self._min_motion_area_ratio = stub_cfg.get("min_motion_area_ratio", 0.02)
        self._max_global_change_ratio = stub_cfg.get("max_global_change_ratio", 0.70)
        self._min_persistence_hits = stub_cfg.get("min_persistence_hits", 3)
        self._persistence_window_n = stub_cfg.get("window_n", 6)
        self._min_interval_s = stub_cfg.get("min_interval_s_between_alerts", 30.0)

        if not Path(model_path).is_absolute():
            model_path = str((Path(__file__).parent.parent.parent / model_path).resolve())

        if Path(model_path).exists():
            try:
                import torch
                self._model = torch.load(model_path, map_location="cpu")
                self._stub = False
                self.logger.info(f"AnomalyCLIP model loaded: {model_path}")
            except Exception as e:
                self.logger.warning(f"AnomalyCLIP load failed ({e}), using stub")
                self._stub = True
        else:
            # Actionable message — distinguish between "no source" vs "download failed"
            if not hf_repo:
                self.logger.warning(
                    "AnomalyCLIP disabled (no deterministic checkpoint source configured). "
                    "Using motion-energy stub. "
                    "Set models.anomalyclip.hf_repo_id + hf_filename to enable."
                )
            else:
                self.logger.warning(
                    f"AnomalyCLIP checkpoint not found ({model_path}) after HF fetch attempt. "
                    "Using motion-energy stub."
                )
            self._stub = True

        self._initialized = True
        self.logger.info(f"AnomalyCLIP lane ready (stub={self._stub})")

    # ------------------------------------------------------------------
    def infer(self, frame_bgr: np.ndarray, ts_utc: str) -> Observation:
        if not self._initialized:
            self.init()

        t0 = time.perf_counter()

        if self._stub:
            score, gate_info = self._motion_energy_score_gated(frame_bgr)
        else:
            score = self._clip_score(frame_bgr)
            gate_info = {}

        dt = time.perf_counter() - t0

        # §4.2 — persistence gate: track score history
        above = score > self.sensitivity
        self._persistence_ring.append(above)
        if len(self._persistence_ring) > self._persistence_window_n:
            self._persistence_ring = self._persistence_ring[-self._persistence_window_n:]

        persistence_hits = sum(self._persistence_ring)

        # Determine trigger with all gates applied
        trigger = False
        suppress_reason = None

        if above:
            # Gate 1: persistence
            if persistence_hits < self._min_persistence_hits:
                suppress_reason = f"persistence_low ({persistence_hits}/{self._min_persistence_hits})"
            # Gate 2: min interval since last alert
            elif self._last_alert_time > 0 and (time.time() - self._last_alert_time) < self._min_interval_s:
                suppress_reason = f"interval_too_short ({time.time() - self._last_alert_time:.0f}s < {self._min_interval_s}s)"
            # Gate 3 & 4: motion area & global change (from gate_info)
            elif gate_info.get("area_suppressed"):
                suppress_reason = gate_info["area_suppressed"]
            elif gate_info.get("global_suppressed"):
                suppress_reason = gate_info["global_suppressed"]
            else:
                trigger = True
                self._last_alert_time = time.time()

        return Observation(
            ts_utc=ts_utc,
            camera_id=self.camera_id,
            lane=self.lane_name,
            score=score,
            trigger=trigger,
            label="unknown_anomaly" if trigger else None,
            debug={
                "inference_ms": round(dt * 1000, 1),
                "stub": self._stub,
                "sensitivity": self.sensitivity,
                "persistence_hits": persistence_hits,
                "persistence_window": self._persistence_window_n,
                "suppress_reason": suppress_reason,
                **gate_info,
            },
        )

    # --- helpers -------------------------------------------------------
    def _motion_energy_score_gated(self, frame_bgr: np.ndarray) -> tuple:
        """
        §4.2 — Motion-energy score with area and global-change gates.
        Returns (score, gate_info_dict).
        """
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        gate_info: Dict[str, Any] = {}
        score = 0.0

        if self._prev_gray is not None:
            diff = cv2.absdiff(self._prev_gray, gray)

            # Raw score
            score = float(np.mean(diff)) / 80.0
            score = min(score, 1.0)

            # Gate: min_motion_area_ratio — only count pixels with significant motion
            thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
            motion_pixels = int(np.count_nonzero(thresh))
            total_pixels = gray.shape[0] * gray.shape[1]
            motion_area_ratio = motion_pixels / max(total_pixels, 1)
            gate_info["motion_area_ratio"] = round(motion_area_ratio, 4)

            if motion_area_ratio < self._min_motion_area_ratio:
                gate_info["area_suppressed"] = (
                    f"motion_area_too_small ({motion_area_ratio:.4f} < {self._min_motion_area_ratio})"
                )

            # Gate: max_global_change_ratio — suppress if entire frame changes
            if motion_area_ratio > self._max_global_change_ratio:
                gate_info["global_suppressed"] = (
                    f"global_change ({motion_area_ratio:.4f} > {self._max_global_change_ratio})"
                )

        self._prev_gray = gray
        return score, gate_info

    def _clip_score(self, frame_bgr: np.ndarray) -> float:
        """Run AnomalyCLIP forward pass. TODO: plug real inference."""
        score, _ = self._motion_energy_score_gated(frame_bgr)
        return score
