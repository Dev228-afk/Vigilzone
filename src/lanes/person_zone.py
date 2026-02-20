"""
Person-in-zone detection lane using YOLO
"""
import numpy as np
from typing import Dict, Any, List
from pathlib import Path
from ultralytics import YOLO
from .base import BaseLane
from ..common.types import Observation
from ..logic.tracker_iou import IOUTracker
from ..logic.zones import check_bbox_in_zones
from ..common.log import setup_logger
from ..runtime.device import select_device


class PersonZoneLane(BaseLane):
    """Detects persons in restricted zones"""
    
    def __init__(self, lane_name: str, camera_id: str, models_cfg: Dict[str, Any], 
                 device: str, zones: List[Dict[str, Any]]):
        super().__init__(lane_name, camera_id, models_cfg, device)
        self.zones = zones
        self.tracker = IOUTracker(iou_threshold=0.3, max_age=30)
        self.model = None
        self.logger = setup_logger(f"PersonZoneLane-{camera_id}")
    
    def init(self):
        """Initialize YOLO model"""
        try:
            model_cfg = self.models_cfg['models']['person_detector']
            weights_path = model_cfg['weights']
            
            # Resolve relative path
            if not Path(weights_path).is_absolute():
                # Try relative to ai_module directory
                base_path = Path(__file__).parent.parent.parent
                weights_path = (base_path / weights_path).resolve()
            
            if not Path(weights_path).exists():
                self.logger.error(f"Model weights not found: {weights_path}")
                raise FileNotFoundError(f"Model weights not found: {weights_path}")
            
            self.logger.info(f"Loading YOLO model from {weights_path}")
            self.model = YOLO(str(weights_path))
            
            # Move to device — use centralized selection
            dev = select_device(self.models_cfg)
            actual_device = dev.torch_device
            self._ul_device = 0 if dev.torch_gpu else "cpu"
            
            self.model.to(actual_device)
            self.conf_threshold = model_cfg.get('conf', 0.25)
            self._initialized = True
            self.logger.info(f"Person detector initialized on {actual_device}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize person detector: {e}")
            raise
    
    def infer(self, frame_bgr: np.ndarray, ts_utc: str) -> Observation:
        """Run person detection and zone checking"""
        if not self._initialized:
            self.init()
        
        try:
            # Run YOLO detection
            results = self.model(frame_bgr, verbose=False, conf=self.conf_threshold,
                                classes=[0], device=self._ul_device)  # class 0 = person
            
            # Extract detections
            detections = []
            if len(results) > 0 and results[0].boxes is not None:
                boxes = results[0].boxes
                for i in range(len(boxes)):
                    box = boxes.xyxy[i].cpu().numpy()  # [x1, y1, x2, y2]
                    conf = float(boxes.conf[i])
                    detections.append((box.tolist(), conf))
            
            # Update tracker
            tracked = self.tracker.update(detections)
            
            # Check which detections are in zones
            max_score = 0.0
            trigger = False
            best_bbox = None
            best_zone = None
            best_track_id = None
            
            for box, conf, track_id in tracked:
                in_zone, zone_name = check_bbox_in_zones(box, self.zones)
                if in_zone and conf > max_score:
                    max_score = conf
                    trigger = True
                    best_bbox = [int(b) for b in box]
                    best_zone = zone_name
                    best_track_id = track_id
            
            return Observation(
                ts_utc=ts_utc,
                camera_id=self.camera_id,
                lane=self.lane_name,
                score=max_score,
                trigger=trigger,
                bbox=best_bbox,
                label="person",
                zone_name=best_zone,
                track_id=best_track_id,
                debug={"total_persons": len(tracked), "in_zone": trigger}
            )
            
        except Exception as e:
            self.logger.error(f"Inference error: {e}")
            return Observation(
                ts_utc=ts_utc,
                camera_id=self.camera_id,
                lane=self.lane_name,
                score=0.0,
                trigger=False,
                debug={"error": str(e)}
            )
