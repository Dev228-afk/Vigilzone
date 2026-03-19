"""
Entity storage — SQLite metadata + on-disk embeddings.

Tables
------
  entities   (entity_id PK, name, category, role, metadata_json, created_at)
  embeddings (entity_id, modality, dim, path, created_at)

Embedding vectors live as .npz files under  data/embeddings/<entity_id>/
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..common.log import setup_logger
from .schema import EntityRecord

_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DB_PATH = _DB_DIR / "entities.db"
_EMBED_DIR = _DB_DIR / "embeddings"
_ENROLL_IMG_DIR = _DB_DIR / "enroll_images"

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'VISITOR',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    entity_id  TEXT NOT NULL,
    modality   TEXT NOT NULL,          -- face | pet_clip
    dim        INTEGER NOT NULL,
    path       TEXT NOT NULL,          -- relative to _EMBED_DIR
    created_at TEXT NOT NULL,
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
);
"""


class EntityStore:
    """Thin SQLite + npz storage for enrolled entities."""

    def __init__(self, db_path: Optional[Path] = None, embed_dir: Optional[Path] = None):
        self.db_path = db_path or _DB_PATH
        self.embed_dir = embed_dir or _EMBED_DIR
        self.enroll_img_dir = _ENROLL_IMG_DIR
        self.logger = setup_logger("EntityStore")

        # Ensure directories
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embed_dir.mkdir(parents=True, exist_ok=True)
        self.enroll_img_dir.mkdir(parents=True, exist_ok=True)

        self._init_db()

    # ── DB helpers ────────────────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(_CREATE_TABLES)
        self.logger.info(f"Entity store ready ({self.db_path})")

    # ── Public API ────────────────────────────────────────────────────
    def add_entity(
        self,
        record: EntityRecord,
        embeddings: Optional[Dict[str, np.ndarray]] = None,
    ) -> str:
        """
        Insert entity + optional embedding vectors.
        ``embeddings`` maps modality (``"face"`` / ``"pet_clip"``) → np.ndarray.
        Returns entity_id.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entities (entity_id, name, category, role, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.entity_id,
                    record.name,
                    record.category,
                    record.role,
                    json.dumps(record.metadata),
                    now,
                ),
            )
            if embeddings:
                for modality, vec in embeddings.items():
                    self._save_embedding(conn, record.entity_id, modality, vec, now)
        self.logger.info(f"Enrolled entity {record.entity_id} ({record.name}, {record.category})")
        return record.entity_id

    def add_embedding(self, entity_id: str, modality: str, vec: np.ndarray):
        """Add a single embedding vector to an existing entity."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            self._save_embedding(conn, entity_id, modality, vec, now)
        self.logger.debug(f"Added {modality} embedding to {entity_id}")

    def remove_entity(self, entity_id: str) -> bool:
        """Delete entity + its embeddings (files + DB rows)."""
        edir = self.embed_dir / entity_id
        if edir.exists():
            import shutil
            shutil.rmtree(edir, ignore_errors=True)
        with self._conn() as conn:
            conn.execute("DELETE FROM embeddings WHERE entity_id = ?", (entity_id,))
            cursor = conn.execute("DELETE FROM entities WHERE entity_id = ?", (entity_id,))
        removed = cursor.rowcount > 0
        if removed:
            self.logger.info(f"Removed entity {entity_id}")
        return removed

    def list_entities(self, category: Optional[str] = None) -> List[Dict]:
        """Return entities (optionally filtered by category)."""
        with self._conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM entities WHERE category = ? ORDER BY created_at DESC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM entities ORDER BY created_at DESC").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_entity(self, entity_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def update_entity(
        self,
        entity_id: str,
        *,
        name: Optional[str] = None,
        role: Optional[str] = None,
        category: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Update mutable entity fields and merge metadata."""
        entity = self.get_entity(entity_id)
        if not entity:
            return None

        next_name = name if isinstance(name, str) and name.strip() else entity.get("name")
        next_role = role if isinstance(role, str) and role.strip() else entity.get("role")
        next_category = category if isinstance(category, str) and category.strip() else entity.get("category")
        next_meta = dict(entity.get("metadata") or {})
        if isinstance(metadata, dict):
            next_meta.update(metadata)

        with self._conn() as conn:
            conn.execute(
                "UPDATE entities SET name = ?, role = ?, category = ?, metadata_json = ? WHERE entity_id = ?",
                (
                    str(next_name),
                    str(next_role),
                    str(next_category),
                    json.dumps(next_meta),
                    entity_id,
                ),
            )
        return self.get_entity(entity_id)

    def record_sighting(self, entity_id: str, camera_id: str):
        """Persist last_seen and last_camera_id in metadata for matched entities."""
        now_iso = datetime.now(timezone.utc).isoformat()
        entity = self.get_entity(entity_id)
        if not entity:
            return
        metadata = dict(entity.get("metadata") or {})
        metadata["last_seen"] = now_iso
        metadata["last_camera_id"] = str(camera_id)
        with self._conn() as conn:
            conn.execute(
                "UPDATE entities SET metadata_json = ? WHERE entity_id = ?",
                (json.dumps(metadata), entity_id),
            )

    def get_all_embeddings(self, modality: str) -> Tuple[List[str], Optional[np.ndarray]]:
        """
        Return ``(entity_ids, matrix_float32)`` for a given modality.
        Matrix shape: ``[N, dim]``.  Returns ``([], None)`` if empty.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT entity_id, dim, path FROM embeddings WHERE modality = ? ORDER BY entity_id",
                (modality,),
            ).fetchall()

        if not rows:
            return [], None

        ids: List[str] = []
        vectors: List[np.ndarray] = []
        for r in rows:
            fpath = self.embed_dir / r["path"]
            if not fpath.exists():
                self.logger.warning(f"Embedding file missing: {fpath}")
                continue
            data = np.load(str(fpath))
            vec = data["vec"]  # 1-D float32
            ids.append(r["entity_id"])
            vectors.append(vec)

        if not vectors:
            return [], None

        matrix = np.stack(vectors).astype(np.float32)
        return ids, matrix

    # ── Internal ──────────────────────────────────────────────────────
    def _save_embedding(
        self, conn: sqlite3.Connection,
        entity_id: str, modality: str, vec: np.ndarray, created_at: str,
    ):
        vec = vec.astype(np.float32).flatten()
        edir = self.embed_dir / entity_id
        edir.mkdir(parents=True, exist_ok=True)
        fname = f"{modality}_{uuid.uuid4().hex[:8]}.npz"
        rel_path = f"{entity_id}/{fname}"
        np.savez_compressed(str(edir / fname), vec=vec)
        conn.execute(
            "INSERT INTO embeddings (entity_id, modality, dim, path, created_at) VALUES (?, ?, ?, ?, ?)",
            (entity_id, modality, len(vec), rel_path, created_at),
        )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict:
        d = dict(row)
        if "metadata_json" in d:
            try:
                d["metadata"] = json.loads(d.pop("metadata_json"))
            except Exception:
                d["metadata"] = {}
        return d

    @staticmethod
    def generate_id() -> str:
        return f"ent_{uuid.uuid4().hex[:12]}"
