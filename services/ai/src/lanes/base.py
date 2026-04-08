"""
Base interface for detection lanes
"""
from abc import ABC, abstractmethod
import numpy as np
from typing import Dict, Any, List, Optional
from ..common.types import Observation


class BaseLane(ABC):
    """Abstract base class for detection lanes"""
    
    def __init__(self, lane_name: str, camera_id: str, models_cfg: Dict[str, Any], device: str, zones: Optional[List[Dict[str, Any]]] = None):
        self.lane_name = lane_name
        self.camera_id = camera_id
        self.models_cfg = models_cfg
        self.device = device
        self.zones = zones or []
        self._initialized = False
    
    @abstractmethod
    def init(self):
        """Initialize models and resources"""
        pass
    
    @abstractmethod
    def infer(self, frame_bgr: np.ndarray, ts_utc: str) -> Observation:
        """
        Run inference on a frame
        Args:
            frame_bgr: BGR frame from OpenCV
            ts_utc: ISO 8601 timestamp
        Returns:
            Observation object
        """
        pass
    
    def cleanup(self):
        """Cleanup resources (optional)"""
        pass
