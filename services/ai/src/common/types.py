"""
Core data types for the AI module
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import numpy as np


def _sanitize(obj):
    """Recursively convert numpy scalars/arrays to JSON-safe Python types."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


@dataclass
class Observation:
    """Single detection observation from a lane"""
    ts_utc: str  # ISO 8601 timestamp
    camera_id: str
    lane: str           # rt_detr | yolov8 | fire_yolo | anyanomaly | anomalyclip | temporal_verifier | person_zone | ...
    score: float
    trigger: bool
    bbox: Optional[List[int]] = None
    label: Optional[str] = None
    zone_name: Optional[str] = None
    track_id: Optional[int] = None
    debug: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize(asdict(self))


@dataclass
class Alert:
    """Confirmed alert after K-of-N voting"""
    ts_utc: str
    camera_id: str
    type: str  # INTRUSION_PERSON_IN_ZONE, FIRE_SMOKE, VIOLENCE_FIGHT, UNKNOWN_SEVERE_ANOMALY
    severity: str  # SEVERE, HIGH, MED, LOW
    confidence: float
    k_of_n: Dict[str, int]  # {"k": 3, "n": 5, "hits": 4}
    session_id: str = ""     # SHA-256 dedupe session id
    cooldown_s: int = 45
    evidence: Dict[str, Any] = field(default_factory=lambda: {
        "keyframe_path": "",
        "clip_path": "",
        "partial_clip": False,
    })
    payload: Dict[str, Any] = field(default_factory=dict)
    debug: Dict[str, Any] = field(default_factory=dict)
    # Structured payload sub-fields tracked for spec compliance
    label: str = ""
    # Identity entity (§9): populated when identity subsystem is active
    entity: Dict[str, Any] = field(default_factory=lambda: {
        "id": None,
        "name": None,
        "category": None,
        "confidence": 0.0,
    })

    def to_dict(self) -> Dict[str, Any]:
        return _sanitize(asdict(self))


def now_iso_utc() -> str:
    """Return current UTC time in ISO 8601 format"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
