"""
Base interface for video ingestion backends
"""
from abc import ABC, abstractmethod
from typing import Tuple, Optional
import numpy as np


class IngestBackend(ABC):
    """Abstract base class for video ingestion"""
    
    def __init__(self, camera_id: str, source: str):
        self.camera_id = camera_id
        self.source = source
        self._running = False
    
    @abstractmethod
    def start(self):
        """Start the ingestion backend"""
        pass
    
    @abstractmethod
    def stop(self):
        """Stop the ingestion backend"""
        pass
    
    @abstractmethod
    def get_latest(self) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """
        Get the latest frame (non-blocking)
        Returns: (frame_bgr, ts_utc) or (None, None) if no frame available
        """
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if backend is connected"""
        pass
