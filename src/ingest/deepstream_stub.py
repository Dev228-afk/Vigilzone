"""
DeepStream backend stub for future Linux/NVIDIA implementation
"""
from typing import Tuple, Optional
import numpy as np
from .base import IngestBackend
from ..common.log import setup_logger


class DeepStreamStub(IngestBackend):
    """
    DeepStream stub - not supported on Windows
    This is a placeholder for future Linux/NVIDIA implementation
    """
    
    def __init__(self, camera_id: str, source: str):
        super().__init__(camera_id, source)
        self.logger = setup_logger(f"DeepStreamStub-{camera_id}")
    
    def start(self):
        """Raise error - DeepStream not supported on Windows"""
        error_msg = (
            "DeepStream backend requires NVIDIA GPU + Linux (Ubuntu / WSL2) "
            "and is not supported in this Windows-native prototype. "
            "Please use 'ffmpeg' or 'opencv' backend instead. "
            "DeepStream support will be added later on proper infrastructure."
        )
        self.logger.error(error_msg)
        raise NotImplementedError(error_msg)
    
    def stop(self):
        """No-op"""
        pass
    
    def get_latest(self) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """Returns None - not implemented"""
        return None, None
    
    def is_connected(self) -> bool:
        """Returns False - not implemented"""
        return False
