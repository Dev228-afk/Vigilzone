"""
Background snapshot cache — periodically grabs a frame for each camera
so the /api/streams/<id>/snapshot/ endpoint can return instantly.

Usage:
  start_snapshot_worker()   — call once from AppConfig.ready()
  get_cached_snapshot(pk)   — returns (jpeg_bytes, source, age_s) or None
"""

import logging
import os
import subprocess
import threading
import time

log = logging.getLogger("vigilzone.snapshot_cache")

# {camera_pk: {"data": bytes, "source": str, "ts": float}}
_store: dict[int, dict] = {}
_lock = threading.Lock()
_running = False

# How often to refresh each camera (seconds)
INTERVAL = float(os.getenv("SNAPSHOT_CACHE_INTERVAL", "2"))
# Maximum age before a cached image is considered stale
MAX_AGE = float(os.getenv("SNAPSHOT_CACHE_MAX_AGE", "5"))


def get_cached_snapshot(camera_pk: int):
    """Return (jpeg_bytes, source_str, age_seconds) or None."""
    with _lock:
        entry = _store.get(camera_pk)
    if entry is None:
        return None
    age = time.time() - entry["ts"]
    if age > MAX_AGE:
        return None
    return entry["data"], entry["source"], age


def _grab_frame(rtsp_url: str, ai_base: str, ai_cam_id: str):
    """Try ffmpeg then AI fallback.  Returns (jpeg_bytes, source) or (None, None)."""
    import requests as http_client

    # ffmpeg
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-rtsp_transport", "tcp",
                "-rw_timeout", "3000000",
                "-i", rtsp_url,
                "-frames:v", "1", "-q:v", "5",
                "-f", "image2", "-vcodec", "mjpeg",
                "pipe:1",
            ],
            capture_output=True,
            timeout=6,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout, "ffmpeg"
    except Exception:
        pass

    # AI fallback
    for endpoint in [
        f"{ai_base}/frame/{ai_cam_id}",
        f"{ai_base}/api/v1/cameras/{ai_cam_id}/snapshot",
        f"{ai_base}/api/v1/cameras/{ai_cam_id}/frame",
    ]:
        try:
            r = http_client.get(endpoint, timeout=2)
            ct = r.headers.get("Content-Type", "")
            if r.status_code == 200 and "image" in ct and r.content:
                return r.content, f"ai_fallback:{endpoint}"
        except Exception:
            continue

    return None, None


def _worker():
    """Background loop — runs in a daemon thread."""
    global _running
    log.info("Snapshot cache worker started  (interval=%.1fs, max_age=%.1fs)", INTERVAL, MAX_AGE)
    while _running:
        try:
            from api.models import Camera  # deferred import to avoid AppRegistryNotReady
            cameras = list(
                Camera.objects.filter(stream_path__isnull=False)
                .exclude(stream_path="")
                .values_list("pk", "rtsp_url", "stream_path", "ai_camera_id")
            )
        except Exception as exc:
            log.debug("snapshot_cache: cannot query cameras yet: %s", exc)
            time.sleep(INTERVAL)
            continue

        mediamtx_rtsp_base = os.getenv("MEDIAMTX_RTSP_BASE", "rtsp://127.0.0.1:8554")
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")

        for pk, rtsp_url, stream_path, ai_camera_id in cameras:
            if not _running:
                break
            ai_cam_id = ai_camera_id or f"cam_{pk}"
            url = rtsp_url or f"{mediamtx_rtsp_base}/{stream_path}"
            data, source = _grab_frame(url, ai_base, ai_cam_id)
            if data:
                with _lock:
                    _store[pk] = {"data": data, "source": source, "ts": time.time()}

        time.sleep(INTERVAL)

    log.info("Snapshot cache worker stopped")


def start_snapshot_worker():
    """Start the background thread (idempotent — only one worker runs)."""
    global _running
    if _running:
        return
    _running = True
    t = threading.Thread(target=_worker, daemon=True, name="snapshot-cache")
    t.start()
