"""
AI Integration views.

1. Proxy endpoints (JWT-protected)   → forward UI requests to AI service
2. Webhook receiver  (token-protected) → persist AI alerts into Django models
"""
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from api.models import Camera, Detection, Incident, Tenant

from .proxy import proxy_request

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. PROXY ENDPOINTS  (JWT-protected, for the UI)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_cameras(request):
    """GET /api/ai/cameras/ → proxy to AI cameras list."""
    # Try v1 API first, fall back to legacy
    resp = proxy_request(request, "/api/v1/cameras")
    if resp.status_code == 404:
        resp = proxy_request(request, "/cameras")
    return resp


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_alerts(request):
    """GET /api/ai/alerts/ → proxy to AI alerts list."""
    resp = proxy_request(request, "/api/v1/alerts")
    if resp.status_code == 404:
        resp = proxy_request(request, "/alerts")
    return resp


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_frame(request, camera_id):
    """GET /api/ai/frame/<camera_id>/ → proxy AI snapshot (binary stream)."""
    resp = proxy_request(request, f"/frame/{camera_id}", stream=True)
    if resp.status_code == 404:
        resp = proxy_request(
            request, f"/api/v1/cameras/{camera_id}/snapshot", stream=True
        )
    return resp


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_system_status(request):
    """GET /api/ai/system/status/ → proxy to AI system status."""
    return proxy_request(request, "/api/v1/system/status")


# ── Entity endpoints ──────────────────────────────────────────


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def ai_entities(request):
    """
    GET  /api/ai/entities/        → list entities from AI
    POST /api/ai/entities/        → enroll entity (multipart images)
    """
    return proxy_request(request, "/entities")


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def ai_entity_detail(request, entity_id):
    """DELETE /api/ai/entities/<entity_id>/ → remove entity."""
    return proxy_request(request, f"/entities/{entity_id}")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_entity_images(request, entity_id):
    """GET /api/ai/entities/<entity_id>/images/ → list enrollment images."""
    return proxy_request(request, f"/entities/{entity_id}/images")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_entity_enroll_person(request):
    """POST /api/ai/entities/enroll_person/ → enroll person (multipart)."""
    return proxy_request(request, "/entities/enroll_person")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_entity_enroll_pet(request):
    """POST /api/ai/entities/enroll_pet/ → enroll pet (multipart)."""
    return proxy_request(request, "/entities/enroll_pet")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_entity_enroll_person_upload(request):
    """POST /api/ai/entities/enroll_person_from_upload/ → enroll from staged images."""
    return proxy_request(request, "/entities/enroll_person_from_upload")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_entity_enroll_pet_upload(request):
    """POST /api/ai/entities/enroll_pet_from_upload/ → enroll from staged images."""
    return proxy_request(request, "/entities/enroll_pet_from_upload")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_upload_enroll_images(request):
    """POST /api/ai/uploads/enroll_images/ → stage images for preview."""
    return proxy_request(request, "/uploads/enroll_images")


# ── Webhook registration ─────────────────────────────────────


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_webhooks_register(request):
    """POST /api/ai/webhooks/register/ → register webhook in AI service."""
    return proxy_request(request, "/webhooks")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_webhooks_list(request):
    """GET /api/ai/webhooks/ → list registered webhooks."""
    return proxy_request(request, "/webhooks")


# ── Evidence / static files proxy ─────────────────────────────


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_evidence(request, camera_id, filename):
    """GET /api/ai/evidence/<camera_id>/<filename> → stream evidence file."""
    return proxy_request(request, f"/evidence/{camera_id}/{filename}", stream=True)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_enroll_image(request, entity_id, filename):
    """GET /api/ai/enroll_images/<entity_id>/<filename> → stream enrollment image."""
    return proxy_request(
        request, f"/enroll_images/{entity_id}/{filename}", stream=True
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. WEBHOOK RECEIVER  (called by AI service, token-protected)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INCIDENT_TYPE_MAP = {
    "fire":             Incident.Type.FIRE,
    "weapon":           Incident.Type.ROBBERY,
    "intrusion":        Incident.Type.INTRUSION,
    "stranger":         Incident.Type.STRANGER,
    "loitering":        Incident.Type.INTRUSION,
    "abandoned_object": Incident.Type.OTHER,
    "crowd":            Incident.Type.OTHER,
    "fall":             Incident.Type.OTHER,
    "animal":           Incident.Type.OTHER,
    "anomaly":          Incident.Type.OTHER,
}

SEVERITY_MAP = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}

# Active-window: if last alert for same (camera, type) was within this many
# seconds, update the existing incident instead of creating a new one.
INCIDENT_ACTIVE_WINDOW_SECONDS = 60


def _resolve_camera(camera_id_str: str):
    """Find Camera by ai_camera_id → name → None."""
    cam = Camera.objects.filter(ai_camera_id=camera_id_str).first()
    if cam:
        return cam, cam.tenant
    cam = Camera.objects.filter(name=camera_id_str).first()
    if cam:
        return cam, cam.tenant
    return None, None


def _parse_severity(raw) -> int:
    if isinstance(raw, int):
        return max(1, min(5, raw))
    if isinstance(raw, str):
        return SEVERITY_MAP.get(raw.lower(), 3)
    return 3


def _parse_timestamp(raw) -> datetime:
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            return dt
        except (ValueError, TypeError):
            pass
    return timezone.now()


