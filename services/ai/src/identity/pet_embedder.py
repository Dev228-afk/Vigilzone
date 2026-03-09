"""
Pet embedder — CLIP image embedding for cat/dog recognition.

Primary:   open_clip (ViT-B-32)
Fallback:  color histogram (low accuracy, zero dependencies)

If neither CLIP is available → disabled gracefully.
"""
from __future__ import annotations

from typing import Dict, Any, Optional

import numpy as np

from ..common.log import setup_logger

logger = setup_logger("PetEmbedder")


class PetEmbedder:
    """Embed a cropped animal image to a vector for matching registered pets."""

    def __init__(self, cfg: Dict[str, Any]):
        self._enabled = cfg.get("enabled", True)
        self._embedder_type = cfg.get("embedder", "clip")  # clip | color_histogram
        self._clip_model_name = cfg.get("clip_model", "ViT-B-32")
        self._min_pet_area_ratio = cfg.get("min_pet_area_ratio", 0.01)
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._available = False
        self._dim = 0

        if self._enabled:
            self._try_load()

    # ── Load ──────────────────────────────────────────────────────────
    def _try_load(self):
        if self._embedder_type == "clip":
            try:
                import open_clip  # type: ignore
                import torch

                model, _, preprocess = open_clip.create_model_and_transforms(
                    self._clip_model_name, pretrained="openai",
                )
                model.eval()
                self._model = model
                self._preprocess = preprocess
                self._dim = model.visual.output_dim
                self._available = True
                logger.info(f"CLIP pet embedder loaded ({self._clip_model_name}, dim={self._dim})")
                return
            except ImportError:
                logger.warning("open_clip_torch not installed — trying color_histogram fallback")
            except Exception as e:
                logger.warning(f"CLIP init failed ({e}) — trying color_histogram fallback")
            # If CLIP fails, fall through to color_histogram
            self._embedder_type = "color_histogram"

        if self._embedder_type == "color_histogram":
            self._dim = 3 * 32  # 32 bins × 3 channels = 96-d
            self._available = True
            logger.info(f"Pet embedder using color_histogram fallback (dim={self._dim})")
            return

        logger.warning("Pet embedder DISABLED — no backend available")

    # ── Public API ────────────────────────────────────────────────────
    @property
    def available(self) -> bool:
        return self._available

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, crop_bgr: np.ndarray, frame_area: int = 0) -> Optional[np.ndarray]:
        """
        Embed an animal crop (BGR) to a unit-normalised vector.
        Returns None if unavailable or quality check fails.

        Parameters
        ----------
        crop_bgr : np.ndarray
            The cropped animal image.
        frame_area : int
            Total frame area (h*w). If >0, enforces min_pet_area_ratio check.
        """
        if not self._available:
            return None

        # Area ratio quality check
        if frame_area > 0 and self._min_pet_area_ratio > 0:
            crop_area = crop_bgr.shape[0] * crop_bgr.shape[1]
            if crop_area / frame_area < self._min_pet_area_ratio:
                return None

        if self._embedder_type == "clip":
            return self._embed_clip(crop_bgr)
        elif self._embedder_type == "color_histogram":
            return self._embed_histogram(crop_bgr)
        return None

    # ── CLIP embedding ────────────────────────────────────────────────
    def _embed_clip(self, crop_bgr: np.ndarray) -> Optional[np.ndarray]:
        try:
            import torch
            from PIL import Image
            import cv2

            rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            tensor = self._preprocess(pil_img).unsqueeze(0)

            with torch.no_grad():
                feat = self._model.encode_image(tensor)
            vec = feat.squeeze().cpu().numpy().astype(np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec
        except Exception as e:
            logger.error(f"CLIP embed error: {e}")
            return None

    # ── Color histogram fallback ──────────────────────────────────────
    def _embed_histogram(self, crop_bgr: np.ndarray) -> Optional[np.ndarray]:
        try:
            import cv2

            hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
            bins = 32
            hists = []
            for ch in range(3):
                hist = cv2.calcHist([hsv], [ch], None, [bins], [0, 256])
                hist = hist.flatten().astype(np.float32)
                total = hist.sum()
                if total > 0:
                    hist /= total
                hists.append(hist)
            vec = np.concatenate(hists)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec
        except Exception as e:
            logger.error(f"Histogram embed error: {e}")
            return None
