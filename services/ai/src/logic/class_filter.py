"""
Robust class-mapping utility for community YOLO models.

Community-trained models ship with arbitrary class-name orderings.
This module provides ``resolve_class_filter`` which maps user-configured
class names (or explicit IDs) to the actual integer class IDs reported
by a loaded Ultralytics model.

Usage:
    from src.logic.class_filter import resolve_class_filter

    model = YOLO("fire_yolov8.pt")
    allowed_ids, model_names = resolve_class_filter(
        model,
        class_names=["fire", "smoke"],
        class_ids=None,
        lane_name="fire_smoke",
        logger=my_logger,
    )
    # allowed_ids  → {0, 1}   (or whatever the model uses)
    # model_names  → {0: 'fire', 1: 'smoke', …}  (full mapping for diagnostics)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple


_CLASS_ALIASES: Dict[str, Set[str]] = {
    "gun": {"gun", "handgun", "pistol", "revolver", "rifle", "shotgun", "firearm"},
    "knife": {"knife", "dagger", "blade", "machete"},
    "weapon": {
        "weapon",
        "gun",
        "handgun",
        "pistol",
        "revolver",
        "rifle",
        "shotgun",
        "firearm",
        "knife",
        "dagger",
        "blade",
        "machete",
    },
}


def resolve_class_filter(
    model,
    class_names: Optional[List[str]] = None,
    class_ids: Optional[List[int]] = None,
    lane_name: str = "",
    logger: Optional[logging.Logger] = None,
) -> Tuple[Optional[Set[int]], Dict[int, str]]:
    """
    Build a deterministic set of allowed class IDs from an Ultralytics model.

    Priority:
      1. ``class_ids`` provided → use directly (bypass name matching).
      2. ``class_names`` provided → case-insensitive lookup against
         ``model.names`` (Ultralytics dict {int: str}).
      3. Neither provided → return ``None`` (= allow all classes).

    If name-matching fails for **every** requested name, the function
    logs the full ``model.names`` and returns ``(None, model_names)``
    so the caller can decide to disable the lane.

    Returns:
        (allowed_ids, model_names)
        - ``allowed_ids`` is ``None`` when no filter could be resolved
          (caller should disable the lane or allow all).
        - ``model_names`` is always the full mapping for diagnostics.
    """
    # Extract model.names (Ultralytics convention)
    model_names: Dict[int, str] = {}
    try:
        if hasattr(model, "names"):
            raw = model.names
            if isinstance(raw, dict):
                model_names = {int(k): str(v) for k, v in raw.items()}
            elif isinstance(raw, (list, tuple)):
                model_names = {i: str(v) for i, v in enumerate(raw)}
    except Exception:
        pass

    # 1. Explicit class_ids
    if class_ids is not None:
        ids = set(int(i) for i in class_ids)
        if logger:
            logger.info(
                f"[{lane_name}] Using explicit class_ids={ids}. "
                f"Model names: {model_names}"
            )
        return ids, model_names

    # 2. Name-based matching (case-insensitive)
    if class_names:
        # Build lowercase → id lookup
        lower_map: Dict[str, int] = {}
        for cid, cname in model_names.items():
            lower_map[cname.strip().lower()] = cid

        def _canonical_tokens(name: str) -> Set[str]:
            token = name.strip().lower().replace("-", " ").replace("_", " ")
            tokens = {token}
            for alias_key, alias_tokens in _CLASS_ALIASES.items():
                if token == alias_key or token in alias_tokens:
                    tokens.update(alias_tokens)
                    tokens.add(alias_key)
            return {t for t in tokens if t}

        def _matches(model_name: str, wanted_name: str) -> bool:
            model_norm = model_name.strip().lower().replace("-", " ").replace("_", " ")
            for candidate in _canonical_tokens(wanted_name):
                if candidate == model_norm:
                    return True
                if candidate in model_norm:
                    return True
                if model_norm in candidate:
                    return True
            return False

        matched: Set[int] = set()
        unmatched: List[str] = []
        for wanted in class_names:
            key = wanted.strip().lower()
            if key in lower_map:
                matched.add(lower_map[key])
            else:
                fuzzy = [cid for cid, cname in model_names.items() if _matches(cname, wanted)]
                if fuzzy:
                    matched.update(fuzzy)
                else:
                    unmatched.append(wanted)

        if matched:
            if unmatched and logger:
                logger.warning(
                    f"[{lane_name}] Partial class-name match: "
                    f"matched={[model_names[i] for i in matched]}, "
                    f"unmatched={unmatched}. "
                    f"Full model.names: {model_names}"
                )
            elif logger:
                logger.info(
                    f"[{lane_name}] Class filter resolved: "
                    f"ids={matched} names={[model_names[i] for i in matched]}"
                )
            return matched, model_names

        # Complete mismatch
        if logger:
            logger.error(
                f"[{lane_name}] Class mapping FAILED. None of "
                f"{class_names} found in model.names={model_names}. "
                f"Set models.{lane_name}.class_ids using the displayed "
                f"model.names mapping."
            )
        return None, model_names

    # 3. Nothing configured → no filter
    return None, model_names
