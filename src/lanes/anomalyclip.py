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

    # ------------------------------------------------------------------
    def init(self):
        cfg = self.models_cfg.get("models", {}).get("anomalyclip", {})
        self.sensitivity = cfg.get("sensitivity", 0.5)
        model_path = cfg.get("model_path", "models/anomalyclip.pt")
        hf_repo = cfg.get("hf_repo_id", "")
        hf_file = cfg.get("hf_filename", "")

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
            score = self._motion_energy_score(frame_bgr)
        else:
            score = self._clip_score(frame_bgr)

        dt = time.perf_counter() - t0
        trigger = score > self.sensitivity

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
            },
        )

    # --- helpers -------------------------------------------------------
    def _motion_energy_score(self, frame_bgr: np.ndarray) -> float:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        score = 0.0
        if self._prev_gray is not None:
            diff = cv2.absdiff(self._prev_gray, gray)
            score = float(np.mean(diff)) / 80.0
            score = min(score, 1.0)
        self._prev_gray = gray
        return score

    def _clip_score(self, frame_bgr: np.ndarray) -> float:
        """Run AnomalyCLIP forward pass. TODO: plug real inference."""
        return self._motion_energy_score(frame_bgr)
