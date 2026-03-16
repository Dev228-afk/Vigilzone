"""
AnyAnomaly lane — wraps the subprocess-based AnyAnomaly client.

This lane does NOT run AnyAnomaly continuously.
It is triggered ONLY when:
  - AnomalyCLIP score crosses candidate_threshold (0.35-0.45), OR
  - Detector lane sees suspicious classes (weapon-like, fight-like), OR
  - Operator forces via force_anyanomaly flag

Outputs UNKNOWN_SEVERE_ANOMALY observations.
"""

import time
import numpy as np
from typing import Dict, Any, Optional, List
from collections import deque

from .base import BaseLane
from ..common.types import Observation
from ..common.log import setup_logger


class AnyAnomalyLane(BaseLane):
    """
    AnyAnomaly lane that delegates to the subprocess worker via client.
    Uses a sliding window of frames for clip-based inference.
    """

    def __init__(self, lane_name: str, camera_id: str,
                 models_cfg: Dict[str, Any], device: str):
        super().__init__(lane_name, camera_id, models_cfg, device)
        self.logger = setup_logger(f"AnyAnomaly-{camera_id}")
        self._client = None  # Set externally by orchestrator
        self._frame_window: deque = deque(maxlen=64)  # ~4s @ 16 fps

        # Config
        cfg = models_cfg.get("models", {}).get("anyanomaly", {})
        self.sensitivity = cfg.get("sensitivity", 0.6)
        self.candidate_threshold = cfg.get("candidate_threshold", 0.40)
        self.max_clip_frames = int(cfg.get("max_clip_sec", 4) * cfg.get("clip_fps", 4))
        self.enabled = cfg.get("enabled", True)
        self._active = self.enabled
        self._disabled_reason: Optional[str] = None

        # Trigger state — set by aggregator / other lanes
        self._armed = False
        self._arm_reason = ""
        self._last_score = 0.0
        self._last_result_ts = 0.0
        self._pending_job_id: Optional[str] = None

    # ------------------------------------------------------------------
    def set_client(self, client):
        """Attach the AnyAnomalyClient (subprocess IPC)."""
        self._client = client

    def arm(self, reason: str = "anomalyclip_candidate"):
        """Arm the lane for next inference pass."""
        self._armed = True
        self._arm_reason = reason

    # ------------------------------------------------------------------
    def init(self):
        if not self.enabled:
            self.logger.info("AnyAnomaly disabled in config")
            self._active = False
        elif self._client and not self._client.is_available:
            self._active = False
            self.enabled = False
            self._disabled_reason = "worker_unavailable"
            self.logger.warning(
                "AnyAnomaly lane disabled for camera=%s because worker is unavailable. "
                "Other lanes continue normally.",
                self.camera_id,
            )
        self._initialized = True
        self.logger.info(
            f"AnyAnomaly lane ready (enabled={self.enabled}, "
            f"sensitivity={self.sensitivity}, "
            f"candidate_threshold={self.candidate_threshold})"
        )

    # ------------------------------------------------------------------
    def infer(self, frame_bgr: np.ndarray, ts_utc: str) -> Observation:
        """
        Main lane entry point, called at anomaly Hz.
        Accumulates frames. Only sends to worker when armed.
        """
        if not self._initialized:
            self.init()

        if not self.enabled:
            return Observation(
                ts_utc=ts_utc,
                camera_id=self.camera_id,
                lane=self.lane_name,
                score=0.0,
                trigger=False,
                label=None,
                debug={
                    "inference_ms": 0.0,
                    "disabled": True,
                    "disabled_reason": self._disabled_reason or "config_disabled",
                },
            )

        t0 = time.perf_counter()
        self._frame_window.append(frame_bgr.copy())

        # Check for completed results
        if self._client and self._pending_job_id:
            result = self._client.get_result(self._pending_job_id)
            if result:
                self._pending_job_id = None
                self._last_score = result.get("score", 0.0)
                self._last_result_ts = time.time()
                self.logger.info(
                    f"AnyAnomaly result: score={self._last_score:.3f} "
                    f"(debug={result.get('extra_debug', {})})"
                )

        score = self._last_score
        trigger = score >= self.sensitivity

        # If armed and client available, submit new request
        if self._armed and self._client and self._client.can_request(self.camera_id):
            self._submit_clip(ts_utc)
            self._armed = False

        dt = time.perf_counter() - t0

        return Observation(
            ts_utc=ts_utc,
            camera_id=self.camera_id,
            lane=self.lane_name,
            score=score,
            trigger=trigger,
            label="unknown_anomaly" if trigger else None,
            debug={
                "inference_ms": round(dt * 1000, 1),
                "armed": self._armed,
                "arm_reason": self._arm_reason,
                "worker_available": bool(self._client and self._client.is_available),
                "pending_job": self._pending_job_id,
                "sensitivity": self.sensitivity,
            },
        )

    # ------------------------------------------------------------------
    def _submit_clip(self, ts_utc: str):
        """Send accumulated frames to the worker subprocess."""
        if not self._client:
            return

        # Sample frames evenly from window
        frames = list(self._frame_window)
        if len(frames) > self.max_clip_frames:
            step = len(frames) / self.max_clip_frames
            indices = [int(i * step) for i in range(self.max_clip_frames)]
            frames = [frames[i] for i in indices]

        if not frames:
            return

        job_id = self._client.request(
            camera_id=self.camera_id,
            ts_utc=ts_utc,
            frames_bgr=frames,
        )
        if job_id:
            self._pending_job_id = job_id
            self.logger.debug(
                f"Submitted clip ({len(frames)} frames) as job {job_id} "
                f"reason={self._arm_reason}"
            )
