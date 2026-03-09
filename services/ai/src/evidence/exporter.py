"""
Evidence exporter – keyframe + clip (5 s pre + 5 s post) from ring buffer.

If post-alert frames are not yet available, waits up to ``post_wait_timeout``
seconds.  If still insufficient, exports what is available and flags
``partial_clip=true``.
"""
import time
import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict
from ..common.log import setup_logger
from ..common.timeutil import now_iso_utc, timestamp_diff_seconds
from .ringbuffer import FrameRingBuffer


class EvidenceExporter:
    """Exports evidence (keyframe + video clip) from ring buffer."""

    def __init__(self, evidence_dir: str = "evidence",
                 post_wait_timeout: float = 6.0):
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.post_wait_timeout = post_wait_timeout
        self.logger = setup_logger("EvidenceExporter")

    # ------------------------------------------------------------------
    def export_evidence(
        self,
        camera_id: str,
        alert_type: str,
        ts_utc: str,
        ringbuffer: FrameRingBuffer,
        pre_seconds: float = 5.0,
        post_seconds: float = 5.0,
    ) -> Dict[str, object]:
        """
        Export keyframe + clip (pre_seconds before + post_seconds after event).

        Returns:
            {"keyframe_path": str, "clip_path": str, "partial_clip": bool}
        """
        try:
            cam_dir = self.evidence_dir / camera_id
            cam_dir.mkdir(parents=True, exist_ok=True)

            safe_ts = ts_utc.replace(":", "-").replace(".", "-")
            keyframe_path = cam_dir / f"{safe_ts}_{alert_type}.jpg"
            clip_path = cam_dir / f"{safe_ts}_{alert_type}.mp4"

            # 1. Gather PRE frames
            pre_frames = ringbuffer.get_frames_before(ts_utc, seconds=pre_seconds)

            # 2. Wait for POST frames (up to post_wait_timeout)
            partial_clip = False
            post_frames: List[Tuple[str, bytes]] = []
            waited = 0.0
            poll = 0.5
            while waited < self.post_wait_timeout:
                time.sleep(poll)
                waited += poll
                all_frames = ringbuffer.get_all_frames()
                post_frames = [
                    (t, d)
                    for t, d in all_frames
                    if timestamp_diff_seconds(ts_utc, t) > 0
                ]
                if post_frames:
                    latest_post = post_frames[-1]
                    if timestamp_diff_seconds(ts_utc, latest_post[0]) >= post_seconds:
                        break
            else:
                partial_clip = True

            # Trim post frames to at most post_seconds
            post_frames = [
                (t, d)
                for t, d in post_frames
                if 0 < timestamp_diff_seconds(ts_utc, t) <= post_seconds
            ]

            frames = pre_frames + post_frames

            if not frames:
                latest = ringbuffer.get_latest_frame()
                if latest:
                    frames = [latest]
                else:
                    return {
                        "keyframe_path": str(keyframe_path),
                        "clip_path": str(clip_path),
                        "partial_clip": True,
                    }

            # 3. Export keyframe (highest-confidence → just use middle frame ±2 s)
            keyframe_idx = len(pre_frames) - 1 if pre_frames else 0
            keyframe_idx = max(0, min(keyframe_idx, len(frames) - 1))
            self._export_keyframe(frames[keyframe_idx][1], keyframe_path)

            # 4. Export clip
            self._export_clip(frames, clip_path)

            self.logger.info(
                f"Evidence exported for {camera_id}/{alert_type}: "
                f"keyframe={keyframe_path.name}, clip={clip_path.name}, "
                f"partial={partial_clip}"
            )
            return {
                "keyframe_path": str(keyframe_path),
                "clip_path": str(clip_path),
                "partial_clip": partial_clip,
            }

        except Exception as e:
            self.logger.error(f"Failed to export evidence: {e}")
            return {"keyframe_path": "", "clip_path": "", "partial_clip": True}

    # ------------------------------------------------------------------
    def _export_keyframe(self, jpeg_bytes: bytes, output_path: Path):
        try:
            with open(output_path, "wb") as f:
                f.write(jpeg_bytes)
        except Exception as e:
            self.logger.error(f"Keyframe export failed: {e}")

    # ------------------------------------------------------------------
    def _export_clip(self, frames: List[Tuple[str, bytes]],
                     output_path: Path, fps: float = 10.0):
        try:
            if not frames:
                return

            first_frame = cv2.imdecode(
                np.frombuffer(frames[0][1], dtype=np.uint8), cv2.IMREAD_COLOR
            )
            h, w = first_frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

            for _, jpeg_bytes in frames:
                frame = cv2.imdecode(
                    np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR
                )
                if frame is not None:
                    writer.write(frame)

            writer.release()
        except Exception as e:
            self.logger.error(f"Clip export failed: {e}")

    # ------------------------------------------------------------------
    def cleanup_old_evidence(self, days: int = 7):
        """Delete evidence older than specified days. TODO: implement."""
        self.logger.info("Evidence cleanup not yet implemented")
