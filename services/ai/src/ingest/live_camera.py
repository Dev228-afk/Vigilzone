"""
Live camera (webcam) ingestion backend.

Uses OpenCV VideoCapture with a device index (0 = default webcam).
Supports the same interface as RTSP / file readers.
"""
import cv2
import threading
import time
import numpy as np
from typing import Tuple, Optional

from .base import IngestBackend
from ..common.timeutil import now_iso_utc
from ..common.log import setup_logger


class LiveCameraReader(IngestBackend):
    """Reads frames from a local webcam / USB camera using OpenCV."""

    def __init__(self, camera_id: str, camera_index: int = 0,
                 reconnect_delay: float = 3.0):
        # source is stored as the string representation of the index
        super().__init__(camera_id, str(camera_index))
        self.camera_index = camera_index
        self.reconnect_delay = reconnect_delay
        self.logger = setup_logger(f"LiveCamera-{camera_id}")

        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_ts: Optional[str] = None
        self._connected = False

    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        self.logger.info(f"Started live camera reader (index={self.camera_index})")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._cap:
            self._cap.release()
        self.logger.info("Stopped live camera reader")

    def get_latest(self) -> Tuple[Optional[np.ndarray], Optional[str]]:
        with self._lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy(), self._latest_ts
            return None, None

    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    def _connect(self) -> bool:
        try:
            # Force DSHOW on Windows for reliability + faster init
            idx = int(self.camera_index)
            self._cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)

            if not self._cap.isOpened():
                # Fallback if DSHOW fails (though rare on modern Windows)
                self._cap = cv2.VideoCapture(idx)
                if not self._cap.isOpened():
                    self._connected = False
                    return False

            ret, frame = self._cap.read()
            if ret and frame is not None:
                self._connected = True
                with self._lock:
                    self._latest_frame = frame
                    self._latest_ts = now_iso_utc()
                self.logger.info(f"Connected to webcam index {self.camera_index}")
                return True

            self._connected = False
            return False

        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            self._connected = False
            return False

    # ------------------------------------------------------------------
    def _read_loop(self):
        while self._running:
            if not self._connected:
                self.logger.info(f"Connecting to webcam index {self.camera_index}...")
                if self._connect():
                    self.logger.info("Webcam connected")
                else:
                    self.logger.warning(
                        f"Webcam connect failed, retrying in {self.reconnect_delay}s"
                    )
                    time.sleep(self.reconnect_delay)
                    continue

            try:
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    self.logger.warning("Frame read failed, reconnecting...")
                    self._connected = False
                    time.sleep(self.reconnect_delay)
                    continue

                with self._lock:
                    self._latest_frame = frame
                    self._latest_ts = now_iso_utc()

                time.sleep(0.01)   # ~100 fps max, prevents CPU spin

            except Exception as e:
                self.logger.error(f"Read error: {e}")
                self._connected = False
                time.sleep(self.reconnect_delay)
