"""
Temporal verifier lane – X3D-S via PyTorchVideo TorchHub (or local checkpoint).

Accepts a short clip (from ring buffer) and outputs a confirm boolean + confidence
for violence / fall.  Only invoked when a candidate event needs temporal confirmation.

IMPORTANT: This lane is ON-DEMAND ONLY.
  Do NOT run temporal verifier continuously.
  Run only when candidate event appears (via verify_clip()).
  The infer() method is a no-op that returns trigger=False.

Loading strategies (config ``source``):
  • ``torchhub`` (default) — ``torch.hub.load("facebookresearch/pytorchvideo", "x3d_s", pretrained=True)``
    No local ``.pth`` file required.  Model weights are downloaded and cached automatically.
  • ``local`` — ``torch.load(model_path)`` from ``models/x3d_s.pth``.

Day-1 fallback: optical-flow + motion-energy classifier (stub).
"""
import time
import numpy as np
import cv2
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from .base import BaseLane
from ..common.types import Observation
from ..common.log import setup_logger


# Kinetics-400 action labels used by X3D-S pretrained on Kinetics
_KINETICS_VIOLENCE_LABELS = {
    "punching person (boxing)", "wrestling", "slapping",
    "headbutting", "kicking person", "pushing",
    "drop kicking", "side kick", "front raises",
}
_KINETICS_FALL_LABELS = {
    "falling off chair", "faceplanting", "tripping",
}