@api_view(["POST"])
@permission_classes([AllowAny])
def ai_webhook_receive(request):
    """
    POST /api/ai/webhook/receive/

    Called by the AI service when an alert is created.
    Protected by X-AI-WEBHOOK-TOKEN header (shared secret).

    Payload:
    {
      "event": "alert.created",
      "data": {
        "id": "...",
        "camera_id": "cam_01",
        "type": "fire",
        "severity": "high" | 4,
        "timestamp": "2025-01-01T12:00:00Z",
        "message": "Fire detected",
        "confidence": 0.92,
        "evidence": { "keyframe": "evidence/cam_01/...", "clip": "..." }
      }
    }
    """
    # ── Auth: accept X-AI-WEBHOOK-TOKEN  **or**  X-Vigilzone-Signature ─
    expected_token = os.getenv("AI_WEBHOOK_TOKEN", "")
    webhook_secret = os.getenv("AI_WEBHOOK_SECRET", "")
    authenticated = False

    # Method 1: flat shared token
    if expected_token:
        received_token = request.headers.get("X-AI-WEBHOOK-TOKEN", "")
        if received_token == expected_token:
            authenticated = True

    # Method 2: HMAC-SHA256 signature (used by AI _dispatch_webhooks)
    if not authenticated and webhook_secret:
        sig_header = request.headers.get("X-Vigilzone-Signature", "")
        if sig_header.startswith("sha256="):
            received_sig = sig_header[7:]
            body_bytes = request.body if hasattr(request, "body") else b""
            if isinstance(body_bytes, memoryview):
                body_bytes = bytes(body_bytes)
            expected_sig = hmac.new(
                webhook_secret.encode(), body_bytes, hashlib.sha256
            ).hexdigest()
            if hmac.compare_digest(received_sig, expected_sig):
                authenticated = True

    # If neither secret is configured, allow (dev mode)
    if not authenticated and (expected_token or webhook_secret):
        return Response(
            {"error": "Unauthorized — invalid or missing webhook credentials"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    payload = request.data
    event = payload.get("event", "")
    data = payload.get("data", {})

    if event != "alert.created":
        logger.info("Ignoring webhook event: %s", event)
        return Response({"status": "ignored", "event": event})

    camera_id_str = data.get("camera_id", "")
    alert_type = data.get("type", "other")
    severity_raw = data.get("severity", 3)
    timestamp_raw = data.get("timestamp")
    message = data.get("message", "")
    confidence = data.get("confidence")

    # ── Resolve / auto-create camera ──────────────────────────
    camera, tenant = _resolve_camera(camera_id_str)
    if not camera:
        # Prefer tenant that has the most cameras (likely the active tenant)
        from django.db.models import Count
        tenant = (
            Tenant.objects.annotate(cam_count=Count("camera"))
            .order_by("-cam_count")
            .first()
        )
        if not tenant:
            tenant = Tenant.objects.first()
        if not tenant:
            return Response(
                {"error": "No tenant configured"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        camera = Camera.objects.create(
            tenant=tenant,
            name=camera_id_str,
            ai_camera_id=camera_id_str,
            status=Camera.Status.ACTIVE,
        )
        logger.info("Auto-created camera '%s' for tenant '%s'", camera_id_str, tenant.name)

    incident_type = INCIDENT_TYPE_MAP.get(alert_type, Incident.Type.OTHER)
    severity = _parse_severity(severity_raw)
    alert_ts = _parse_timestamp(timestamp_raw)

    # Evidence URL (routed through Django proxy)
    # Accept both naming conventions: keyframe/keyframe_path, clip/clip_path
    evidence = data.get("evidence", {})
    keyframe = evidence.get("keyframe_path") or evidence.get("keyframe", "")
    clip = evidence.get("clip_path") or evidence.get("clip", "")
    media_key = f"/api/ai/evidence/{keyframe}" if keyframe else ""
    clip_url = f"/api/ai/evidence/{clip}" if clip else ""

    with transaction.atomic():
        # ── Active-window: reuse or create incident ───────────
        cutoff = alert_ts - timedelta(seconds=INCIDENT_ACTIVE_WINDOW_SECONDS)
        existing = (
            Incident.objects.filter(
                camera=camera,
                type=incident_type,
                status=Incident.Status.OPEN,
                started_at__gte=cutoff,
            )
            .order_by("-started_at")
            .first()
        )

        if existing:
            # Update the existing active incident
            existing.severity = max(existing.severity, severity)
            existing.details = {
                **(existing.details or {}),
                "last_alert_id": data.get("id", ""),
                "last_message": message,
                "alert_count": (existing.details or {}).get("alert_count", 1) + 1,
            }
            if clip_url:
                existing.details["clip_url"] = clip_url
            if media_key:
                existing.media_key = media_key
            existing.save(update_fields=["severity", "details", "media_key", "updated_at"])
            incident = existing
            created = False
        else:
            details_dict = {
                "ai_alert_id": data.get("id", ""),
                "message": message,
                "alert_type": alert_type,
                "confidence": confidence,
                "alert_count": 1,
            }
            if clip_url:
                details_dict["clip_url"] = clip_url
            incident = Incident.objects.create(
                tenant=tenant,
                camera=camera,
                type=incident_type,
                status=Incident.Status.OPEN,
                severity=severity,
                started_at=alert_ts,
                details=details_dict,
                media_key=media_key,
            )
            created = True

        # Always store raw detection
        Detection.objects.create(
            tenant=tenant,
            camera=camera,
            ts=alert_ts,
            payload=data,
        )

    logger.info(
        "AI webhook: %s incident #%s (%s, sev=%d) for camera '%s'",
        "created" if created else "updated",
        incident.pk,
        incident_type,
        severity,
        camera_id_str,
    )

    # §4 — dispatch email/push notifications
    try:
        from api.views import dispatch_notifications
        dispatch_notifications(incident)
    except Exception as exc:
        logger.warning("Notification dispatch error: %s", exc)

    return Response(
        {
            "status": "created" if created else "updated",
            "incident_id": incident.pk,
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )
