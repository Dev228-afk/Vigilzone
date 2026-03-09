"""
Identity-driven alert policy — severity/suppression rules.

Reads ``configs/policy.yaml`` and applies identity-aware logic:
  • Unknown person in restricted zone → HIGH
  • Known OWNER/FAMILY in restricted zone → LOW (or SUPPRESS)
  • Unknown person loitering → escalate to HIGH
  • Known pet → SUPPRESS pet alerts
  • Unknown animal at night → MED

``apply()`` returns a PolicyDecision that the aggregator uses to override
or suppress the default severity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set

from ..common.log import setup_logger
from .schema import EntityCategory, IdentityMatch

logger = setup_logger("IdentityPolicy")


@dataclass
class PolicyDecision:
    """Output of the policy engine for a single alert candidate."""
    severity: Optional[str]     # "SEVERE" / "HIGH" / "MED" / "LOW" / None → keep default
    suppress: bool              # True → do not emit alert
    reason: str                 # human-readable justification


class IdentityPolicy:
    """
    Config-driven identity policy engine.

    ``policy_cfg`` example::

        policy:
          time_rules:
            night_hours: [22, 6]
          intrusion:
            unknown_in_restricted: "HIGH"
            known_family_in_restricted: "LOW"
            suppress_known_roles: ["OWNER", "FAMILY"]
          animals:
            known_pet: "SUPPRESS"
            unknown_animal_night: "MED"
    """

    def __init__(self, policy_cfg: Dict[str, Any]):
        self.cfg = policy_cfg or {}
        tr = self.cfg.get("time_rules", {})
        nh = tr.get("night_hours", [22, 6])
        self._night_start = int(nh[0])
        self._night_end = int(nh[1])

        intr = self.cfg.get("intrusion", {})
        self._unknown_restricted_severity = intr.get("unknown_in_restricted", "HIGH")
        self._known_family_severity = intr.get("known_family_in_restricted", "LOW")
        self._suppress_roles: Set[str] = set(intr.get("suppress_known_roles", ["OWNER", "FAMILY"]))

        anim = self.cfg.get("animals", {})
        self._known_pet_action = anim.get("known_pet", "SUPPRESS")
        self._unknown_animal_night_sev = anim.get("unknown_animal_night", "MED")

    # ── Public API ────────────────────────────────────────────────────
    def apply(
        self,
        alert_type: str,
        identity: Optional[IdentityMatch],
        zone_name: Optional[str] = None,
        is_restricted_zone: bool = False,
    ) -> PolicyDecision:
        """
        Evaluate policy and return a PolicyDecision.

        Parameters
        ----------
        alert_type : str
            e.g. INTRUSION_PERSON_IN_ZONE, FIRE_SMOKE, …
        identity : IdentityMatch or None
            The identity result for the tracked entity.
        zone_name : str, optional
            Name of the zone the entity is in.
        is_restricted_zone : bool
            Whether the zone is marked as restricted.
        """
        if identity is None:
            return PolicyDecision(severity=None, suppress=False, reason="no_identity")

        cat = identity.category

        # ── Person rules ──────────────────────────────────────────────
        if cat == EntityCategory.KNOWN_PERSON:
            # §FIX: For intrusion alerts, suppress ALL known persons regardless
            # of role.  The user enrolled them, so they are authorized.
            if alert_type == "INTRUSION_PERSON_IN_ZONE":
                return PolicyDecision(
                    severity=None, suppress=True,
                    reason=f"known_person_suppressed_intrusion",
                )

            # Known person but not in restricted zone → no override
            return PolicyDecision(severity=None, suppress=False, reason="known_person_no_override")

        if cat == EntityCategory.UNKNOWN_PERSON:
            if alert_type == "INTRUSION_PERSON_IN_ZONE" and is_restricted_zone:
                return PolicyDecision(
                    severity=self._unknown_restricted_severity, suppress=False,
                    reason="unknown_person_in_restricted_zone",
                )
            return PolicyDecision(severity=None, suppress=False, reason="unknown_person")

        # ── Animal rules ──────────────────────────────────────────────
        if cat == EntityCategory.PET:
            if self._known_pet_action == "SUPPRESS":
                return PolicyDecision(severity=None, suppress=True, reason="known_pet_suppressed")
            return PolicyDecision(severity=None, suppress=False, reason="known_pet")

        if cat == EntityCategory.UNKNOWN_ANIMAL:
            if self._is_night_now():
                return PolicyDecision(
                    severity=self._unknown_animal_night_sev, suppress=False,
                    reason="unknown_animal_at_night",
                )
            return PolicyDecision(severity=None, suppress=False, reason="unknown_animal_day")

        return PolicyDecision(severity=None, suppress=False, reason="no_matching_rule")

    # ── Helpers ───────────────────────────────────────────────────────
    def _is_night_now(self) -> bool:
        """Check if current UTC hour is within configured night window."""
        hour = datetime.now(timezone.utc).hour
        if self._night_start > self._night_end:
            # e.g. 22..6 wraps midnight
            return hour >= self._night_start or hour < self._night_end
        return self._night_start <= hour < self._night_end

    @staticmethod
    def _get_entity_dict(identity: IdentityMatch) -> Dict[str, Any]:
        """Build a minimal entity dict from the IdentityMatch."""
        return {
            "entity_id": identity.entity_id,
            "name": identity.name,
            "category": identity.category,
            "role": "",  # Role is resolved by the aggregator from the store
        }