class TemporalVerifierLane(BaseLane):
    """
    Temporal verifier — ON-DEMAND ONLY.
    The process loop should skip this lane; call verify_clip() directly
    from the aggregator when a candidate violence/fall event appears.
    """

    # Flag for orchestrator to skip in main loop
    on_demand = True

    def __init__(self, lane_name: str, camera_id: str,
                 models_cfg: Dict[str, Any], device: str):
        super().__init__(lane_name, camera_id, models_cfg, device)
        self.conf_threshold = 0.5
        self.logger = setup_logger(f"TemporalVerifier-{camera_id}")
        self._stub = True
        self._model = None
        self._torch_device = "cpu"
        self._prev_gray = None

    # ------------------------------------------------------------------
    def init(self):
        cfg = self.models_cfg.get("models", {}).get("temporal_verifier", {})
        self.conf_threshold = cfg.get("conf", 0.5)
        kind = cfg.get("kind", "x3d")
        source = cfg.get("source", "torchhub")

        # Determine torch device
        try:
            from ..runtime.device import select_device
            dev = select_device(self.models_cfg)
            self._torch_device = dev.torch_device
        except Exception:
            self._torch_device = "cpu"

        loaded = False

        # Strategy 1: TorchHub (no local file needed)
        if source == "torchhub":
            loaded = self._load_torchhub(cfg)

        # Strategy 2: Local file
        if not loaded and source == "local":
            loaded = self._load_local(cfg)

        # Fallback: try local file even if source==torchhub, it might be there
        if not loaded and source != "local":
            loaded = self._load_local(cfg)

        if loaded:
            self._stub = False
        else:
            if source == "torchhub":
                self.logger.warning(
                    "TorchHub load failed and no local checkpoint — using motion-energy stub. "
                    "Install pytorchvideo: pip install pytorchvideo"
                )
            else:
                model_path = cfg.get("model_path", "models/x3d_s.pth")
                self.logger.warning(
                    f"Temporal verifier model not found ({model_path}), using motion-energy stub"
                )
            self._stub = True

        self._initialized = True
        self.logger.info(f"Temporal verifier ready (stub={self._stub})")

    # ------------------------------------------------------------------
    def _load_torchhub(self, cfg: Dict[str, Any]) -> bool:
        """Load X3D-S (or compatible) model from PyTorchVideo TorchHub."""
        hub_repo = cfg.get("hub_repo", "facebookresearch/pytorchvideo")
        hub_model = cfg.get("hub_model", "x3d_s")
        pretrained = cfg.get("pretrained", True)
        try:
            import torch
            self.logger.info(f"Loading temporal verifier from TorchHub: {hub_repo}/{hub_model}")
            model = torch.hub.load(
                hub_repo, hub_model,
                pretrained=pretrained,
            )
            model = model.eval()
            model = model.to(self._torch_device)
            self._model = model
            self.logger.info(
                f"Temporal verifier ({hub_model}) loaded via TorchHub on {self._torch_device}"
            )
            return True
        except Exception as e:
            self.logger.warning(f"TorchHub load failed ({hub_repo}/{hub_model}): {e}")
            return False

    # ------------------------------------------------------------------
    def _load_local(self, cfg: Dict[str, Any]) -> bool:
        """Load model from a local .pth checkpoint."""
        model_path = cfg.get("model_path", "models/x3d_s.pth")
        if not Path(model_path).is_absolute():
            model_path = str((Path(__file__).parent.parent.parent / model_path).resolve())

        if not Path(model_path).exists():
            return False

        try:
            import torch
            self._model = torch.load(model_path, map_location=self._torch_device)
            if hasattr(self._model, "eval"):
                self._model.eval()
            self.logger.info(f"Temporal verifier loaded from local: {model_path}")
            return True
        except Exception as e:
            self.logger.warning(f"Local model load failed ({model_path}): {e}")
            return False

    # ------------------------------------------------------------------
    def infer(self, frame_bgr: np.ndarray, ts_utc: str) -> Observation:
        """
        NO-OP: Temporal verifier must NOT run continuously.
        This method exists only to satisfy the BaseLane interface.
        The orchestrator should skip this lane in the main loop
        (check lane.on_demand == True).
        """
        if not self._initialized:
            self.init()

        return Observation(
            ts_utc=ts_utc,
            camera_id=self.camera_id,
            lane=self.lane_name,
            score=0.0,
            trigger=False,
            label=None,
            debug={"on_demand": True, "skipped": True},
        )

    # ------------------------------------------------------------------
    # On-demand clip verification
    # ------------------------------------------------------------------
    def verify_clip(self, frames: List[Tuple[str, bytes]],
                    target_label: str = "violence") -> Dict[str, Any]:
        """
        Run temporal verification on a clip of JPEG-encoded frames.

        Args:
            frames: List of (ts_utc, jpeg_bytes) from ring buffer.
            target_label: What to verify (``violence`` / ``fall``).

        Returns:
            {"confirmed": bool, "score": float}
        """
        if not self._initialized:
            self.init()

        if not frames:
            return {"confirmed": False, "score": 0.0}

        t0 = time.perf_counter()

        if self._stub:
            result = self._stub_clip_verify(frames)
        else:
            result = self._model_clip_verify(frames, target_label)

        dt = time.perf_counter() - t0
        self.logger.debug(
            f"Clip verify ({len(frames)} frames): confirmed={result['confirmed']}, "
            f"score={result['score']:.2f}, {dt*1000:.1f} ms"
        )
        return result

    # --- helpers -------------------------------------------------------
    def _motion_energy(self, frame_bgr: np.ndarray) -> float:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        score = 0.0
        if self._prev_gray is not None:
            diff = cv2.absdiff(self._prev_gray, gray)
            score = float(np.mean(diff)) / 80.0
            score = min(score, 1.0)
        self._prev_gray = gray
        return score

    def _stub_clip_verify(self, frames: List[Tuple[str, bytes]]) -> Dict[str, Any]:
        """Motion-based clip verification stub."""
        energies = []
        prev_gray = None
        for _, jpeg_bytes in frames:
            img = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            img = cv2.GaussianBlur(img, (21, 21), 0)
            if prev_gray is not None:
                diff = cv2.absdiff(prev_gray, img)
                energies.append(float(np.mean(diff)) / 80.0)
            prev_gray = img

        if not energies:
            return {"confirmed": False, "score": 0.0}

        avg = float(np.mean(energies))
        return {"confirmed": avg > self.conf_threshold, "score": round(min(avg, 1.0), 3)}

    def _model_clip_verify(self, frames: List[Tuple[str, bytes]],
                           target_label: str) -> Dict[str, Any]:
        """
        Run X3D-S forward pass on a clip.

        Preprocessing: decode JPEG → resize 256×256 → centre-crop 224×224 →
        /255 → normalize(mean, std) → stack → [1, C, T, H, W].

        Output: softmax over Kinetics-400 classes.  Sum probabilities of
        violence/fall-related classes and compare to conf_threshold.
        """
        import torch

        target_labels = (
            _KINETICS_VIOLENCE_LABELS if target_label == "violence"
            else _KINETICS_FALL_LABELS
        )

        try:
            # Decode and preprocess frames
            imgs = []
            for _, jpeg_bytes in frames:
                img = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    continue
                img = cv2.resize(img, (256, 256))
                # Centre crop 224x224
                y0, x0 = (256 - 224) // 2, (256 - 224) // 2
                img = img[y0:y0+224, x0:x0+224]
                img = img[:, :, ::-1].astype(np.float32) / 255.0  # BGR→RGB, 0-1
                # Normalize (ImageNet-style)
                mean = np.array([0.45, 0.45, 0.45], dtype=np.float32)
                std = np.array([0.225, 0.225, 0.225], dtype=np.float32)
                img = (img - mean) / std
                imgs.append(img)

            if len(imgs) < 4:
                return self._stub_clip_verify(frames)

            # [T, H, W, C] → [C, T, H, W]
            clip = np.stack(imgs, axis=0)  # [T, H, W, C]
            clip = clip.transpose(3, 0, 1, 2)  # [C, T, H, W]
            clip_tensor = torch.from_numpy(clip).unsqueeze(0).to(self._torch_device)

            with torch.no_grad():
                logits = self._model(clip_tensor)
                probs = torch.softmax(logits, dim=1).squeeze(0).cpu().numpy()

            # Try to load Kinetics-400 label list
            try:
                from pytorchvideo.data.kinetics import KINETICS_400_LABELS  # type: ignore
                labels = KINETICS_400_LABELS
            except ImportError:
                # Fallback: use stub scoring
                return self._stub_clip_verify(frames)

            # Sum probabilities for target labels
            target_score = 0.0
            for idx, lbl in enumerate(labels):
                if lbl.lower() in {t.lower() for t in target_labels}:
                    target_score += float(probs[idx])

            confirmed = target_score > self.conf_threshold
            return {"confirmed": confirmed, "score": round(min(target_score, 1.0), 3)}

        except Exception as e:
            self.logger.warning(f"X3D-S forward pass failed ({e}), falling back to stub")
            return self._stub_clip_verify(frames)
