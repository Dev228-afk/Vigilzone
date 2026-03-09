"""
Deduper – session-based alert deduplication.

Generates a ``session_id`` (SHA-256) for each fired alert.
Subsequent alerts within cooldown that share the same dedupe key
(camera_id + label + approximate timestamp bucket) are appended
to the existing session instead of spawning a new one.
"""
import hashlib
import time
from typing import Dict, Optional
from ..common.log import setup_logger
from ..common.timeutil import now_iso_utc, timestamp_diff_seconds


class Deduper:
    """Alert session deduplication manager."""

    def __init__(self, session_window_s: float = 45.0):
        """
        Args:
            session_window_s: Window in seconds within which repeated events
                for the same key are considered the same session.
        """
        self.session_window_s = session_window_s
        # key → {"session_id": str, "ts": str, "count": int}
        self._sessions: Dict[str, Dict] = {}
        self.logger = setup_logger("Deduper")

    # ------------------------------------------------------------------
    def get_session_id(self, camera_id: str, label: str,
                       ts_utc: str,
                       track_id: Optional[int] = None) -> str:
        """
        Return (or create) a session_id for this event.

        The dedupe key is built from ``camera_id + label + track_id``.
        If a session already exists within the window → return same id.
        Otherwise create a new session.
        """
        key = self._make_key(camera_id, label, track_id)

        if key in self._sessions:
            existing = self._sessions[key]
            elapsed = timestamp_diff_seconds(existing["ts"], ts_utc)
            if elapsed <= self.session_window_s:
                existing["count"] += 1
                existing["ts"] = ts_utc  # slide window forward
                return existing["session_id"]

        # New session
        session_id = self._hash(camera_id, label, ts_utc, track_id)
        self._sessions[key] = {
            "session_id": session_id,
            "ts": ts_utc,
            "count": 1,
        }
        return session_id

    # ------------------------------------------------------------------
    def is_duplicate(self, camera_id: str, label: str,
                     ts_utc: str,
                     track_id: Optional[int] = None) -> bool:
        """Return True if this event already has an active session (i.e. duplicate)."""
        key = self._make_key(camera_id, label, track_id)
        if key not in self._sessions:
            return False
        existing = self._sessions[key]
        elapsed = timestamp_diff_seconds(existing["ts"], ts_utc)
        return elapsed <= self.session_window_s

    # ------------------------------------------------------------------
    def cleanup(self, current_ts: Optional[str] = None):
        """Remove expired sessions."""
        if current_ts is None:
            current_ts = now_iso_utc()
        expired = []
        for key, sess in self._sessions.items():
            if timestamp_diff_seconds(sess["ts"], current_ts) > self.session_window_s * 2:
                expired.append(key)
        for k in expired:
            del self._sessions[k]

    # --- internal ------------------------------------------------------
    @staticmethod
    def _make_key(camera_id: str, label: str,
                  track_id: Optional[int] = None) -> str:
        parts = [camera_id, label]
        if track_id is not None:
            parts.append(str(track_id))
        return "|".join(parts)

    @staticmethod
    def _hash(camera_id: str, label: str, ts_utc: str,
              track_id: Optional[int] = None) -> str:
        raw = f"{camera_id}:{label}:{ts_utc}:{track_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
