"""
AnyAnomaly client — main-process side.

Manages the AnyAnomaly subprocess lifecycle and IPC.
Provides a simple API:
  - start()       → launch worker process
  - request()     → submit a clip for scoring (non-blocking)
  - get_result()  → poll for latest result
  - stop()        → graceful shutdown

Rate limiting: max 1 request per camera per 5 seconds.
"""

import time
import uuid
import base64
import logging
import threading
from multiprocessing import Process, Queue
from typing import Dict, Any, Optional, List

import numpy as np
import cv2

from ..common.log import setup_logger


class AnyAnomalyClient:
    """Client that talks to the AnyAnomaly subprocess worker."""

    def __init__(self, config: Dict[str, Any]):
        """
        config: the 'anyanomaly' section from models.yaml
        """
        self.config = config
        self.enabled = config.get("enabled", True)
        self.sensitivity = config.get("sensitivity", 0.6)
        self.candidate_threshold = config.get("candidate_threshold", 0.40)
        self.max_clip_sec = config.get("max_clip_sec", 4.0)
        self.clip_fps = config.get("clip_fps", 4)

        self.logger = setup_logger("AnyAnomalyClient")

        self._request_queue: Optional[Queue] = None
        self._response_queue: Optional[Queue] = None
        self._process: Optional[Process] = None
        self._running = False
        self._worker_enabled = False

        # Rate limiting: max 1 request per camera per 5s
        self._rate_limit_s = 5.0
        self._last_request_time: Dict[str, float] = {}

        # Pending jobs
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self._results_lock = threading.Lock()

        # Background thread to drain response queue
        self._drain_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    def start(self):
        """Launch the AnyAnomaly worker subprocess."""
        if not self.enabled:
            self.logger.info("AnyAnomaly disabled in config")
            return

        self._request_queue = Queue(maxsize=16)
        self._response_queue = Queue(maxsize=64)

        from .anyanomaly_worker import worker_loop

        self._process = Process(
            target=worker_loop,
            args=(self._request_queue, self._response_queue, self.config),
            daemon=True,
            name="AnyAnomaly-Worker",
        )
        self._process.start()
        self._running = True

        # Wait for worker status
        try:
            status = self._response_queue.get(timeout=30)
            if status.get("type") == "status":
                self._worker_enabled = status.get("enabled", False)
                self.logger.info(
                    f"AnyAnomaly worker started (enabled={self._worker_enabled}, pid={self._process.pid})"
                )
        except Exception:
            self.logger.warning("AnyAnomaly worker did not report status in time")
            self._worker_enabled = False

        # Start drain thread
        self._drain_thread = threading.Thread(target=self._drain_responses, daemon=True)
        self._drain_thread.start()

    # ------------------------------------------------------------------
    def stop(self):
        """Gracefully shut down the worker."""
        self._running = False
        if self._request_queue:
            try:
                self._request_queue.put(None, timeout=2)  # Poison pill
            except Exception:
                pass
        if self._process and self._process.is_alive():
            self._process.join(timeout=10)
            if self._process.is_alive():
                self._process.terminate()
                self.logger.warning("AnyAnomaly worker terminated forcibly")
        self.logger.info("AnyAnomaly client stopped")

    # ------------------------------------------------------------------
    def can_request(self, camera_id: str) -> bool:
        """Check rate limit for a camera."""
        if not self._running or not self._worker_enabled:
            return False
        last = self._last_request_time.get(camera_id, 0)
        return (time.time() - last) >= self._rate_limit_s

    # ------------------------------------------------------------------
    def request(self, camera_id: str, ts_utc: str,
                frames_bgr: List[np.ndarray],
                prompt_text: str = "") -> Optional[str]:
        """
        Submit a clip for AnyAnomaly scoring.
        Returns job_id if submitted, None if rate-limited or queue full.
        """
        if not self.can_request(camera_id):
            return None

        # Mark rate limit
        self._last_request_time[camera_id] = time.time()

        # Encode frames as JPEG base64
        frames_b64 = []
        for frame in frames_bgr:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            frames_b64.append(base64.b64encode(buf.tobytes()).decode("ascii"))

        job_id = str(uuid.uuid4())[:12]

        request_msg = {
            "job_id": job_id,
            "camera_id": camera_id,
            "ts_utc": ts_utc,
            "prompt_text": prompt_text,
            "frames_b64_list": frames_b64,
        }

        try:
            self._request_queue.put_nowait(request_msg)
            with self._results_lock:
                self._pending[job_id] = {"camera_id": camera_id, "ts_utc": ts_utc}
            self.logger.debug(f"Submitted AnyAnomaly job {job_id} for {camera_id}")
            return job_id
        except Exception:
            self.logger.warning("AnyAnomaly request queue full, dropping request")
            return None

    # ------------------------------------------------------------------
    def get_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get result for a specific job, or None if not ready."""
        with self._results_lock:
            return self._results.pop(job_id, None)

    def get_latest_result(self, camera_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent result for a camera, or None."""
        with self._results_lock:
            latest = None
            to_remove = []
            for jid, res in self._results.items():
                if res.get("camera_id") == camera_id:
                    latest = res
                    to_remove.append(jid)
            for jid in to_remove:
                del self._results[jid]
            return latest

    # ------------------------------------------------------------------
    def _drain_responses(self):
        """Background thread: continuously drain response queue."""
        while self._running:
            try:
                response = self._response_queue.get(timeout=1.0)
                if response.get("type") == "result":
                    job_id = response["job_id"]
                    with self._results_lock:
                        self._results[job_id] = response
                        self._pending.pop(job_id, None)
                    # Keep results bounded
                    if len(self._results) > 100:
                        oldest = list(self._results.keys())[:50]
                        for k in oldest:
                            self._results.pop(k, None)
            except Exception:
                pass  # timeout or empty queue

    # ------------------------------------------------------------------
    @property
    def is_available(self) -> bool:
        return self._running and self._worker_enabled

    @property
    def pending_count(self) -> int:
        return len(self._pending)
