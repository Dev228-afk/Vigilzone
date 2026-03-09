"""
Cooldown manager to prevent alert spam
"""
from typing import Dict, Optional
from ..common.timeutil import now_iso_utc, timestamp_diff_seconds


class CooldownManager:
    """
    Manages cooldown periods per camera per alert type
    Prevents duplicate alerts within cooldown window
    """
    
    def __init__(self, default_cooldown_s: int = 45):
        self.default_cooldown_s = default_cooldown_s
        # Key: (camera_id, alert_type) -> last_fired_ts
        self.last_fired: Dict[tuple, str] = {}
    
    def can_fire(self, camera_id: str, alert_type: str, current_ts: Optional[str] = None) -> bool:
        """
        Check if alert can fire (not in cooldown)
        Args:
            camera_id: Camera identifier
            alert_type: Type of alert
            current_ts: Current timestamp (ISO UTC), uses now if None
        Returns:
            True if alert can fire (not in cooldown)
        """
        if current_ts is None:
            current_ts = now_iso_utc()
        
        key = (camera_id, alert_type)
        
        if key not in self.last_fired:
            return True
        
        last_ts = self.last_fired[key]
        elapsed = timestamp_diff_seconds(last_ts, current_ts)
        
        return elapsed >= self.default_cooldown_s
    
    def mark_fired(self, camera_id: str, alert_type: str, ts: Optional[str] = None):
        """
        Mark that an alert has fired
        Args:
            camera_id: Camera identifier
            alert_type: Type of alert
            ts: Timestamp (ISO UTC), uses now if None
        """
        if ts is None:
            ts = now_iso_utc()
        
        key = (camera_id, alert_type)
        self.last_fired[key] = ts
    
    def get_cooldown_remaining(self, camera_id: str, alert_type: str, current_ts: Optional[str] = None) -> float:
        """
        Get remaining cooldown time in seconds
        Returns:
            Seconds remaining in cooldown, 0 if not in cooldown
        """
        if current_ts is None:
            current_ts = now_iso_utc()
        
        key = (camera_id, alert_type)
        
        if key not in self.last_fired:
            return 0.0
        
        last_ts = self.last_fired[key]
        elapsed = timestamp_diff_seconds(last_ts, current_ts)
        remaining = self.default_cooldown_s - elapsed
        
        return max(0.0, remaining)
    
    def reset(self, camera_id: Optional[str] = None, alert_type: Optional[str] = None):
        """
        Reset cooldown state
        Args:
            camera_id: If specified, reset only this camera
            alert_type: If specified (with camera_id), reset only this alert type
        """
        if camera_id is None:
            self.last_fired.clear()
        elif alert_type is None:
            # Reset all alert types for this camera
            keys_to_remove = [k for k in self.last_fired.keys() if k[0] == camera_id]
            for key in keys_to_remove:
                del self.last_fired[key]
        else:
            # Reset specific camera + alert type
            key = (camera_id, alert_type)
            if key in self.last_fired:
                del self.last_fired[key]
