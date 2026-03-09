"""
Auto-throttle — EMA-based adaptive sample_hz control per camera.

Tracks detector runtime via exponential moving average.
If rtdetr_ema_ms > target_ms, reduces detector sample_hz gradually.
If recovered, slowly increases back (capped at configured max).

Also provides per-camera effective_sample_hz for /metrics.
"""

import time
import threading
from typing import Dict, Any, Optional

from ..common.log import setup_logger


class AutoThrottle:
    """
    Per-camera adaptive sampling control.
    Adjusts detector Hz based on inference latency EMA.
    """

    def __init__(self, target_ms: float = 120.0, alpha: float = 0.1,
                 min_hz: float = 0.5, default_max_hz: float = 2.0):
        """
        Args:
            target_ms: Target detector latency (ms). If EMA exceeds this, throttle.
            alpha: EMA smoothing factor (0 < alpha < 1). Higher = more responsive.
            min_hz: Minimum sample Hz (never go below this).
            default_max_hz: Default max Hz per camera (overridden by config).
        """
        self.target_ms = target_ms
        self.alpha = alpha
        self.min_hz = min_hz
        self.default_max_hz = default_max_hz
        self.logger = setup_logger("AutoThrottle")

        # Per camera state
        self._state: Dict[str, Dict[str, float]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def _get_state(self, camera_id: str, max_hz: float = None) -> Dict[str, float]:
        """Get or initialize per-camera state."""
        if camera_id not in self._state:
            mhz = max_hz or self.default_max_hz
            self._state[camera_id] = {
                "ema_ms": 0.0,
                "current_hz": mhz,
                "max_hz": mhz,
                "last_update": time.time(),
            }
        return self._state[camera_id]

    # ------------------------------------------------------------------
    def update(self, camera_id: str, inference_ms: float,
               max_hz: float = None) -> float:
        """
        Report a detector inference latency and get the adjusted Hz.

        Args:
            camera_id: Camera identifier.
            inference_ms: Latest inference time in ms.
            max_hz: Max Hz from config (used on first call).

        Returns:
            Adjusted detector sample Hz for this camera.
        """
        with self._lock:
            state = self._get_state(camera_id, max_hz)

            # Update EMA
            if state["ema_ms"] == 0.0:
                state["ema_ms"] = inference_ms
            else:
                state["ema_ms"] = self.alpha * inference_ms + (1 - self.alpha) * state["ema_ms"]

            # Throttle logic
            ema = state["ema_ms"]
            current_hz = state["current_hz"]
            max_hz_val = state["max_hz"]

            if ema > self.target_ms:
                # Reduce Hz gradually
                reduction = 0.9  # 10% reduction per overrun
                new_hz = max(current_hz * reduction, self.min_hz)
                if new_hz < current_hz:
                    self.logger.debug(
                        f"[{camera_id}] Throttling: ema={ema:.0f}ms > target={self.target_ms}ms, "
                        f"Hz {current_hz:.2f} → {new_hz:.2f}"
                    )
                state["current_hz"] = new_hz
            elif ema < self.target_ms * 0.7:
                # Recover slowly (5% increase per good reading)
                recovery = 1.05
                new_hz = min(current_hz * recovery, max_hz_val)
                state["current_hz"] = new_hz

            state["last_update"] = time.time()
            return state["current_hz"]

    # ------------------------------------------------------------------
    def get_effective_hz(self, camera_id: str) -> float:
        """Get current effective Hz for a camera."""
        with self._lock:
            state = self._state.get(camera_id)
            if state:
                return state["current_hz"]
            return self.default_max_hz

    def get_ema_ms(self, camera_id: str) -> float:
        """Get current EMA latency for a camera."""
        with self._lock:
            state = self._state.get(camera_id)
            if state:
                return state["ema_ms"]
            return 0.0

    # ------------------------------------------------------------------
    def get_metrics(self) -> Dict[str, Dict[str, float]]:
        """Return per-camera throttle state for /metrics."""
        with self._lock:
            return {
                cam_id: {
                    "ema_ms": round(s["ema_ms"], 1),
                    "effective_hz": round(s["current_hz"], 2),
                    "max_hz": s["max_hz"],
                }
                for cam_id, s in self._state.items()
            }
