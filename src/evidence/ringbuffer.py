"""
Ring buffer for storing recent frames in memory
"""
import threading
import cv2
import numpy as np
from collections import deque
from typing import Optional, List, Tuple
from ..common.log import setup_logger


class FrameRingBuffer:
    """
    Thread-safe ring buffer for storing recent frames
    Stores frames as JPEG bytes to reduce memory usage
    """
    
    def __init__(self, camera_id: str, max_seconds: float = 20.0, fps: float = 10.0):
        """
        Args:
            camera_id: Camera identifier
            max_seconds: Maximum seconds of video to buffer
            fps: Expected frames per second to store
        """
        self.camera_id = camera_id
        self.max_frames = int(max_seconds * fps)
        self.logger = setup_logger(f"RingBuffer-{camera_id}")
        
        # Ring buffer: (timestamp, jpeg_bytes)
        self.buffer: deque = deque(maxlen=self.max_frames)
        self._lock = threading.Lock()
        
        self.logger.info(f"Initialized ring buffer: {max_seconds}s @ {fps}fps = {self.max_frames} frames")
    
    def add_frame(self, frame_bgr: np.ndarray, ts_utc: str):
        """
        Add a frame to the ring buffer
        Args:
            frame_bgr: BGR frame from OpenCV
            ts_utc: ISO UTC timestamp
        """
        try:
            # Encode to JPEG to save memory
            _, jpeg_bytes = cv2.imencode('.jpg', frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            jpeg_data = jpeg_bytes.tobytes()
            
            with self._lock:
                self.buffer.append((ts_utc, jpeg_data))
                
        except Exception as e:
            self.logger.error(f"Failed to add frame: {e}")
    
    def get_frames_before(self, ts_utc: str, seconds: float = 8.0) -> List[Tuple[str, bytes]]:
        """
        Get frames from specified seconds before a timestamp
        Args:
            ts_utc: Reference timestamp
            seconds: How many seconds before to retrieve
        Returns:
            List of (timestamp, jpeg_bytes) tuples
        """
        from ..common.timeutil import timestamp_diff_seconds
        
        with self._lock:
            result = []
            for frame_ts, jpeg_data in self.buffer:
                diff = timestamp_diff_seconds(frame_ts, ts_utc)
                if -seconds <= diff <= 0:
                    result.append((frame_ts, jpeg_data))
            return result
    
    def get_latest_frame(self) -> Optional[Tuple[str, bytes]]:
        """Get the most recent frame"""
        with self._lock:
            if len(self.buffer) > 0:
                return self.buffer[-1]
            return None
    
    def get_all_frames(self) -> List[Tuple[str, bytes]]:
        """Get all frames in buffer"""
        with self._lock:
            return list(self.buffer)
    
    def clear(self):
        """Clear the buffer"""
        with self._lock:
            self.buffer.clear()
        self.logger.info("Buffer cleared")
    
    def size(self) -> int:
        """Get current buffer size"""
        with self._lock:
            return len(self.buffer)
