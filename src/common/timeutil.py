"""
Time utilities
"""
from datetime import datetime, timezone


def now_iso_utc() -> str:
    """Return current UTC time in ISO 8601 format"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso_utc(ts: str) -> datetime:
    """Parse ISO 8601 timestamp to datetime"""
    # Handle both with and without 'Z' suffix
    if ts.endswith('Z'):
        ts = ts[:-1] + '+00:00'
    return datetime.fromisoformat(ts)


def timestamp_diff_seconds(ts1: str, ts2: str) -> float:
    """Calculate difference in seconds between two ISO timestamps"""
    dt1 = parse_iso_utc(ts1)
    dt2 = parse_iso_utc(ts2)
    return (dt2 - dt1).total_seconds()
