"""
FFmpeg-based video reader using subprocess
"""
import cv2
import subprocess
import threading
import time
import os
import numpy as np
from typing import Tuple, Optional
from .base import IngestBackend
from ..common.timeutil import now_iso_utc
from ..common.log import setup_logger


class FFmpegReader(IngestBackend):
    """
    FFmpeg backend using subprocess to decode RTSP streams
    Falls back to OpenCV if subprocess approach fails
    """
    
    def __init__(self, camera_id: str, source: str, reconnect_delay: float = 5.0, 
                 width: int = 640, height: int = 480):
        super().__init__(camera_id, source)
        
        # FORCE underlying OpenCV FFmpeg wrappers to drop dead connections
        # 5000000 microseconds = 5 seconds
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"

        self.reconnect_delay = reconnect_delay
        self.width = width
        self.height = height
        self.logger = setup_logger(f"FFmpegReader-{camera_id}")
        
        self._cap = None  # Fallback to OpenCV
        self._thread = None
        self._lock = threading.Lock()
        self._latest_frame = None
        self._latest_ts = None
        self._connected = False
        self._use_opencv_fallback = True  # Use OpenCV by default (simpler on Windows)
    
    def start(self):
        """Start the reader thread"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        self.logger.info(f"Started FFmpeg reader for {self.camera_id}")
    
    def stop(self):
        """Stop the reader thread"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._cap:
            self._cap.release()
        self.logger.info(f"Stopped FFmpeg reader for {self.camera_id}")
    
    def get_latest(self) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """Get the latest frame (non-blocking)"""
        with self._lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy(), self._latest_ts
            return None, None
    
    def is_connected(self) -> bool:
        """Check if connected"""
        return self._connected
    
    def _connect(self) -> bool:
        """Establish connection using OpenCV with FFmpeg backend"""
        try:
            if self._cap:
                self._cap.release()
            
            # Use OpenCV with FFmpeg backend (easier on Windows)
            self._cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
            
            if self._cap.isOpened():
                ret, frame = self._cap.read()
                if ret and frame is not None:
                    self._connected = True
                    self.logger.info(f"Connected to {self.source} via FFmpeg")
                    
                    with self._lock:
                        self._latest_frame = frame
                        self._latest_ts = now_iso_utc()
                    
                    return True
            
            self._connected = False
            return False
            
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            self._connected = False
            return False
    
    def _read_loop(self):
        """Main read loop with reconnect logic"""
        while self._running:
            if not self._connected:
                self.logger.info(f"Attempting to connect to {self.source}...")
                if self._connect():
                    self.logger.info(f"Successfully connected")
                else:
                    self.logger.warning(f"Connection failed, retrying in {self.reconnect_delay}s")
                    time.sleep(self.reconnect_delay)
                    continue
            
            try:
                ret, frame = self._cap.read()
                
                if not ret or frame is None:
                    self.logger.warning(f"Failed to read frame, reconnecting...")
                    self._connected = False
                    time.sleep(self.reconnect_delay)
                    continue
                
                with self._lock:
                    self._latest_frame = frame
                    self._latest_ts = now_iso_utc()
                
                time.sleep(0.01)
                
            except Exception as e:
                self.logger.error(f"Read error: {e}")
                self._connected = False
                time.sleep(self.reconnect_delay)
