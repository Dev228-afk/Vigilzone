"""
Face embedder — InsightFace FaceAnalysis (buffalo_l).

Provides:
  • detect_faces(frame_bgr) → list of FaceResult
  • embed_face(aligned_face) → 512-d normalised vector

Graceful degradation: if ``insightface`` is not installed → disabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

from ..common.log import setup_logger

logger = setup_logger("FaceEmbedder")


@dataclass
class FaceResult:
    bbox: List[int]           # [x1, y1, x2, y2]
    det_score: float          # detection confidence
    embedding: np.ndarray     # 512-d float32, L2-normalised
    aligned: Optional[np.ndarray] = None   # aligned face crop (112×112 BGR)
    quality_ok: bool = True   # passed sharpness / pose gating
    sharpness: float = 0.0    # Laplacian variance of face crop
    yaw: Optional[float] = None
    pitch: Optional[float] = None


class FaceEmbedder:
    """InsightFace-backed face detector + embedder."""

    def __init__(self, cfg: Dict[str, Any]):
        self._enabled = cfg.get("enabled", True)
        self._provider = cfg.get("provider", "insightface")
        self._model_pack = cfg.get("model_pack", "buffalo_l")
        self._det_size: Tuple[int, int] = tuple(cfg.get("det_size", [640, 640]))
        self._min_face_px = cfg.get("min_face_px", 60)
        self._min_det_score = cfg.get("min_det_score", 0.65)
        self._min_sharpness = cfg.get("min_sharpness", 35.0)
        self._max_abs_yaw = cfg.get("max_abs_yaw", 35)
        self._max_abs_pitch = cfg.get("max_abs_pitch", 25)

        # GPU: auto-detect via centralized device selection
        # InsightFace uses ORT — so check ort_cuda, NOT torch_gpu
        self._use_gpu = False
        try:
            from ..runtime.device import select_device
            dev_info = select_device({"device": "auto"})
            self._use_gpu = dev_info.ort_cuda   # ORT CUDA independent of torch
        except Exception:
            self._use_gpu = cfg.get("gpu", False)

        self._app = None       # insightface.app.FaceAnalysis
        self._available = False

        if self._enabled:
            self._try_load()

    # ── Load ──────────────────────────────────────────────────────────
    def _try_load(self):
        try:
            from insightface.app import FaceAnalysis  # type: ignore
            # Use CUDAExecutionProvider when ORT has CUDA (determined by device.py).
            providers = (
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if self._use_gpu
                else ["CPUExecutionProvider"]
            )
            self._app = FaceAnalysis(
                name=self._model_pack,
                allowed_modules=["detection", "recognition"],
                providers=providers,
            )
            ctx_id = 0 if self._use_gpu else -1
            self._app.prepare(ctx_id=ctx_id, det_size=self._det_size)
            self._available = True
            prov = "GPU" if self._use_gpu else "CPU"
            logger.info(f"InsightFace loaded ({prov}) — pack={self._model_pack}, det_size={self._det_size}")
        except ImportError:
            logger.warning("insightface not installed — face identity DISABLED")
            self._available = False
        except Exception as e:
            # If GPU load fails, retry with CPU only
            if self._use_gpu:
                logger.warning(f"InsightFace GPU init failed ({e}), falling back to CPU")
                self._use_gpu = False
                self._try_load()  # recursive retry with CPU
                return
            logger.warning(f"InsightFace init failed ({e}) — face identity DISABLED")
            self._available = False

    # ── Public API ────────────────────────────────────────────────────
    @property
    def available(self) -> bool:
        return self._available

    def detect_faces(self, frame_bgr: np.ndarray) -> List[FaceResult]:
        """
        Detect + embed all faces in a BGR frame.

        Returns list of FaceResult ordered by detection score (highest first).
        Only faces >= min_face_px and >= min_det_score are included.
        Quality gating (sharpness, yaw/pitch) sets quality_ok flag.
        """
        if not self._available:
            return []

        try:
            faces = self._app.get(frame_bgr)
        except Exception as e:
            logger.error(f"Face detection error: {e}")
            return []

        results: List[FaceResult] = []
        for face in faces:
            bbox = face.bbox.astype(int).tolist()  # [x1, y1, x2, y2]
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w < self._min_face_px or h < self._min_face_px:
                continue
            det_score = float(face.det_score)
            if det_score < self._min_det_score:
                continue

            embedding = face.normed_embedding  # already L2-normalised by InsightFace
            if embedding is None:
                continue
            embedding = embedding.astype(np.float32)
            # Double-check unit norm
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            # ── Quality gating ────────────────────────────────────────
            quality_ok = True
            sharpness_val = 0.0

            # Sharpness: Laplacian variance on face crop
            try:
                import cv2
                x1c = max(0, bbox[0])
                y1c = max(0, bbox[1])
                x2c = min(frame_bgr.shape[1], bbox[2])
                y2c = min(frame_bgr.shape[0], bbox[3])
                face_crop = frame_bgr[y1c:y2c, x1c:x2c]
                if face_crop.size > 0:
                    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
                    sharpness_val = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                    if sharpness_val < self._min_sharpness:
                        quality_ok = False
            except Exception:
                pass  # if cv2 fails, skip sharpness check

            # Yaw / pitch gating (from InsightFace pose if available)
            yaw_val = None
            pitch_val = None
            try:
                if hasattr(face, 'pose') and face.pose is not None:
                    pose = face.pose  # [yaw, pitch, roll] in degrees
                    yaw_val = float(pose[0])
                    pitch_val = float(pose[1])
                    if abs(yaw_val) > self._max_abs_yaw:
                        quality_ok = False
                    if abs(pitch_val) > self._max_abs_pitch:
                        quality_ok = False
            except Exception:
                pass  # pose not available, skip gracefully

            results.append(FaceResult(
                bbox=bbox,
                det_score=det_score,
                embedding=embedding,
                quality_ok=quality_ok,
                sharpness=sharpness_val,
                yaw=yaw_val,
                pitch=pitch_val,
            ))

        # Sort by detection score descending
        results.sort(key=lambda f: f.det_score, reverse=True)
        return results

    def embed_from_crop(self, face_crop_bgr: np.ndarray) -> Optional[np.ndarray]:
        """
        Given a face crop (not full frame), detect + embed the single best
        face.  Used for enrollment images.

        Returns 512-d unit vector or None.
        """
        faces = self.detect_faces(face_crop_bgr)
        if not faces:
            return None
        return faces[0].embedding

    def detect_faces_on_crop(self, person_crop: np.ndarray,
                              offset_x: int = 0, offset_y: int = 0) -> List[FaceResult]:
        """
        Run face detection on a person crop instead of full frame.
        Adjusts bboxes back to full-frame coordinates via offset.
        """
        results = self.detect_faces(person_crop)
        for fr in results:
            fr.bbox = [
                fr.bbox[0] + offset_x,
                fr.bbox[1] + offset_y,
                fr.bbox[2] + offset_x,
                fr.bbox[3] + offset_y,
            ]
        return results
