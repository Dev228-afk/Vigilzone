"""
Identity matcher — cosine-similarity lookup with in-memory indices.

Supports multiple embeddings per entity with configurable strategies:
  - max:       score(entity) = max sim across stored embeddings
  - centroid:  score(entity) = sim(query, entity_centroid)
  - topk_avg:  score(entity) = avg of top-K similarities (default)

Matching requires:
  best_sim >= match_threshold_sim
  margin  (best_sim - second_best_sim) >= top2_margin

If FAISS is installed it accelerates the raw search; otherwise pure numpy.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from ..common.log import setup_logger
from .schema import EntityCategory, IdentityMatch
from .store import EntityStore

logger = setup_logger("IdentityMatcher")

# Try FAISS (optional acceleration)
try:
    import faiss  # type: ignore
    _HAS_FAISS = True
    logger.info("FAISS available — using accelerated index")
except ImportError:
    _HAS_FAISS = False


# ── Raw vector index (flat cosine via inner product on L2-normed vecs) ──

class _NumpyIndex:
    """Simple brute-force cosine index backed by numpy."""

    def __init__(self, entity_ids: List[str], matrix: np.ndarray):
        """
        Parameters
        ----------
        entity_ids : list[str]
            Entity ID for each row (may have duplicates for multi-embed).
        matrix : ndarray [N, D]
            L2-normalised rows.
        """
        self.entity_ids = entity_ids
        self.matrix = matrix  # [N, D], rows are L2-normalised

    def search_all(self, query: np.ndarray) -> List[Tuple[str, float]]:
        """Return [(entity_id, cosine_similarity)] for ALL rows, sorted descending."""
        if self.matrix is None or len(self.entity_ids) == 0:
            return []
        query = query.astype(np.float32).flatten()
        norm = np.linalg.norm(query)
        if norm > 0:
            query = query / norm
        sims = self.matrix @ query  # [N]
        idxs = np.argsort(sims)[::-1]
        return [(self.entity_ids[i], float(sims[i])) for i in idxs]


class _FaissIndex:
    """FAISS inner-product (cosine) index."""

    def __init__(self, entity_ids: List[str], matrix: np.ndarray):
        self.entity_ids = entity_ids
        dim = matrix.shape[1]
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(matrix)

    def search_all(self, query: np.ndarray) -> List[Tuple[str, float]]:
        if len(self.entity_ids) == 0:
            return []
        query = query.astype(np.float32).reshape(1, -1)
        norm = np.linalg.norm(query)
        if norm > 0:
            query = query / norm
        k = len(self.entity_ids)
        scores, idxs = self.index.search(query, k)
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0:
                continue
            results.append((self.entity_ids[idx], float(score)))
        return results


# ── Entity-level aggregation helpers ──────────────────────────────────

def _aggregate_max(entity_sims: Dict[str, List[float]]) -> Dict[str, float]:
    """score = max similarity."""
    return {eid: max(sims) for eid, sims in entity_sims.items()}


def _aggregate_centroid(
    entity_sims: Dict[str, List[float]],
    entity_centroids: Dict[str, np.ndarray],
    query: np.ndarray,
) -> Dict[str, float]:
    """score = cosine_sim(query, centroid)."""
    query = query.astype(np.float32).flatten()
    norm = np.linalg.norm(query)
    if norm > 0:
        query = query / norm
    scores: Dict[str, float] = {}
    for eid, centroid in entity_centroids.items():
        scores[eid] = float(np.dot(query, centroid))
    return scores


def _aggregate_topk_avg(entity_sims: Dict[str, List[float]], topk: int = 3) -> Dict[str, float]:
    """score = avg of top-K similarities."""
    scores: Dict[str, float] = {}
    for eid, sims in entity_sims.items():
        sorted_sims = sorted(sims, reverse=True)[:topk]
        scores[eid] = sum(sorted_sims) / max(len(sorted_sims), 1)
    return scores


class IdentityMatcher:
    """
    Maintains in-memory indices per modality for fast cosine lookup.
    Supports multiple embeddings per entity and configurable strategies.
    """

    def __init__(self, store: EntityStore, cfg: Optional[Dict] = None,
                 face_threshold: float = 0.50, pet_threshold: float = 0.30,
                 face_margin: float = 0.08, pet_margin: float = 0.05):
        self.store = store
        cfg = cfg or {}
        self.strategy = cfg.get("strategy", "topk_avg")
        self.topk = cfg.get("topk", 3)

        self.face_threshold = face_threshold
        self.pet_threshold = pet_threshold
        self.face_margin = face_margin
        self.pet_margin = pet_margin

        self._face_index = None   # _NumpyIndex | _FaissIndex
        self._pet_index = None
        # Per-entity centroids: {entity_id → centroid_vec}
        self._face_centroids: Dict[str, np.ndarray] = {}
        self._pet_centroids: Dict[str, np.ndarray] = {}

        self.reload_indices()

    # ── Rebuild ───────────────────────────────────────────────────────
    def reload_indices(self):
        """Rebuild all in-memory indices from the store."""
        self._face_index, self._face_centroids = self._build_index("face")
        self._pet_index, self._pet_centroids = self._build_index("pet_clip")
        face_n = len(set(self._face_index.entity_ids)) if self._face_index else 0
        pet_n = len(set(self._pet_index.entity_ids)) if self._pet_index else 0
        face_vecs = len(self._face_index.entity_ids) if self._face_index else 0
        pet_vecs = len(self._pet_index.entity_ids) if self._pet_index else 0
        logger.info(f"Indices rebuilt: face={face_n} entities/{face_vecs} vecs, "
                     f"pet={pet_n} entities/{pet_vecs} vecs")

    def _build_index(self, modality: str) -> Tuple[object, Dict[str, np.ndarray]]:
        ids, matrix = self.store.get_all_embeddings(modality)
        centroids: Dict[str, np.ndarray] = {}
        if matrix is None or len(ids) == 0:
            return _NumpyIndex([], np.empty((0, 0), dtype=np.float32)), centroids

        # Build per-entity centroids (for centroid strategy)
        entity_rows: Dict[str, List[np.ndarray]] = {}
        for eid, vec in zip(ids, matrix):
            entity_rows.setdefault(eid, []).append(vec)
        for eid, vecs in entity_rows.items():
            centroid = np.mean(vecs, axis=0).astype(np.float32)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm
            centroids[eid] = centroid

        if _HAS_FAISS and matrix.shape[0] >= 1:
            return _FaissIndex(ids, matrix), centroids
        return _NumpyIndex(ids, matrix), centroids

    # ── Match ─────────────────────────────────────────────────────────
    def match_face(self, embedding: np.ndarray, camera_id: Optional[str] = None) -> IdentityMatch:
        """Match a 512-d face embedding. Returns IdentityMatch."""
        return self._match(embedding, self._face_index, self._face_centroids,
                           self.face_threshold, self.face_margin,
                           camera_id=camera_id,
                           known_cat=EntityCategory.KNOWN_PERSON,
                           unknown_cat=EntityCategory.UNKNOWN_PERSON)

    def match_pet(self, embedding: np.ndarray, camera_id: Optional[str] = None) -> IdentityMatch:
        """Match a pet CLIP embedding. Returns IdentityMatch."""
        return self._match(embedding, self._pet_index, self._pet_centroids,
                           self.pet_threshold, self.pet_margin,
                           camera_id=camera_id,
                           known_cat=EntityCategory.PET,
                           unknown_cat=EntityCategory.UNKNOWN_ANIMAL)

    def _match(self, embedding: np.ndarray, index, centroids: Dict[str, np.ndarray],
               threshold: float, min_margin: float, camera_id: Optional[str],
               known_cat: str, unknown_cat: str) -> IdentityMatch:
        _unknown = IdentityMatch(
            entity_id=None, name=None, category=unknown_cat,
            confidence=0.0, score=0.0,
            best_sim=0.0, second_sim=0.0, margin=0.0,
        )

        if index is None or len(index.entity_ids) == 0:
            return _unknown

        # Get all raw similarities
        raw_results = index.search_all(embedding)
        if not raw_results:
            return _unknown

        # Group similarities by entity_id
        entity_sims: Dict[str, List[float]] = {}
        for eid, sim in raw_results:
            entity_sims.setdefault(eid, []).append(sim)

        # Aggregate per strategy
        if self.strategy == "centroid":
            entity_scores = _aggregate_centroid(entity_sims, centroids, embedding)
        elif self.strategy == "max":
            entity_scores = _aggregate_max(entity_sims)
        else:  # topk_avg (default)
            entity_scores = _aggregate_topk_avg(entity_sims, self.topk)

        # Sort by score descending
        sorted_entities = sorted(entity_scores.items(), key=lambda x: x[1], reverse=True)
        if camera_id:
            sorted_entities = [
                (eid, score) for eid, score in sorted_entities
                if self._is_camera_allowed(eid, camera_id)
            ]
        if not sorted_entities:
            return _unknown

        best_id, best_sim = sorted_entities[0]
        second_sim = sorted_entities[1][1] if len(sorted_entities) > 1 else 0.0
        margin = best_sim - second_sim

        # Check threshold + margin
        if best_sim >= threshold and margin >= min_margin:
            entity = self.store.get_entity(best_id)
            name = entity["name"] if entity else best_id
            return IdentityMatch(
                entity_id=best_id,
                name=name,
                category=known_cat,
                confidence=round(min(best_sim, 1.0), 4),
                score=round(best_sim, 4),
                best_sim=round(best_sim, 4),
                second_sim=round(second_sim, 4),
                margin=round(margin, 4),
            )

        return IdentityMatch(
            entity_id=None, name=None,
            category=unknown_cat,
            confidence=0.0,
            score=round(best_sim, 4),
            best_sim=round(best_sim, 4),
            second_sim=round(second_sim, 4),
            margin=round(margin, 4),
        )

    def _is_camera_allowed(self, entity_id: str, camera_id: str) -> bool:
        """Apply optional camera restriction from entity metadata."""
        entity = self.store.get_entity(entity_id)
        if not entity:
            return False
        metadata = entity.get("metadata") or {}
        allowed = metadata.get("allowed_camera_ids")
        if not isinstance(allowed, list) or len(allowed) == 0:
            return True
        allowed_str = {str(cam).strip() for cam in allowed if str(cam).strip()}
        return str(camera_id).strip() in allowed_str
