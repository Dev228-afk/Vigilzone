"""
RT-DETR detection lane — Phase-1 uses Ultralytics RTDETR directly.

Fallback cascade (handled by engine_loader):
    1. TensorRT FP16 engine
    2. ONNX GPU
    3. ONNX CPU
    4. Ultralytics .pt  ← Phase-1 default

Correct usage per spec:
    from ultralytics import RTDETR
    model = RTDETR("rtdetr-l.pt")

Spec §2: Treat Ultralytics rtdetr-l.pt as COCO classes ONLY.
  DO NOT map RT-DETR outputs to fire/smoke/weapon unless custom weights
  explicitly support those classes.
  class_allowlist in config controls which COCO classes are kept.
"""
import time
import numpy as np
from typing import Dict, Any, List, Optional, Set

from .base import BaseLane
from ..common.types import Observation
from ..common.log import setup_logger
from ..logic.engine_loader import load_detector_engine, DetectorEngine
from ..runtime.device import select_device


class RTDETRLane(BaseLane):
    """Primary detector lane backed by RT-DETR via Ultralytics or TRT/ONNX."""

    def __init__(self, lane_name: str, camera_id: str,
                 models_cfg: Dict[str, Any], device: str):
        super().__init__(lane_name, camera_id, models_cfg, device)
        self.engine: Optional[DetectorEngine] = None
        self.logger = setup_logger(f"RTDETRLane-{camera_id}")
        # Class allowlist from config (only these classes pass through)
        self._class_allowlist: Optional[Set[str]] = None

    # ------------------------------------------------------------------
    def init(self):
        cfg = self.models_cfg.get("models", {}).get("rt_detr", {})

        # Load class_allowlist from config — if present, only allow those classes
        allowlist = cfg.get("class_allowlist", None)
        if allowlist:
            self._class_allowlist = set(c.lower() for c in allowlist)
            self.logger.info(f"RT-DETR class allowlist: {self._class_allowlist}")
        else:
            # Default COCO subset — no fire/smoke/weapon from standard COCO model
            self._class_allowlist = {
                "person", "car", "truck", "bus", "motorcycle", "bicycle",
            }
            self.logger.info(f"RT-DETR using default COCO allowlist: {self._class_allowlist}")

        self.engine = load_detector_engine(self.models_cfg)
        dev = select_device(self.models_cfg)
        self._initialized = True
        self.logger.info(
            f"RT-DETR inference device: {dev.torch_device} "
            f"(runtime={self.engine.runtime})"
        )

    # ------------------------------------------------------------------
    def infer(self, frame_bgr: np.ndarray, ts_utc: str) -> Observation:
        if not self._initialized:
            self.init()

        t0 = time.perf_counter()
        dets = self.engine.infer(frame_bgr)
        dt = time.perf_counter() - t0

        # Pick highest-confidence detection FROM ALLOWLIST ONLY
        best_score = 0.0
        best_bbox = None
        best_label = None
        trigger = False
        kept = 0
        dropped = 0

        for d in dets:
            label = d.label.lower() if d.label else ""

            # --- Allowlist filter ---
            if self._class_allowlist and label not in self._class_allowlist:
                dropped += 1
                continue

            kept += 1
            if d.score > best_score:
                best_score = d.score
                best_bbox = [int(c) for c in d.bbox]
                best_label = label
                trigger = True

        return Observation(
            ts_utc=ts_utc,
            camera_id=self.camera_id,
            lane=self.lane_name,
            score=best_score,
            trigger=trigger,
            bbox=best_bbox,
            label=best_label,
            debug={
                "runtime": self.engine.runtime,
                "inference_ms": round(dt * 1000, 1),
                "num_detections": len(dets),
                "num_kept": kept,
                "num_dropped_allowlist": dropped,
                "detector_runtime": self.engine.runtime,
            },
        )
