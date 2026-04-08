"""
AI Integration views.

1. Proxy endpoints (JWT-protected)   → forward UI requests to AI service
2. Webhook receiver  (token-protected) → persist AI alerts into Django models
"""
import hashlib
import hmac
import logging
import os

from django.db import models
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from api.models import Camera
from api.views import (
    _ensure_mediamtx_path,
    _get_canonical_camera_id,
    _get_mediamtx_loopback_url,
    assert_member,
    assert_non_viewer,
    get_active_tenant,
)
from .proxy import proxy_request

logger = logging.getLogger(__name__)


def _resolve_control_camera(request, raw_camera_id):
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        return None, tenant, Response(
            {"error": "Not a member of this tenant."},
            status=status.HTTP_403_FORBIDDEN,
        )

    camera = None
    camera_token = str(raw_camera_id or "").strip()
    if not camera_token:
        return None, tenant, Response(
            {"error": "camera_id is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if camera_token.isdigit():
        camera = Camera.objects.filter(pk=int(camera_token), tenant=tenant).first()

    if camera is None:
        camera = Camera.objects.filter(
            tenant=tenant,
        ).filter(
            models.Q(ai_camera_id=camera_token) | models.Q(stream_path=camera_token)
        ).first()

    if camera is None:
        return None, tenant, Response(
            {"error": "Camera not found for tenant"},
            status=status.HTTP_404_NOT_FOUND,
        )

    return camera, tenant, None


def _set_camera_runtime(camera: Camera, enabled: bool) -> dict:
    import requests as http_client

    ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080").rstrip("/")
    stream_id = camera.ai_camera_id or _get_canonical_camera_id(camera)

    if enabled:
        provisioned_stream_id, _, _ = _ensure_mediamtx_path(camera)
        stream_id = provisioned_stream_id
        register_payload = {
            "camera_id": stream_id,
            "rtsp_url": _get_mediamtx_loopback_url(stream_id),
            "ingest_backend": "opencv",
            "enabled_lanes": ["rt_detr", "yolov8_fallback", "fire_smoke_yolo", "person_zone"],
            "sample_hz": 2.0,
        }
        register_resp = http_client.post(
            f"{ai_base}/api/v1/cameras/register",
            json=register_payload,
            timeout=15,
        )
        if register_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"AI register failed: {register_resp.status_code} {register_resp.text[:200]}"
            )

    runtime_resp = http_client.post(
        f"{ai_base}/api/v1/cameras/{stream_id}/runtime-control",
        json=bool(enabled),
        timeout=10,
    )
    if runtime_resp.status_code >= 400:
        raise RuntimeError(
            f"AI runtime-control failed: {runtime_resp.status_code} {runtime_resp.text[:200]}"
        )

    runtime_status = {"running": enabled}
    try:
        status_resp = http_client.get(
            f"{ai_base}/api/v1/cameras/{stream_id}/runtime-status",
            timeout=5,
        )
        if status_resp.ok:
            runtime_status = status_resp.json() or runtime_status
    except Exception:
        pass

    camera.ai_camera_id = stream_id
    if not camera.stream_path:
        camera.stream_path = stream_id
    camera.status = Camera.Status.ACTIVE if runtime_status.get("running") else Camera.Status.INACTIVE
    camera.save(update_fields=["ai_camera_id", "stream_path", "status", "updated_at"])

    return {
        "camera_db_id": camera.id,
        "camera_id": camera.ai_camera_id,
        "name": camera.name,
        "stream_path": camera.stream_path,
        "loopback_rtsp_url": _get_mediamtx_loopback_url(camera.ai_camera_id or camera.stream_path),
        "running": bool(runtime_status.get("running")),
        "runtime": runtime_status,
    }

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
    camera_id = (camera_id or "").strip()
    if not camera_id:
        return Response({"error": "camera_id is required"}, status=status.HTTP_400_BAD_REQUEST)

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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_start(request):
    """POST /api/ai/start/ → authorize tenant camera and start AI runtime."""
    camera, tenant, error_response = _resolve_control_camera(
        request,
        request.data.get("camera_id"),
    )
    if error_response is not None:
        return error_response

    assert_non_viewer(request, tenant)

    try:
        payload = _set_camera_runtime(camera, enabled=True)
    except Exception as exc:
        logger.warning("Failed to start AI runtime for camera %s: %s", camera.id, exc)
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    payload["status"] = "started"
    return Response(payload, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_stop(request):
    """POST /api/ai/stop/ → authorize tenant camera and stop AI runtime."""
    camera, tenant, error_response = _resolve_control_camera(
        request,
        request.data.get("camera_id"),
    )
    if error_response is not None:
        return error_response

    assert_non_viewer(request, tenant)

    try:
        payload = _set_camera_runtime(camera, enabled=False)
    except Exception as exc:
        logger.warning("Failed to stop AI runtime for camera %s: %s", camera.id, exc)
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    payload["status"] = "stopped"
    return Response(payload, status=status.HTTP_200_OK)


# ── Entity endpoints ──────────────────────────────────────────


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def ai_entities(request):
    """
    GET  /api/ai/entities/        → list entities from AI
    POST /api/ai/entities/        → enroll entity (multipart images)
    """
    return proxy_request(request, "/entities")


@api_view(["PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def ai_entity_detail(request, entity_id):
    """
    PUT    /api/ai/entities/<entity_id>/ → update AI entity metadata.
    DELETE /api/ai/entities/<entity_id>/ → remove entity.
    """
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
#    All ingestion logic is in ai_integration.incident_ingest
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@api_view(["POST"])
@permission_classes([AllowAny])
def ai_webhook_receive(request):
    """
    POST /api/ai/webhook/receive/

    Called by the AI service when an alert is created.
    Protected by X-AI-WEBHOOK-TOKEN header (shared secret).

    Now delegates to the shared ingest function for consistent processing
    with the Redis subscriber path.
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

    # Extract stable event ID for idempotency
    event_id = str(data.get("id", "")).strip() or None

    # Delegate to shared ingest function
    from .incident_ingest import process_alert_event

    result = process_alert_event(
        data=data,
        source="webhook",
        event_id=event_id,
    )

    if result.status == "error":
        http_status = status.HTTP_400_BAD_REQUEST
        if "Ambiguous" in (result.error or ""):
            http_status = status.HTTP_409_CONFLICT
        return Response(
            {"error": result.error, "status": result.status},
            status=http_status,
        )

    if result.status == "duplicate":
        return Response(
            {"status": "duplicate", "incident_id": result.incident_id},
            status=status.HTTP_200_OK,
        )

    return Response(
        {
            "status": result.status,
            "incident_id": result.incident_id,
        },
        status=status.HTTP_201_CREATED if result.status == "created" else status.HTTP_200_OK,
    )
