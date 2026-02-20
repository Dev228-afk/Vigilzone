"""
Violence detection lane (motion-based stub)
"""
import numpy as np
import cv2
from typing import Dict, Any
from .base import BaseLane
from ..common.types import Observation
from ..common.log import setup_logger


class ViolenceLane(BaseLane):
    """
    Violence detection using motion energy heuristic
    This is a stub - replace with proper violence detection model later
    """
    
    def __init__(self, lane_name: str, camera_id: str, models_cfg: Dict[str, Any], device: str):
        super().__init__(lane_name, camera_id, models_cfg, device)
        self.prev_frame_gray = None
        self.logger = setup_logger(f"ViolenceLane-{camera_id}")
    
    def init(self):
        """Initialize (minimal setup for motion-based detection)"""
        model_cfg = self.models_cfg['models']['violence_detector']
        self.motion_threshold = model_cfg.get('motion_threshold', 45.0)
        self.score_threshold = model_cfg.get('threshold', 0.60)
        self._initialized = True
        self.logger.info(f"Violence detector initialized (motion-based stub)")
    
    def infer(self, frame_bgr: np.ndarray, ts_utc: str) -> Observation:
        """Compute motion energy as proxy for violence"""
        if not self._initialized:
            self.init()
        
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            
            # Compute motion if we have a previous frame
            motion_score = 0.0
            if self.prev_frame_gray is not None:
                # Frame difference
                diff = cv2.absdiff(self.prev_frame_gray, gray)
                motion_energy = np.mean(diff)
                
                # Normalize to 0-1 range
                motion_score = min(motion_energy / 100.0, 1.0)
            
            self.prev_frame_gray = gray.copy()
            
            # Trigger if motion energy exceeds threshold
            trigger = motion_score > (self.motion_threshold / 100.0)
            
            return Observation(
                ts_utc=ts_utc,
                camera_id=self.camera_id,
                lane=self.lane_name,
                score=motion_score,
                trigger=trigger,
                label="violence" if trigger else None,
                debug={"motion_energy": float(motion_score), "stub": True}
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
