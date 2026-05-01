"""
Shared helpers for realtime browser notification transports (SSE and legacy WebSocket).
This ensures auth, grouping, and per-user filtering remain consistent across transports.
"""

import json
import logging
from typing import Optional, Dict, Any
from asgiref.sync import sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

logger = logging.getLogger(__name__)

# Cache models to avoid import cycles if used at module level
def _get_models():
    from django.contrib.auth import get_user_model
    from .models import Membership
    return get_user_model(), Membership

@sync_to_async
def authenticate_user_from_bearer(token: Optional[str]):
    """Authenticate user from a raw JWT token string."""
    if not token or token == "null":
        return None

    try:
        access_token = AccessToken(token)
        user_id = access_token.get("user_id")
        if not user_id:
            return None

        User, _ = _get_models()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    except (TokenError, InvalidToken) as e:
        logger.warning(f"SSE JWT validation failed: {e}")
        return None
    except Exception as e:
        logger.error(f"SSE Authentication unexpected error: {e}")
        return None

def parse_tenant_id(value: Optional[str]) -> Optional[int]:
    """Safely parse tenant ID from a string."""
    if not value:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

@sync_to_async
def verify_tenant_membership(user, tenant_id: int) -> bool:
    """Verify user is a member of the specified tenant."""
    if not user or not tenant_id:
        return False
    
    _, Membership = _get_models()
    return Membership.objects.filter(
        user=user,
        tenant_id=tenant_id
    ).exists()

def build_group_name(tenant_id: int) -> str:
    """Canonical name for a tenant's channel-layer group."""
    return f"tenant_notifications_{tenant_id}"

def filter_notification_for_user(event_data: Dict[str, Any], user_id: int) -> Optional[Dict[str, Any]]:
    """
    Given a raw group broadcast payload, filter/mutate it for a specific user.
    Returns the mutated payload, or None if the message should be dropped for this user.
    """
    # Don't mutate the original dictionary shared across connections
    data = dict(event_data)
    per_user_ids = data.pop("alert_ids_by_user", None)
    per_user_counts = data.pop("unread_counts_by_user", None)
    
    if isinstance(per_user_ids, dict):
        user_id_str = str(user_id)
        
        # Extract alert_id for this specific user
        alert_id = per_user_ids.get(user_id_str)
        if not alert_id:
            logger.debug(f"User {user_id_str} not in alert targets. Dropping broadcast message.")
            return None
            
        data["alert_id"] = alert_id

        # Extract unread_count for this specific user if available
        if isinstance(per_user_counts, dict):
            data["unread_count"] = per_user_counts.get(user_id_str)
            
    return data

def encode_sse(event_name: str, data: Dict[str, Any], event_id: Optional[str] = None) -> bytes:
    """
    Format a data dictionary into an SSE compliant byte string.
    """
    payload = []
    if event_id:
        payload.append(f"id: {event_id}")
    if event_name:
        payload.append(f"event: {event_name}")
    
    json_data = json.dumps(data)
    payload.append(f"data: {json_data}")
    payload.append("")
    payload.append("") # two blank lines to terminate
    
    return ("\n".join(payload)).encode("utf-8")
