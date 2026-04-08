import os
import logging
import hashlib
import hmac
import time
import socket
from urllib.parse import urlparse
from typing import List
from rest_framework import viewsets, permissions, status
from rest_framework.exceptions import PermissionDenied, NotAuthenticated
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Q, TextField
from django.db.models.functions import Cast
from django.conf import settings
from django.utils import timezone
from ai_integration.redis_queue import (
    append_incident_event,
    build_test_incident_event,
    create_redis_client,
    read_subscriber_status,
    stream_length,
)
from server.redis_runtime import resolve_backend_redis_settings
from .models import (
    Tenant, Membership, Camera, CameraZone, Incident, Detection,
    Alert, AuditLog, Profile, Invitation, KnownEntity, NotificationChannel,
    TenantRuntimeSetting, normalize_instant_notification_levels, severity_level_for_value,
)
from .stream_workers import STREAM_WORKERS
from .serializers import (
    TenantSerializer, MyTenantSerializer, MembershipSerializer,
    CameraSafeSerializer, CameraAdminSerializer, CameraWriteSerializer,
    CameraStreamSerializer,
    IncidentSerializer, DetectionSerializer, AlertSerializer, AuditLogSerializer,
    ProfileSerializer, InvitationCreateSerializer, PendingInvitationSerializer,
    KnownEntitySerializer, CameraZoneSerializer, NotificationChannelSerializer,
)
from .notification_service import NotificationService

class IsAuthenticatedOrReadOnly(permissions.IsAuthenticatedOrReadOnly):
    pass

def get_active_tenant(request, required=True):
    tid = (
        getattr(request, "tenant_id", None)
        or request.headers.get("X-Tenant-ID")
        or request.headers.get("x-tenant-id")
        or request.META.get("HTTP_X_TENANT_ID")
    )
    if not tid:
        if required:
            raise PermissionDenied("Missing X-Tenant-ID header.")
        return None
    try:
        return Tenant.objects.get(pk=tid)
    except Tenant.DoesNotExist:
        if required:
            raise PermissionDenied("Invalid tenant ID.")
        return None

def assert_member(request, tenant):
    if not request.user or not request.user.is_authenticated:
        raise NotAuthenticated()
    return Membership.objects.filter(user=request.user, tenant=tenant).exists()


def get_membership(request, tenant):
    if not request.user or not request.user.is_authenticated:
        raise NotAuthenticated()
    return Membership.objects.filter(user=request.user, tenant=tenant).first()


def assert_non_viewer(request, tenant):
    membership = get_membership(request, tenant)
    if not membership:
        raise PermissionDenied("Not a member of this tenant.")
    if membership.role == Membership.Role.VIEWER:
        raise PermissionDenied("Viewer role is read-only.")
    return membership

class TenantScopedViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet that filters by tenant={X-Tenant-ID} and sets tenant on create.
    """
    tenant_field = "tenant"   # override if different

    def get_queryset(self):
        tenant = get_active_tenant(self.request)
        if not assert_member(self.request, tenant):
            raise PermissionDenied("Not a member of this tenant.")
        return super().get_queryset().filter(**{self.tenant_field: tenant})

    def perform_create(self, serializer):
        tenant = get_active_tenant(self.request)
        assert_non_viewer(self.request, tenant)
        serializer.save(**{self.tenant_field: tenant})

    def perform_update(self, serializer):
        tenant = get_active_tenant(self.request)
        assert_non_viewer(self.request, tenant)
        serializer.save()

    def perform_destroy(self, instance):
        tenant = get_active_tenant(self.request)
        assert_non_viewer(self.request, tenant)
        instance.delete()

class TenantViewSet(viewsets.ModelViewSet):
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Tenant.objects.all()
        # return only tenants where the user has a membership
        return Tenant.objects.filter(memberships__user=user).distinct()
    
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @transaction.atomic
    def perform_create(self, serializer):
        # no X-Tenant-ID usage here; this is global creation
        tenant = serializer.save()  # creates Tenant(name, plan)
        Membership.objects.get_or_create(
            user=self.request.user,
            tenant=tenant,
            defaults={"role": "owner"},
        )


    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request):
        qs = (
            Membership.objects
            .select_related("tenant")
            .filter(user=request.user)
            .order_by("tenant__name")
        )
        return Response(MyTenantSerializer(qs, many=True).data)

class MembershipViewSet(TenantScopedViewSet):
    queryset = Membership.objects.select_related("user", "tenant").all()
    serializer_class = MembershipSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        tenant = get_active_tenant(self.request)
        assert_role_in(self.request, tenant, allowed_roles={"owner", "admin"})
        serializer.save(tenant=tenant)

    def perform_update(self, serializer):
        tenant = get_active_tenant(self.request)
        assert_role_in(self.request, tenant, allowed_roles={"owner", "admin"})
        serializer.save()

    def perform_destroy(self, instance):
        tenant = get_active_tenant(self.request)
        assert_role_in(self.request, tenant, allowed_roles={"owner", "admin"})
        instance.delete()


# ── RTSP probe helper (used by test_connection endpoints) ────
def _probe_rtsp(rtsp_url: str, timeout_s: int = 3) -> dict:
    """
    Probe an RTSP URL with ffprobe (fast), falling back to ffmpeg single-frame grab.
    Returns { ok, method, latency_ms, details?, error? }.
    """
    import subprocess
    import time as _time
    import json as _json
    import shutil

    result: dict = {"ok": False, "method": "none", "latency_ms": 0}

    # ── Try ffprobe first ─────────────────────────────────────
    if shutil.which("ffprobe"):
        t0 = _time.monotonic()
        try:
            proc = subprocess.Popen(
                [
                    "ffprobe", "-v", "error",
                    "-rtsp_transport", "tcp",
                    "-rw_timeout", str(timeout_s * 1_000_000),
                    "-show_streams", "-select_streams", "v:0",
                    "-print_format", "json",
                    rtsp_url,
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            proc.wait(timeout=timeout_s + 2)
            stdout = proc.stdout.read(51200)  # Bound read to 50KB to prevent OOM
            stderr = proc.stderr.read(51200)
            
            latency = int((_time.monotonic() - t0) * 1000)
            if proc.returncode == 0 and stdout:
                try:
                    info = _json.loads(stdout)
                    streams = info.get("streams", [])
                    if streams:
                        s = streams[0]
                        return {
                            "ok": True,
                            "method": "ffprobe",
                            "latency_ms": latency,
                            "details": {
                                "codec": s.get("codec_name"),
                                "width": s.get("width"),
                                "height": s.get("height"),
                                "fps": s.get("r_frame_rate"),
                            },
                        }
                except _json.JSONDecodeError:
                    pass
            result["error"] = stderr.decode(errors="replace").strip()[:300]
        except subprocess.TimeoutExpired:
            proc.kill()
            result["error"] = f"ffprobe timed out ({timeout_s}s)"
            result["latency_ms"] = timeout_s * 1000
            return result
        except FileNotFoundError:
            pass  # fall through to ffmpeg

    # ── Fallback: ffmpeg single-frame grab ────────────────────
    t0 = _time.monotonic()
    try:
        proc = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-rtsp_transport", "tcp",
                "-rw_timeout", str(timeout_s * 1_000_000),
                "-i", rtsp_url,
                "-frames:v", "1",
                "-f", "null", "-",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        proc.wait(timeout=timeout_s + 2)
        stdout = proc.stdout.read(51200)
        stderr = proc.stderr.read(51200)
        
        latency = int((_time.monotonic() - t0) * 1000)
        if proc.returncode == 0:
            return {"ok": True, "method": "ffmpeg", "latency_ms": latency}
        result["method"] = "ffmpeg"
        result["latency_ms"] = latency
        result["error"] = stderr.decode(errors="replace").strip()[:300]
    except FileNotFoundError:
        result["error"] = "Neither ffprobe nor ffmpeg found on PATH"
    except subprocess.TimeoutExpired:
        proc.kill()
        result["error"] = f"ffmpeg timed out ({timeout_s}s)"
        result["latency_ms"] = timeout_s * 1000

    return result

# ── AI sync helpers ──────────────────────────────────────────
def _get_canonical_camera_id(camera: Camera) -> str:
    """Return a stable ID for MediaMTX paths and AI registration."""
    from django.utils.text import slugify
    if camera.stream_path:
        return camera.stream_path
    if camera.ai_camera_id:
        return camera.ai_camera_id
    if camera.name:
        return slugify(camera.name)
    return f"camera-{camera.pk}"


from urllib.parse import urlparse


def _get_mediamtx_loopback_url(stream_path: str) -> str:
    """Return the RTSP loopback URL for AI ingestion through MediaMTX."""
    base = os.getenv("MEDIAMTX_RTSP_BASE", "").strip()

    if not base:
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080").strip()
        ai_host = (urlparse(ai_base).hostname or "").lower()

        if ai_host in {"127.0.0.1", "localhost", "0.0.0.0"}:
            base = "rtsp://127.0.0.1:8554"
        else:
            base = "rtsp://mediamtx:8554"

    return f"{base.rstrip('/')}/{str(stream_path).lstrip('/')}"


def _get_mediamtx_api_base() -> str:
    return os.getenv("MEDIAMTX_API_BASE", "http://127.0.0.1:9997").rstrip("/")


def classify_camera_source(url: str) -> str:
    lowered = url.strip().lower()
    if lowered.startswith((
        "rtsp://", "rtsps://", "rtmp://", "rtmps://",
        "srt://", "whep://", "wheps://"
    )):
        return "native"
    if ".m3u8" in lowered:
        return "hls"
    if any(x in lowered for x in ["getoneshot", "snapshot"]):
        return "snapshot"
    if any(x in lowered for x in [".mjpg", ".mjpeg", "/mjpg", "/mjpeg", "nphmotionjpeg", "motionjpeg"]):
        return "mjpeg"
    return "unknown"


def build_mediamtx_path_payload(camera: Camera, path_name: str, source_kind: str) -> dict:
    if source_kind in ("native", "hls"):
        payload = {
            "source": camera.rtsp_url,
            "sourceOnDemand": True,
            "sourceOnDemandStartTimeout": "20s",
            "sourceOnDemandCloseAfter": "10s",
        }
        if source_kind == "native" and camera.rtsp_url.strip().lower().startswith("rtsp"):
            payload["rtspTransport"] = "tcp"
        if camera.source_fingerprint:
            payload["sourceFingerprint"] = camera.source_fingerprint
        return payload
    elif source_kind == "mjpeg":
        escaped_url = camera.rtsp_url.replace('"', '\\"')
        
        ffmpeg_cmd = 'ffmpeg -nostdin -loglevel warning '
        if camera.rtsp_url.lower().startswith("https://"):
            ffmpeg_cmd += '-tls_verify 0 '

        run_on_demand = (
            ffmpeg_cmd +
            f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
            f'-f mjpeg -i "{escaped_url}" '
            f'-an -c:v libx264 -preset ultrafast -tune zerolatency '
            f'-pix_fmt yuv420p -g 30 '
            f'-f rtsp rtsp://127.0.0.1:8554/{path_name}'
        )
        return {
            "source": "publisher",
            "sourceOnDemand": False,
            "runOnDemand": run_on_demand,
            "runOnDemandRestart": True,
            "runOnDemandStartTimeout": "20s",
            "runOnDemandCloseAfter": "10s",
        }
    else:
        raise ValueError(f"Unsupported source kind '{source_kind}' for MediaMTX live provisioning.")


def _ensure_mediamtx_path(camera: Camera) -> tuple[str, str, str]:
    import os
    import requests as http_client

    path_name = _get_canonical_camera_id(camera)
    if not camera.rtsp_url:
        raise ValueError(f"Camera '{camera.name}' has no rtsp_url; cannot provision MediaMTX.")

    api_base = _get_mediamtx_api_base()
    
    source_kind = camera.source_kind or classify_camera_source(camera.rtsp_url)
    payload = build_mediamtx_path_payload(camera, path_name, source_kind)

    # Make sure API is reachable.
    info_resp = http_client.get(f"{api_base}/v3/config/global/get", timeout=5)
    info_resp.raise_for_status()

    # Check whether path exists.
    check_resp = http_client.get(f"{api_base}/v3/config/paths/get/{path_name}", timeout=5)

    if check_resp.status_code == 200:
        write_resp = http_client.patch(
            f"{api_base}/v3/config/paths/patch/{path_name}",
            json=payload,
            timeout=5,
        )
        if write_resp.status_code >= 400:
            raise RuntimeError(f"MediaMTX patch failed for {path_name}: {write_resp.status_code} {write_resp.text}")
        write_resp.raise_for_status()
    elif check_resp.status_code == 404:
        write_resp = http_client.post(
            f"{api_base}/v3/config/paths/add/{path_name}",
            json=payload,
            timeout=5,
        )
        if write_resp.status_code >= 400:
            raise RuntimeError(f"MediaMTX add failed for {path_name}: {write_resp.status_code} {write_resp.text}")
        write_resp.raise_for_status()
    else:
        raise RuntimeError(
            f"Unexpected MediaMTX response while checking path '{path_name}': "
            f"{check_resp.status_code} {check_resp.text[:300]}"
        )

    verify_resp = http_client.get(f"{api_base}/v3/config/paths/get/{path_name}", timeout=5)
    verify_resp.raise_for_status()
    verify_data = verify_resp.json()
    actual_source = (verify_data.get("source") or "").strip()
    
    expected_source = payload["source"]
    expected_run_on_demand = payload.get("runOnDemand")
    actual_run_on_demand = verify_data.get("runOnDemand")
    
    if actual_source != expected_source.strip():
        raise RuntimeError(
            f"MediaMTX path '{path_name}' source mismatch. Expected '{expected_source}', got '{actual_source}'"
        )
        
    if expected_run_on_demand and actual_run_on_demand != expected_run_on_demand:
        raise RuntimeError(
            f"MediaMTX path '{path_name}' runOnDemand mismatch. Expected runOnDemand to be set."
        )
        
    return path_name, source_kind, expected_source


from typing import Dict, List

def reconcile_all_cameras_to_mediamtx() -> Dict[str, object]:
    """
    Replay all DB camera RTSP sources into MediaMTX path configs.
    Returns counts and failures for diagnostics.
    """
    results: List[dict] = []
    success = 0
    failed = 0

    for camera in Camera.objects.exclude(rtsp_url__isnull=True).exclude(rtsp_url__exact=""):
        try:
            path_name, source_kind, provisioned_source = _ensure_mediamtx_path(camera)
            results.append({
                "camera_id": camera.id,
                "name": camera.name,
                "path": path_name,
                "source_kind": source_kind,
                "provisioned_source": provisioned_source,
                "status": "ok",
                "source": camera.rtsp_url,
            })
            success += 1
        except Exception as exc:
            results.append({
                "camera_id": camera.id,
                "name": camera.name,
                "status": "error",
                "error": str(exc),
                "source": camera.rtsp_url,
            })
            failed += 1

    return {
        "total": success + failed,
        "success": success,
        "failed": failed,
        "results": results,
    }


class CameraViewSet(TenantScopedViewSet):
    queryset = Camera.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        # Write operations use CameraWriteSerializer (accepts legacy aliases)
        if self.action in ("create", "update", "partial_update"):
            return CameraWriteSerializer
        # Read: admin sees rtsp_url, others don't
        if self.request.user and self.request.user.is_staff:
            return CameraAdminSerializer
        return CameraSafeSerializer

    def _assert_camera_write_access(self, request):
        tenant = get_active_tenant(request)
        return assert_non_viewer(request, tenant)

    def perform_create(self, serializer):
        """
        Save camera first, then provision the MediaMTX path immediately when rtsp_url exists.
        """
        from django.utils.text import slugify
        
        camera = serializer.save()
        
        # DECOUPLED FIX: Generate stream_path immediately upon creation.
        # Do not wait for AI to sync. MediaMTX needs this path instantly.
        if not camera.stream_path:
            camera.stream_path = slugify(camera.name) or f"cam_{camera.id}"
            camera.save(update_fields=["stream_path"])

        if camera.rtsp_url:
            try:
                _ensure_mediamtx_path(camera)
            except Exception:
                # Creation should not hard-fail on provisioning in admin UI flows.
                # sync_to_ai will surface a hard error later if still broken.
                pass

    def perform_update(self, serializer):
        """Sync MediaMTX path when camera is updated."""
        from django.utils.text import slugify
        
        camera = serializer.save()
        
        if not camera.stream_path:
            camera.stream_path = slugify(camera.name) or f"cam_{camera.id}"
            camera.save(update_fields=["stream_path"])

        if camera.rtsp_url:
            try:
                _ensure_mediamtx_path(camera)
            except Exception:
                pass

    def perform_destroy(self, instance):
        """Cleanup MediaMTX path when camera is deleted."""
        path_name = _get_canonical_camera_id(instance)
        api_base = _get_mediamtx_api_base()
        import requests as http_client
        try:
            http_client.delete(f"{api_base}/v3/config/paths/delete/{path_name}", timeout=5)
        except Exception:
            pass
        instance.delete()

    @action(detail=False, methods=["post"], url_path="reconcile_mediamtx")
    def reconcile_mediamtx(self, request):
        self._assert_camera_write_access(request)
        summary = reconcile_all_cameras_to_mediamtx()
        status_code = status.HTTP_200_OK if summary["failed"] == 0 else status.HTTP_207_MULTI_STATUS
        return Response(summary, status=status_code)

    @action(detail=True, methods=["post"], url_path="sync_to_ai")
    def sync_to_ai(self, request, pk=None):
        """POST /api/cameras/{id}/sync_to_ai/ — register camera with AI module."""
        import requests as http_client

        self._assert_camera_write_access(request)
        camera = self.get_object()
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080").rstrip("/")

        try:
            stream_id, source_kind, _ = _ensure_mediamtx_path(camera)
        except Exception as exc:
            return Response(
                {"error": f"MediaMTX provisioning failed: {str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        loopback_url = _get_mediamtx_loopback_url(stream_id)

        payload = {
            "camera_id": stream_id,
            "rtsp_url": loopback_url,
            "ingest_backend": request.data.get("ingest_backend", "opencv"),
            "enabled_lanes": request.data.get(
                "enabled_lanes",
                camera.enabled_lanes if camera.enabled_lanes else ["rt_detr", "person_zone"],
            ),
            "sample_hz": request.data.get("sample_hz", 2.0),
        }

        try:
            resp = http_client.post(
                f"{ai_base}/api/v1/cameras/register",
                json=payload,
                timeout=3.0,
            )
        except http_client.ConnectionError:
            return Response({"error": "AI service unavailable"}, status=status.HTTP_502_BAD_GATEWAY)
        except http_client.Timeout:
            return Response(
                {
                    "error": "AI service is busy or starting up.", 
                    "suggestion": "The request was sent, please refresh in a few moments."
                }, 
                status=status.HTTP_504_GATEWAY_TIMEOUT
            )

        if resp.status_code not in (200, 201):
            camera.status = Camera.Status.INACTIVE
            camera.save(update_fields=["status", "updated_at"])
            return Response(
                {"error": f"AI returned {resp.status_code}", "detail": resp.text[:500]},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        ai_data = resp.json()
        camera.ai_camera_id = ai_data.get("camera_id", stream_id)
        camera.status = Camera.Status.ACTIVE
        camera.source_type = Camera.SourceType.REGISTERED
        update_fields = ["ai_camera_id", "status", "source_type", "updated_at"]

        camera.save(update_fields=update_fields)

        return Response({
            "status": "synced",
            "ai_camera_id": camera.ai_camera_id,
            "stream_path": camera.stream_path,
            "hot_loaded": ai_data.get("hot_loaded", False),
            "rtsp_url_sent": payload["rtsp_url"],
            "path_name": stream_id,
            "db_rtsp_url": camera.rtsp_url,
            "loopback_rtsp_url": payload["rtsp_url"],
        })

    @action(detail=True, methods=["post"], url_path="runtime_control")
    def runtime_control(self, request, pk=None):
        """POST /api/cameras/{id}/runtime_control/ — start/stop AI task (Phase 3)."""
        import requests as http_client
        self._assert_camera_write_access(request)
        camera = self.get_object()
        enabled = request.data.get("enabled")
        if enabled is None:
            return Response({"error": "Field 'enabled' (bool) is required"}, status=status.HTTP_400_BAD_REQUEST)

        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
        cam_id = camera.ai_camera_id or _get_canonical_camera_id(camera)

        # If enabling, ensure registered first (ensure AI knows about loopback)
        if enabled:
            sync_payload = {
                "camera_id": cam_id,
                "rtsp_url": _get_mediamtx_loopback_url(cam_id),
                "enabled_lanes": camera.enabled_lanes if camera.enabled_lanes else ["rt_detr", "person_zone"],
            }
            try:
                http_client.post(f"{ai_base}/api/v1/cameras/register", json=sync_payload, timeout=5)
            except Exception:
                pass

        try:
            # Fix: AI endpoint expects a raw boolean Body, not an object (Objective 4)
            resp = http_client.post(
                f"{ai_base}/api/v1/cameras/{cam_id}/runtime-control",
                json=bool(enabled),
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                camera.status = Camera.Status.ACTIVE if data.get("running") else Camera.Status.INACTIVE
                camera.save(update_fields=["status", "updated_at"])
                return Response(data)
            return Response(
                {"error": f"AI returned {resp.status_code}", "detail": resp.text[:500]},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    # ── Zone CRUD ────────────────────────────────────────────
    @action(detail=True, methods=["get", "post"], url_path="zones")
    def zones(self, request, pk=None):
        """GET/POST /api/cameras/{id}/zones/"""
        camera = self.get_object()
        if request.method == "GET":
            qs = CameraZone.objects.filter(camera=camera).order_by("zone_name")
            return Response(CameraZoneSerializer(qs, many=True).data)
        # POST — create new zone
        self._assert_camera_write_access(request)
        ser = CameraZoneSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(camera=camera)
        return Response(ser.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["put", "delete"], url_path=r"zones/(?P<zone_id>\d+)")
    def zone_detail(self, request, pk=None, zone_id=None):
        """PUT/DELETE /api/cameras/{id}/zones/{zone_id}/"""
        self._assert_camera_write_access(request)
        camera = self.get_object()
        try:
            zone = CameraZone.objects.get(pk=zone_id, camera=camera)
        except CameraZone.DoesNotExist:
            return Response({"error": "Zone not found"}, status=status.HTTP_404_NOT_FOUND)
        if request.method == "DELETE":
            zone.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        # PUT
        ser = CameraZoneSerializer(zone, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    @action(detail=True, methods=["post"], url_path="sync_zones_to_ai")
    def sync_zones_to_ai(self, request, pk=None):
        """POST /api/cameras/{id}/sync_zones_to_ai/ — push zones to AI."""
        import requests as http_client
        self._assert_camera_write_access(request)
        camera = self.get_object()
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
        cam_id = camera.ai_camera_id or f"cam_{camera.pk}"
        zones_payload = list(
            CameraZone.objects.filter(camera=camera, enabled=True).values(
                "zone_name", "zone_type", "polygon_points"
            )
        )
        try:
            resp = http_client.put(
                f"{ai_base}/api/v1/cameras/{cam_id}/zones",
                json=zones_payload, timeout=3.0,
            )
            return Response({"status": "synced", "ai_status": resp.status_code, "zones_sent": len(zones_payload)})
        except http_client.Timeout:
            return Response(
                {
                    "error": "AI service is busy or starting up.", 
                    "suggestion": "The request was sent, please refresh in a few moments."
                }, 
                status=status.HTTP_504_GATEWAY_TIMEOUT
            )
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=["post"], url_path="sync_ai_settings")
    def sync_ai_settings(self, request, pk=None):
        """POST /api/cameras/{id}/sync_ai_settings/ — push per-camera thresholds to AI."""
        import requests as http_client
        self._assert_camera_write_access(request)
        camera = self.get_object()
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
        cam_id = camera.ai_camera_id or f"cam_{camera.pk}"
        payload = {
            "min_confidence": camera.min_confidence,
            "min_bbox_area": camera.min_bbox_area,
            "k_of_n": [camera.k_of_n_k, camera.k_of_n_n],
            "cooldown_s": camera.cooldown_s,
        }
        try:
            resp = http_client.put(
                f"{ai_base}/api/v1/cameras/{cam_id}/settings",
                json=payload, timeout=3.0,
            )
            return Response({"status": "synced", "ai_status": resp.status_code})
        except http_client.Timeout:
            return Response(
                {
                    "error": "AI service is busy or starting up.", 
                    "suggestion": "The request was sent, please refresh in a few moments."
                }, 
                status=status.HTTP_504_GATEWAY_TIMEOUT
            )
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    def _do_test_connection(self, rtsp_url, camera=None, timeout_s=5):
        import uuid
        import requests as http_client
        if not rtsp_url:
            return Response({"ok": False, "category": "missing_url", "error": "No URL provided."}, status=status.HTTP_400_BAD_REQUEST)
        
        source_kind = classify_camera_source(rtsp_url)
        path_name = _get_canonical_camera_id(camera) if camera else f"test-{uuid.uuid4().hex[:8]}"

        temp_cam = camera if camera else Camera(rtsp_url=rtsp_url)
        try:
            payload = build_mediamtx_path_payload(temp_cam, path_name, source_kind)
        except ValueError as exc:
            return Response({"ok": False, "category": "unsupported_source", "message": str(exc), "error": str(exc)})
        api_base = _get_mediamtx_api_base()
        
        try:
            info = http_client.get(f"{api_base}/v3/config/global/get", timeout=5)
            info.raise_for_status()
        except Exception:
            return Response({"ok": False, "category": "mediamtx_api_unavailable", "message": "MediaMTX Control API unreachable.", "error": "MediaMTX Control API unreachable."})
            
        try:
            check = http_client.get(f"{api_base}/v3/config/paths/get/{path_name}", timeout=5)
            if check.status_code == 200:
                write = http_client.patch(f"{api_base}/v3/config/paths/patch/{path_name}", json=payload, timeout=5)
            else:
                write = http_client.post(f"{api_base}/v3/config/paths/add/{path_name}", json=payload, timeout=5)
            if write.status_code >= 400:
                raise RuntimeError(f"{write.status_code} {write.text}")
        except Exception as exc:
            if "tls" in str(exc).lower() or "certificate" in str(exc).lower():
                cat = "tls_validation_error"
            else:
                cat = "path_provision_failed"
            return Response({"ok": False, "category": cat, "message": str(exc), "error": str(exc)})
            
        loopback_url = _get_mediamtx_loopback_url(path_name)
        
        from .stream_workers import _probe_rtsp
        probe_result = _probe_rtsp(loopback_url, timeout_s=timeout_s)
        
        if not camera:
            try:
                http_client.delete(f"{api_base}/v3/config/paths/delete/{path_name}", timeout=5)
            except Exception:
                pass
                
        if not probe_result.get("ok"):
            cat = "source_timeout" if "timeout" in str(probe_result.get("error", "")).lower() else "loopback_unavailable"
            return Response({
                "ok": False, 
                "category": cat, 
                "message": probe_result.get("error", "Unknown probe error"),
                "error": probe_result.get("error", "Unknown probe error"),
                "source_kind": source_kind,
                "path_name": path_name,
                "loopback_rtsp_url": loopback_url,
            })
            
        return Response({
            "ok": True,
            "category": "ok",
            "message": f"Connection OK ({probe_result.get('method')})",
            "source_kind": source_kind,
            "path_name": path_name,
            "loopback_rtsp_url": loopback_url,
            "details": probe_result.get("details"),
            "latency_ms": probe_result.get("latency_ms"),
            "method": probe_result.get("method"),
        })

    # ── Test connection (existing camera) ───────────────────
    @action(detail=True, methods=["post"], url_path="test_connection")
    def test_connection_detail(self, request, pk=None):
        """POST /api/cameras/{id}/test_connection/ — test stored RTSP URL via MediaMTX."""
        self._assert_camera_write_access(request)
        camera = self.get_object()
        timeout_s = min(int(request.data.get("timeout_s", 5)), 15)
        return self._do_test_connection(camera.rtsp_url, camera=camera, timeout_s=timeout_s)

    # ── Test connection (unsaved URL) ───────────────────────
    @action(detail=False, methods=["post"], url_path="test_connection")
    def test_connection_list(self, request):
        """
        CLOUD FIX: HTTP 202 Accepted Pattern.
        Instead of running ffprobe in the web thread, enqueue it.
        """
        self._assert_camera_write_access(request)
        rtsp_url = request.data.get("rtsp_url", "").strip()
        if not rtsp_url:
            return Response({"error": "rtsp_url is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Example pseudo-code for Celery task queuing
        # task = probe_rtsp_task.delay(rtsp_url)
        # return Response({"task_id": task.id, "status": "processing"}, status=status.HTTP_202_ACCEPTED)

        # If Celery is not yet implemented, simulate a strict 2-second timeout locally,
        # but tag this heavily for Phase 2 infrastructure migration.
        timeout_s = 2 # Strictly reduced for Cloud Load Balancers
        result = self._do_test_connection(rtsp_url, camera=None, timeout_s=timeout_s)
        return Response(result)

class IncidentViewSet(TenantScopedViewSet):
    queryset = Incident.objects.select_related("camera").all()
    serializer_class = IncidentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        """Create incident. Notifications are sent automatically via Django signal."""
        tenant = get_active_tenant(self.request)
        assert_non_viewer(self.request, tenant)
        
        # Save the incident - the post_save signal will broadcast notifications
        serializer.save(tenant=tenant)

    def get_queryset(self):
        qs = super().get_queryset().order_by("-started_at")
        status_filter = self.request.query_params.get("status")
        type_filter = self.request.query_params.get("type")
        search = (self.request.query_params.get("search") or "").strip()
        if status_filter:
            qs = qs.filter(status=status_filter)
        if type_filter:
            qs = qs.filter(type=type_filter)
        if search:
            query = (
                Q(type__icontains=search)
                | Q(camera__name__icontains=search)
                | Q(details_text__icontains=search)
            )
            if search.isdigit():
                query |= Q(id=int(search))
            qs = qs.annotate(details_text=Cast("details", output_field=TextField())).filter(query)
        return qs

    @action(detail=True, methods=["post"], url_path="acknowledge")
    def acknowledge(self, request, pk=None):
        tenant = get_active_tenant(request)
        assert_non_viewer(request, tenant)
        incident = self.get_object()
        if incident.status == "resolved":
            return Response({"error": "Incident already resolved"}, status=status.HTTP_400_BAD_REQUEST)
        incident.status = "acknowledged"
        incident.save(update_fields=["status", "updated_at"])
        # Audit
        AuditLog.objects.create(
            tenant=tenant, actor=request.user,
            action="incident.acknowledge", target_type="incident", target_id=str(incident.pk),
        )
        return Response(IncidentSerializer(incident).data)

    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve(self, request, pk=None):
        tenant = get_active_tenant(request)
        assert_non_viewer(request, tenant)
        incident = self.get_object()
        incident.status = "resolved"
        incident.ended_at = timezone.now()
        incident.save(update_fields=["status", "ended_at", "updated_at"])
        AuditLog.objects.create(
            tenant=tenant, actor=request.user,
            action="incident.resolve", target_type="incident", target_id=str(incident.pk),
        )
        return Response(IncidentSerializer(incident).data)

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """Aggregated incident stats for dashboard & reports."""
        from django.db.models import Count
        from django.db.models.functions import TruncDate
        import datetime

        tenant = get_active_tenant(request)
        qs = Incident.objects.filter(tenant=tenant)

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - datetime.timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)

        today_count = qs.filter(started_at__gte=today_start).count()
        week_count = qs.filter(started_at__gte=week_start).count()
        month_count = qs.filter(started_at__gte=month_start).count()
        total_count = qs.count()

        # Type breakdown
        type_breakdown = list(qs.values("type").annotate(count=Count("id")).order_by("-count"))

        # Per-day (last 7 days)
        seven_days_ago = today_start - datetime.timedelta(days=6)
        per_day = list(
            qs.filter(started_at__gte=seven_days_ago)
            .annotate(day=TruncDate("started_at"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )

        # Status breakdown
        status_breakdown = list(qs.values("status").annotate(count=Count("id")))

        return Response({
            "today": today_count,
            "week": week_count,
            "month": month_count,
            "total": total_count,
            "type_breakdown": type_breakdown,
            "per_day": [{"day": str(d["day"]), "count": d["count"]} for d in per_day],
            "status_breakdown": status_breakdown,
        })

class DetectionViewSet(TenantScopedViewSet):
    queryset = Detection.objects.all()
    serializer_class = DetectionSerializer
    permission_classes = [permissions.IsAuthenticated]

class AlertViewSet(TenantScopedViewSet):
    queryset = Alert.objects.all()
    serializer_class = AlertSerializer
    permission_classes = [permissions.IsAuthenticated]

class AuditLogViewSet(TenantScopedViewSet):
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated]

class ProfileViewSet(viewsets.ModelViewSet):
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Users can only access their own profile
        return Profile.objects.filter(user=self.request.user)

    def perform_update(self, serializer):
        tenant = get_active_tenant(self.request)
        assert_non_viewer(self.request, tenant)
        serializer.save(user=self.request.user)

    def list(self, request, *args, **kwargs):
        """Return single profile (auto-create if missing)."""
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response(ProfileSerializer(profile).data)

    @action(detail=False, methods=["get", "put", "patch"], url_path="me")
    def me(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        if request.method == "GET":
            return Response(ProfileSerializer(profile).data)
        tenant = get_active_tenant(request)
        assert_non_viewer(request, tenant)
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProfileSerializer(profile).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_summary(request):
    """Single endpoint for all dashboard data."""
    import datetime
    from django.db.models import Count

    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied("Not a member of this tenant.")

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - datetime.timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    incidents = Incident.objects.filter(tenant=tenant)

    # Cameras - DECOUPLED FIX: Include stream_path so the UI can construct 
    # MediaMTX WebRTC URLs without waiting for AI synchronization.
    cameras_qs = Camera.objects.filter(tenant=tenant).values(
        "id", "name", "site", "status", "ai_camera_id", "source_type", "stream_path", "rtsp_url"
    )
    
    cameras = []
    for cam in cameras_qs:
        # Convert rtsp_url presence to a safe boolean for the UI (hide credentials)
        cam["has_stream"] = bool(cam.pop("rtsp_url", None))
        cameras.append(cam)

    active_cameras = sum(1 for cam in cameras if cam.get("status") == Camera.Status.ACTIVE)

    # Incident counts
    stats = {
        "today": incidents.filter(started_at__gte=today_start).count(),
        "week": incidents.filter(started_at__gte=week_start).count(),
        "month": incidents.filter(started_at__gte=month_start).count(),
        "open": incidents.filter(status=Incident.Status.OPEN).count(),
        "critical": incidents.filter(severity__gte=4, started_at__gte=today_start).count(),
        "camera_total": len(cameras),
        "camera_live": active_cameras,
    }

    # Recent incidents (last 10)
    recent_incidents = list(
        incidents.order_by("-started_at")[:10].values(
            "id", "type", "status", "severity", "started_at",
            "camera__name", "camera__source_type", "details",
        )
    )

    # Type breakdown
    type_breakdown = list(incidents.values("type").annotate(count=Count("id")).order_by("-count"))

    # Recent audit
    recent_audit = list(
        AuditLog.objects.filter(tenant=tenant)
        .select_related("actor")
        .order_by("-created_at")[:10]
        .values("id", "action", "target_type", "target_id", "created_at", "actor__username")
    )

    # AI health check (non-blocking, best effort)
    ai_healthy = False
    try:
        import requests as http_client
        from requests.exceptions import RequestException
        import logging
        
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
        resp = http_client.get(f"{ai_base}/api/v1/health", timeout=3)
        ai_healthy = resp.status_code == 200
    except RequestException as exc:
        import logging
        logging.getLogger(__name__).warning("AI Engine health check failed: %s", exc)
        # Continue silently for the user, but now we have an audit trail

    return Response({
        "cameras": cameras,
        "stats": stats,
        "recent_incidents": recent_incidents,
        "type_breakdown": type_breakdown,
        "recent_audit": [
            {**a, "actor": a.pop("actor__username", None)} for a in recent_audit
        ],
        "ai_healthy": ai_healthy,
    })

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def auth_context(request):
    tenant = get_active_tenant(request, required=False)

    # Demo-safety net: if a user has no tenant memberships (e.g., created via admin/import),
    # create a personal community on first login so they never hit a dead-end.
    # Disabled to allow new users to select from pending community invites instead.
    auto_create_first_login = getattr(
        settings, "AUTO_CREATE_TENANT_ON_FIRST_LOGIN", False
    )
    if tenant is None and auto_create_first_login:
        memberships_qs = Membership.objects.select_related("tenant").filter(user=request.user)
        if memberships_qs.count() == 0:
            with transaction.atomic():
                t = Tenant.objects.create(name=f"{request.user.username}'s Community")
                Membership.objects.create(user=request.user, tenant=t, role=Membership.Role.OWNER)
            tenant = t

    # If no tenant header, and user has exactly one membership, auto-select it
    if tenant is None:
        memberships = Membership.objects.select_related("tenant").filter(user=request.user)
        if memberships.count() == 1:
            tenant = memberships.first().tenant

    role = None
    tenant_payload = None

    if tenant:
        m = Membership.objects.filter(user=request.user, tenant=tenant).first()
        if m:
            role = m.role
            tenant_payload = {"id": tenant.id, "name": tenant.name}

    return Response({
        "user": {
            "id": request.user.id,
            "username": request.user.username,
            "email": request.user.email,
            "is_superuser": request.user.is_superuser,
            "is_staff": request.user.is_staff,
        },
        "tenant": tenant_payload,
        "role": role,
    })

def assert_role_in(request, tenant, allowed_roles):
    if not request.user or not request.user.is_authenticated:
        raise NotAuthenticated()
    membership = Membership.objects.filter(user=request.user, tenant=tenant).first()
    if not membership or membership.role not in allowed_roles:
        raise PermissionDenied("Insufficient permissions.")
    return membership


class KnownEntityViewSet(TenantScopedViewSet):
    """
    Django-authoritative CRUD for enrolled entities.

    POST stores the entity in Django **and** forwards images to AI enroll.
    The ai_entity_id returned from AI is persisted for linkage.
    """
    queryset = KnownEntity.objects.all()
    serializer_class = KnownEntitySerializer
    permission_classes = [permissions.IsAuthenticated]
    # Accept both JSON and multipart
    from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        qs = super().get_queryset().order_by("-created_at")
        cat = self.request.query_params.get("category")
        group = self.request.query_params.get("group")
        if cat:
            qs = qs.filter(category=cat)
        if group:
            qs = qs.filter(group=group)
        return qs

    def create(self, request, *args, **kwargs):
        """
        Override create to handle multipart form data with images.
        The serializer validates name/category/group/notes, then we
        forward files to the AI enroll endpoint.
        """
        import requests as http_client

        # Build serializer from combined POST data (works for both JSON and multipart)
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        tenant = get_active_tenant(self.request)
        assert_non_viewer(self.request, tenant)
        entity = serializer.save(tenant=tenant)

        # Collect uploaded files
        uploaded_files = request.FILES.getlist("files")

        # Best-effort AI enrollment (forward images to AI module)
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
        endpoint = (
            "/entities/enroll_pet" if entity.category == "pet"
            else "/entities/enroll_person"
        )

        ai_data = {}
        try:
            if uploaded_files:
                # Multipart: forward files to AI's /entities/enroll_person or /entities/enroll_pet
                files_payload = []
                for f in uploaded_files:
                    f.seek(0)  # ensure at start
                    files_payload.append(("files", (f.name, f.read(), f.content_type or "image/jpeg")))

                form_data = {"name": entity.name}
                if entity.category != "pet":
                    form_data["role"] = "VISITOR"

                resp = http_client.post(
                    f"{ai_base}{endpoint}",
                    data=form_data,
                    files=files_payload,
                    timeout=30,
                )
            else:
                # No images — just register metadata (AI may reject with "no face found")
                resp = http_client.post(
                    f"{ai_base}{endpoint}",
                    data={"name": entity.name, "role": "VISITOR"},
                    timeout=10,
                )

            if resp.status_code in (200, 201):
                ai_data = resp.json()
                entity.ai_entity_id = str(ai_data.get("entity_id", ai_data.get("id", "")))
                
                # CLOUD FIX: Do not rely on local file paths like /enroll_images/...
                # In the cloud, the AI engine MUST upload the crop to an S3 bucket 
                # and return the CDN URL, or return a Base64 string for lightweight thumbnails.
                
                if ai_data.get("thumbnail_b64"):
                    # Store small base64 directly, or save to Django's configured Storage backend (S3)
                    entity.thumbnail_url = f"data:image/jpeg;base64,{ai_data['thumbnail_b64']}"
                elif ai_data.get("s3_url"):
                    entity.thumbnail_url = ai_data["s3_url"]
                else:
                    # Fallback ONLY if strictly needed during local dev migration
                    p = str(ai_data.get("thumbnail", ""))
                    if p.startswith("/api/"): p = p[4:]
                    if p.startswith("/enroll_images/"): p = f"/ai{p}"
                    entity.thumbnail_url = p

                entity.save(update_fields=["ai_entity_id", "thumbnail_url", "updated_at"])
                self._sync_entity_to_ai(entity)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("AI enrollment failed: %s", exc)
            # Entity is saved locally even if AI is down

        headers = self.get_success_headers(serializer.data)
        result = self.get_serializer(entity).data
        result = self._merge_ai_identity_state(result)
        # Include AI enrollment details for the frontend
        result["ai_enrollment"] = {
            "embeddings_stored": ai_data.get("embeddings_stored", 0),
            "saved_images_count": ai_data.get("saved_images_count", 0),
            "failed_images": ai_data.get("failed_images", []),
        }
        return Response(result, status=status.HTTP_201_CREATED, headers=headers)

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        ai_map = self._fetch_ai_entity_state_map()
        if isinstance(response.data, list):
            response.data = [self._merge_ai_identity_state(item, ai_map=ai_map) for item in response.data]
        elif isinstance(response.data, dict) and isinstance(response.data.get("results"), list):
            response.data["results"] = [
                self._merge_ai_identity_state(item, ai_map=ai_map)
                for item in response.data["results"]
            ]
        return response

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        if isinstance(response.data, dict):
            response.data = self._merge_ai_identity_state(response.data, ai_map=self._fetch_ai_entity_state_map())
        return response

    def update(self, request, *args, **kwargs):
        tenant = get_active_tenant(request)
        assert_non_viewer(request, tenant)
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        entity = serializer.save()
        self._sync_entity_to_ai(entity)
        return Response(self.get_serializer(entity).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def _allowed_ai_camera_ids(self, entity) -> List[str]:
        allowed = []
        for cam in entity.cameras.all():
            cam_id = (cam.ai_camera_id or "").strip() or str(cam.id)
            allowed.append(cam_id)
        return sorted(set(allowed))

    def _sync_entity_to_ai(self, entity):
        if not entity.ai_entity_id:
            return

        import requests as http_client

        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
        payload = {
            "name": entity.name,
            "metadata": {
                "allowed_camera_ids": self._allowed_ai_camera_ids(entity),
            },
        }
        try:
            http_client.put(
                f"{ai_base}/entities/{entity.ai_entity_id}",
                json=payload,
                timeout=10,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("AI entity metadata sync failed: %s", exc)

    def _fetch_ai_entity_state_map(self):
        import requests as http_client

        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
        try:
            resp = http_client.get(f"{ai_base}/entities", timeout=5)
            if resp.status_code != 200:
                return {}
            raw = resp.json()
            entities = raw if isinstance(raw, list) else []
            return {
                str(item.get("entity_id") or item.get("id") or ""): item
                for item in entities
                if isinstance(item, dict)
            }
        except Exception:
            return {}

    def _merge_ai_identity_state(self, payload: dict, ai_map=None):
        """Overlay AI-managed identity state (last_seen/last_camera_id) in API responses."""
        ai_entity_id = str(payload.get("ai_entity_id") or "").strip()
        if not ai_entity_id:
            return payload

        by_id = ai_map if isinstance(ai_map, dict) else self._fetch_ai_entity_state_map()
        ai_item = by_id.get(ai_entity_id)
        if not ai_item:
            return payload
        if ai_item.get("last_seen"):
            payload["last_seen"] = ai_item.get("last_seen")
        if ai_item.get("last_camera_id"):
            payload["last_camera_id"] = ai_item.get("last_camera_id")
        return payload

    def perform_destroy(self, instance):
        """Delete from AI then from Django."""
        import requests as http_client
        tenant = get_active_tenant(self.request)
        assert_non_viewer(self.request, tenant)

        if instance.ai_entity_id:
            ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
            try:
                http_client.delete(
                    f"{ai_base}/entities/{instance.ai_entity_id}",
                    timeout=10,
                )
            except Exception:
                pass
        instance.delete()


class InvitationViewSet(viewsets.ModelViewSet):
    queryset = Invitation.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ["create"]:
            return InvitationCreateSerializer
        if self.action in ["pending"]:
            return PendingInvitationSerializer
        return PendingInvitationSerializer

    def create(self, request, *args, **kwargs):
        # tenant-scoped (requires header) — invite into current tenant
        tenant = get_active_tenant(request)  # required
        assert_role_in(request, tenant, allowed_roles={"owner", "admin"})

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].lower()
        
        # Check if a pending invitation already exists for this email + tenant
        existing_invite = Invitation.objects.filter(
            tenant=tenant,
            email=email,
            status=Invitation.Status.PENDING,
            expires_at__gt=timezone.now()
        ).first()
        
        if existing_invite:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"email": "A pending invitation already exists for this email."})

        inv = Invitation.objects.create(
            tenant=tenant,
            email=email,
            role=serializer.validated_data["role"],
            invited_by=request.user,
        )
        return Response(PendingInvitationSerializer(inv).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="pending")
    def pending(self, request):
        # no tenant header required
        email = (request.user.email or "").lower()
        qs = (
            Invitation.objects
            .select_related("tenant", "invited_by")
            .filter(email=email, status="pending", expires_at__gt=timezone.now())
            .order_by("-created_at")
        )
        return Response(PendingInvitationSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="accept")
    @transaction.atomic
    def accept(self, request, pk=None):
        inv = self.get_object()

        if (request.user.email or "").lower() != inv.email.lower():
            raise PermissionDenied("This invitation is not for your account.")

        if not inv.is_valid():
            raise PermissionDenied("Invitation is not valid (expired or already used).")

        Membership.objects.get_or_create(
            tenant=inv.tenant,
            user=request.user,
            defaults={"role": inv.role},
        )

        inv.status = "accepted"
        inv.accepted_by = request.user
        inv.accepted_at = timezone.now()
        inv.save(update_fields=["status", "accepted_by", "accepted_at", "updated_at"])

        return Response({"ok": True, "tenant_id": inv.tenant.id, "role": inv.role})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §B  STREAM ENDPOINTS (OpenCV preview + MJPEG)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _stream_preview_config() -> dict:
    return {
        "fps": int(getattr(settings, "STREAM_PREVIEW_FPS", 3)),
        "max_width": int(getattr(settings, "STREAM_PREVIEW_MAX_WIDTH", 960)),
        "jpeg_quality": int(getattr(settings, "STREAM_PREVIEW_JPEG_QUALITY", 70)),
        "idle_ttl_s": int(getattr(settings, "STREAM_IDLE_TTL_SECONDS", 60)),
        "ffmpeg_capture_options": str(
            getattr(settings, "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;3000000")
        ),
    }


def _build_stream_token(camera_id: int, ttl_s: int = 60) -> tuple[str, int]:
    exp = int(time.time()) + ttl_s
    payload = f"{camera_id}.{exp}".encode()
    sig = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()[:32]
    return f"{camera_id}.{exp}.{sig}", ttl_s


def _verify_stream_token(token: str, camera_id: int) -> tuple[bool, dict]:
    try:
        tok_cam, tok_exp, tok_sig = token.split(".")
        if int(tok_cam) != int(camera_id):
            return False, {"error": "camera_mismatch"}
        if time.time() > float(tok_exp):
            return False, {"error": "expired"}
        payload = f"{tok_cam}.{tok_exp}".encode()
        expected = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(expected, tok_sig):
            return False, {"error": "signature_mismatch"}
        return True, {"camera_id": int(tok_cam), "exp": int(tok_exp)}
    except Exception:
        return False, {"error": "malformed"}


def _camera_from_jwt_scope(request, camera_id: int) -> Camera:
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    try:
        return Camera.objects.get(pk=camera_id, tenant=tenant)
    except Camera.DoesNotExist:
        raise PermissionDenied("Camera not found for tenant")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def streams_list(request):
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    cameras = Camera.objects.filter(tenant=tenant).order_by("name")
    return Response(CameraStreamSerializer(cameras, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def streams_detail(request, camera_id):
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    try:
        camera = Camera.objects.get(pk=camera_id, tenant=tenant)
    except Camera.DoesNotExist:
        return Response({"error": "Camera not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(CameraStreamSerializer(camera).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def streams_signed_token(request, camera_id):
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    try:
        Camera.objects.get(pk=camera_id, tenant=tenant)
    except Camera.DoesNotExist:
        return Response({"error": "Camera not found"}, status=status.HTTP_404_NOT_FOUND)

    token, ttl = _build_stream_token(camera_id, ttl_s=60)
    return Response({"token": token, "ttl": ttl})


@api_view(["GET"])
@permission_classes([])
def streams_snapshot(request, camera_id):
    """JWT member auth OR signed query token auth."""
    from django.http import HttpResponse

    token_param = request.GET.get("token", "")
    camera = None

    if token_param:
        ok, _payload = _verify_stream_token(token_param, camera_id)
        if not ok:
            return Response({"error": "Invalid stream token"}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            camera = Camera.objects.get(pk=camera_id)
        except Camera.DoesNotExist:
            return Response({"error": "Camera not found"}, status=status.HTTP_404_NOT_FOUND)
    elif request.user and request.user.is_authenticated:
        try:
            camera = _camera_from_jwt_scope(request, camera_id)
        except PermissionDenied as exc:
            return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    else:
        raise NotAuthenticated("Provide Authorization header or ?token= parameter")

    cfg = _stream_preview_config()
    worker = STREAM_WORKERS.ensure_running(camera, **cfg)
    worker.touch()
    jpeg, frame_ts, last_error = STREAM_WORKERS.get_latest_jpeg(int(camera.pk))

    if jpeg:
        resp = HttpResponse(jpeg, content_type="image/jpeg")
        resp["Cache-Control"] = "no-store"
        resp["X-Frame-Timestamp"] = str(frame_ts or "")
        resp["X-Stream-Status"] = "connected"
        return resp

    return Response(
        {
            "status": "warming_up",
            "last_error": last_error,
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def community_activity(request):
    """Unified tenant timeline for dashboard/community activity cards."""
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()

    limit = min(int(request.query_params.get("limit", 20)), 100)
    events = []

    for log in AuditLog.objects.filter(tenant=tenant).select_related("actor").order_by("-created_at")[:limit]:
        actor_name = log.actor.username if log.actor else "System"
        events.append({
            "type": "audit",
            "title": log.action.replace(".", " ").replace("_", " ").title(),
            "description": log.meta.get("message") if isinstance(log.meta, dict) else "",
            "timestamp": log.created_at,
            "actor": actor_name,
            "related_type": log.target_type,
            "related_id": log.target_id,
        })

    for incident in Incident.objects.filter(tenant=tenant).select_related("camera").order_by("-updated_at")[:limit]:
        status_label = incident.get_status_display()
        events.append({
            "type": "incident",
            "title": f"Incident {incident.get_type_display()} {status_label}",
            "description": f"Camera: {incident.camera.name}",
            "timestamp": incident.updated_at,
            "actor": None,
            "related_type": "incident",
            "related_id": str(incident.id),
        })

    for entity in KnownEntity.objects.filter(tenant=tenant).order_by("-updated_at")[:limit]:
        events.append({
            "type": "entity",
            "title": f"Entity updated: {entity.name}",
            "description": f"Category: {entity.category}",
            "timestamp": entity.updated_at,
            "actor": None,
            "related_type": "entity",
            "related_id": str(entity.id),
        })

    for camera in Camera.objects.filter(tenant=tenant).order_by("-updated_at")[:limit]:
        events.append({
            "type": "camera",
            "title": f"Camera updated: {camera.name}",
            "description": f"Status: {camera.status}",
            "timestamp": camera.updated_at,
            "actor": None,
            "related_type": "camera",
            "related_id": str(camera.id),
        })

    for inv in Invitation.objects.filter(tenant=tenant).select_related("invited_by").order_by("-updated_at")[:limit]:
        inviter = inv.invited_by.username if inv.invited_by else "System"
        events.append({
            "type": "invitation",
            "title": f"Invitation {inv.status}",
            "description": f"{inv.email} ({inv.role})",
            "timestamp": inv.updated_at,
            "actor": inviter,
            "related_type": "invitation",
            "related_id": str(inv.id),
        })

    events.sort(key=lambda item: item["timestamp"], reverse=True)
    payload = []
    for item in events[:limit]:
        payload.append({
            **item,
            "timestamp": item["timestamp"].isoformat() if item["timestamp"] else None,
        })
    return Response(payload)


def _mjpeg_generator(camera_id: int, fps: int):
    interval = 1.0 / max(1, fps)
    boundary = b"--frame\r\n"
    try:
        while True:
            STREAM_WORKERS.touch(camera_id)
            jpeg, _frame_ts, _err = STREAM_WORKERS.get_latest_jpeg(camera_id)
            if jpeg:
                yield (
                    boundary
                    + b"Content-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode()
                    + b"\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
            time.sleep(interval)
    finally:
        STREAM_WORKERS.remove_viewer(camera_id)


@api_view(["GET"])
@permission_classes([])
def streams_mjpeg(request, camera_id):
    """
    CLOUD FIX: Django no longer spawns stateful OpenCV threads.
    It simply validates the token and acts as a stateless reverse proxy 
    or redirects to the dedicated streaming server (MediaMTX).
    """
    token_param = request.GET.get("token", "")
    ok, _payload = _verify_stream_token(token_param, camera_id) if token_param else (False, {})
    if not ok:
        return Response({"error": "Invalid stream token"}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        camera = Camera.objects.get(pk=camera_id)
    except Camera.DoesNotExist:
        return Response({"error": "Camera not found"}, status=status.HTTP_404_NOT_FOUND)

    # In a cloud environment, redirect the client directly to the MediaMTX stream 
    # or the AI Edge Node handling the camera, removing the load from Django entirely.
    # Assuming MediaMTX is available at a known internal/external URL:
    mediamtx_url = os.getenv("MEDIAMTX_EXTERNAL_URL", "http://localhost:8888")
    stream_path = camera.stream_path or f"cam_{camera.id}"
    
    # Redirect directly to MediaMTX API for the HLS/WebRTC/MJPEG feed
    from django.shortcuts import redirect
    return redirect(f"{mediamtx_url}/{stream_path}/stream")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def streams_health(request):
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()

    camera_ids = list(Camera.objects.filter(tenant=tenant).values_list("id", flat=True))
    cfg = _stream_preview_config()
    return Response(STREAM_WORKERS.health_for_cameras(camera_ids, default_fps=cfg["fps"]))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §4  NOTIFICATION SETTINGS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

logger = logging.getLogger(__name__)


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def notification_settings(request):
    """GET/PUT /api/notifications/settings/ — tenant channel prefs + user instant-alert preferences."""
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    channel, _ = NotificationChannel.objects.get_or_create(tenant=tenant)
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == "GET":
        return Response({
            **NotificationChannelSerializer(channel).data,
            "instant_notification_levels": normalize_instant_notification_levels(profile.instant_notification_levels),
            "available_instant_notification_levels": [
                {"value": "critical", "label": "Critical"},
                {"value": "severe", "label": "Severe"},
                {"value": "moderate", "label": "Moderate"},
                {"value": "low", "label": "Low"},
                {"value": "info", "label": "Info"},
            ],
        })

    channel_payload = dict(request.data)
    instant_levels = channel_payload.pop("instant_notification_levels", None)

    if instant_levels is not None:
        profile.instant_notification_levels = normalize_instant_notification_levels(instant_levels)
        profile.save(update_fields=["instant_notification_levels"])

    if channel_payload:
        assert_role_in(request, tenant, allowed_roles={"owner", "admin"})
        ser = NotificationChannelSerializer(channel, data=channel_payload, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()

    return Response({
        **NotificationChannelSerializer(channel).data,
        "instant_notification_levels": normalize_instant_notification_levels(profile.instant_notification_levels),
        "available_instant_notification_levels": [
            {"value": "critical", "label": "Critical"},
            {"value": "severe", "label": "Severe"},
            {"value": "moderate", "label": "Moderate"},
            {"value": "low", "label": "Low"},
            {"value": "info", "label": "Info"},
        ],
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notification_test(request):
    """POST /api/notifications/test/ — send a test notification."""
    from django.core.mail import send_mail as django_send_mail

    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    assert_role_in(request, tenant, allowed_roles={"owner", "admin"})
    channel, _ = NotificationChannel.objects.get_or_create(tenant=tenant)
    results = {"email": None, "push": None}
    if channel.email_enabled and channel.email_recipients:
        try:
            django_send_mail(
                subject="[VigilZone] Test Notification",
                message="This is a test notification from VigilZone.",
                from_email=None,  # uses DEFAULT_FROM_EMAIL
                recipient_list=channel.email_recipients,
            )
            results["email"] = "sent"
        except Exception as exc:
            results["email"] = f"error: {exc}"
    else:
        results["email"] = "disabled or no recipients"

    if channel.push_enabled and channel.fcm_tokens:
        results["push"] = "placeholder — FCM not configured yet"
    else:
        results["push"] = "disabled or no tokens"

    return Response(results)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notification_register_device(request):
    """POST /api/notifications/register_device/ — store FCM token."""
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    token = request.data.get("token", "").strip()
    if not token:
        return Response({"error": "token required"}, status=status.HTTP_400_BAD_REQUEST)
    channel, _ = NotificationChannel.objects.get_or_create(tenant=tenant)
    tokens = list(channel.fcm_tokens or [])
    if token not in tokens:
        tokens.append(token)
        channel.fcm_tokens = tokens
        channel.save(update_fields=["fcm_tokens", "updated_at"])
    return Response({"stored": True, "total_tokens": len(tokens)})


def dispatch_notifications(incident: Incident):
    """Fire notifications for an incident.
    Now broadcasts to all tenant members via WebSocket + creates alerts."""
    NotificationService.broadcast_incident(incident)


def _bool_from_env(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_bool(raw, default=False):
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _ensure_tenant_webcam_camera(tenant: Tenant, enabled: bool | None = None) -> Camera:
    """Ensure a stable cam_live record exists for the tenant."""
    camera = (
        Camera.objects.filter(tenant=tenant)
        .filter(
            Q(ai_camera_id="cam_live")
            | Q(stream_path="cam_live")
            | Q(source_type=Camera.SourceType.WEBCAM)
        )
        .order_by("id")
        .first()
    )

    target_status = (
        Camera.Status.ACTIVE
        if enabled is True
        else Camera.Status.INACTIVE
        if enabled is False
        else None
    )

    if camera is None:
        return Camera.objects.create(
            tenant=tenant,
            name="Live Webcam",
            ai_camera_id="cam_live",
            stream_path="cam_live",
            source_type=Camera.SourceType.WEBCAM,
            status=target_status or Camera.Status.INACTIVE,
        )

    update_fields = []
    if not camera.name:
        camera.name = "Live Webcam"
        update_fields.append("name")
    if camera.ai_camera_id != "cam_live":
        camera.ai_camera_id = "cam_live"
        update_fields.append("ai_camera_id")
    if camera.stream_path != "cam_live":
        camera.stream_path = "cam_live"
        update_fields.append("stream_path")
    if camera.source_type != Camera.SourceType.WEBCAM:
        camera.source_type = Camera.SourceType.WEBCAM
        update_fields.append("source_type")
    if target_status and camera.status != target_status:
        camera.status = target_status
        update_fields.append("status")
    if update_fields:
        update_fields.append("updated_at")
        camera.save(update_fields=update_fields)
    return camera


def _set_ai_webcam_runtime(enabled: bool, tenant: Tenant | None = None) -> dict:
    import requests as http_client

    ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080").rstrip("/")
    control_url = f"{ai_base}/api/v1/cameras/cam_live/runtime-control"
    status_url = f"{ai_base}/api/v1/cameras/cam_live/runtime-status"

    timeout_s = 25
    control_payload: bool | dict = bool(enabled)
    if tenant is not None:
        control_payload = {
            "enabled": bool(enabled),
            "tenant_id": tenant.id,
            "camera_id": "cam_live",
            "source_type": "webcam",
        }
    resp = http_client.post(control_url, json=control_payload, timeout=timeout_s)
    if resp.status_code >= 400:
        raise RuntimeError(f"AI runtime-control failed: {resp.status_code} {resp.text[:200]}")

    status_payload = {"running": None}
    try:
        status_resp = http_client.get(status_url, timeout=5)
        if status_resp.ok:
            status_payload = status_resp.json() or status_payload
    except Exception:
        pass

    result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    result.update({"status": status_payload})
    return result


def _get_ai_webcam_runtime_status() -> dict:
    import requests as http_client

    ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080").rstrip("/")
    status_url = f"{ai_base}/api/v1/cameras/cam_live/runtime-status"
    resp = http_client.get(status_url, timeout=5)
    if resp.status_code >= 400:
        raise RuntimeError(f"AI runtime-status failed: {resp.status_code} {resp.text[:200]}")
    payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    return payload or {"running": None}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def ai_webcam_state(request):
    """
    GET  /api/ai/webcam-state/ — persisted + runtime webcam state for cam_live.
    POST /api/ai/webcam-state/ — update persisted webcam state and apply runtime toggle.
    """
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()

    runtime_setting, _ = TenantRuntimeSetting.objects.get_or_create(tenant=tenant)

    if request.method == "POST":
        assert_role_in(request, tenant, allowed_roles={"owner", "admin"})
        if "enabled" not in request.data:
            return Response({"error": "enabled is required"}, status=status.HTTP_400_BAD_REQUEST)

        enabled = _coerce_bool(request.data.get("enabled"), default=False)
        webcam_camera = _ensure_tenant_webcam_camera(tenant, enabled=enabled)
        runtime_setting.webcam_enabled = enabled
        runtime_setting.save(update_fields=["webcam_enabled", "updated_at"])

        try:
            ai_result = _set_ai_webcam_runtime(enabled, tenant=tenant)
            runtime_payload = ai_result.get("status", {}) or {}
            running = runtime_payload.get("running")
            desired_status = (
                Camera.Status.ACTIVE if running else Camera.Status.INACTIVE
            ) if isinstance(running, bool) else (Camera.Status.ACTIVE if enabled else Camera.Status.INACTIVE)
            if webcam_camera.status != desired_status:
                webcam_camera.status = desired_status
                webcam_camera.save(update_fields=["status", "updated_at"])
            return Response({
                "webcam_enabled": runtime_setting.webcam_enabled,
                "runtime": runtime_payload,
                "camera_id": webcam_camera.ai_camera_id,
                "camera_db_id": webcam_camera.id,
                "applied": True,
            })
        except Exception as exc:
            runtime = {"running": None}
            try:
                runtime = _get_ai_webcam_runtime_status()
                if isinstance(runtime.get("running"), bool) and runtime["running"] == enabled:
                    desired_status = Camera.Status.ACTIVE if enabled else Camera.Status.INACTIVE
                    if webcam_camera.status != desired_status:
                        webcam_camera.status = desired_status
                        webcam_camera.save(update_fields=["status", "updated_at"])
                    return Response({
                        "webcam_enabled": runtime_setting.webcam_enabled,
                        "runtime": runtime,
                        "camera_id": webcam_camera.ai_camera_id,
                        "camera_db_id": webcam_camera.id,
                        "applied": True,
                        "warning": str(exc),
                    })
            except Exception:
                pass
            fallback_status = Camera.Status.INACTIVE if not enabled else webcam_camera.status
            if webcam_camera.status != fallback_status:
                webcam_camera.status = fallback_status
                webcam_camera.save(update_fields=["status", "updated_at"])
            return Response({
                "webcam_enabled": runtime_setting.webcam_enabled,
                "runtime": runtime,
                "camera_id": webcam_camera.ai_camera_id,
                "camera_db_id": webcam_camera.id,
                "applied": False,
                "warning": str(exc),
            }, status=status.HTTP_502_BAD_GATEWAY)

    runtime = {"running": None}
    if _bool_from_env(os.getenv("FETCH_AI_RUNTIME_STATUS", "true"), default=True):
        try:
            runtime = _get_ai_webcam_runtime_status()
        except Exception:
            runtime = {"running": None}

    return Response({
        "webcam_enabled": runtime_setting.webcam_enabled,
        "runtime": runtime,
    })


def _ensure_user_alert_backfill(tenant, user, max_incidents=300):
    """Create per-user alerts for recent incidents that have no user-scoped alert yet."""
    incidents = list(
        Incident.objects.filter(tenant=tenant)
        .select_related("camera")
        .order_by("-started_at", "-id")[:max_incidents]
    )
    if not incidents:
        return 0

    incident_ids = [inc.id for inc in incidents]
    existing_alert_incident_ids = set(
        Alert.objects.filter(incident_id__in=incident_ids)
        .filter(
            Q(payload__user_id=str(user.id))
            | Q(payload__user_id__isnull=True)
        )
        .values_list("incident_id", flat=True)
    )

    missing_incidents = [inc for inc in incidents if inc.id not in existing_alert_incident_ids]
    if not missing_incidents:
        return 0

    severity_labels = {1: "Low", 2: "Medium-Low", 3: "Medium", 4: "High", 5: "Critical"}
    profile, _ = Profile.objects.get_or_create(user=user)
    alerts = []
    for incident in missing_incidents:
        if not profile.allows_instant_notification(incident.severity):
            continue
        severity_level = severity_level_for_value(incident.severity)
        alerts.append(Alert(
            incident=incident,
            channel="websocket",
            payload={
                "title": f"🚨 {incident.get_type_display()} Detected",
                "message": f"{severity_labels.get(incident.severity, 'Unknown')} severity incident at {incident.camera.name if incident.camera else 'Unknown camera'}",
                "data": {
                    "incident_id": incident.id,
                    "type": incident.type,
                    "status": incident.status,
                    "severity": incident.severity,
                    "severity_level": severity_level,
                    "camera_id": incident.camera_id,
                    "camera_name": incident.camera.name if incident.camera else None,
                    "started_at": incident.started_at.isoformat() if incident.started_at else None,
                    "details": incident.details,
                },
                "severity": incident.severity,
                "severity_level": severity_level,
                "user_id": str(user.id),
                "username": user.username,
                "backfilled": True,
            }
        ))

    Alert.objects.bulk_create(alerts)
    return len(alerts)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §5  REAL-TIME NOTIFICATION API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notifications_list(request):
    """
    GET /api/notifications/ — List notifications for current user.
    
    Query params:
    - limit: Max notifications to return (default 50, max 100)
    - offset: Pagination offset
    - unread_only: If 'true', only return unread notifications
    """
    from django.db.models import Count, Q
    
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()

    _ensure_user_alert_backfill(tenant, request.user)
    
    limit = min(int(request.query_params.get("limit", 50)), 100)
    offset = int(request.query_params.get("offset", 0))
    unread_only = request.query_params.get("unread_only", "false").lower() == "true"
    
    # Get incidents for this tenant
    incidents_qs = Incident.objects.filter(tenant=tenant)
    
    # Get alerts for these incidents
    alerts_qs = Alert.objects.filter(
        incident__in=incidents_qs,
    ).filter(
        Q(payload__user_id=str(request.user.id))
        | Q(payload__user_id__isnull=True)
    ).select_related("incident", "incident__camera").order_by("-created_at")
    
    if unread_only:
        alerts_qs = alerts_qs.filter(delivered_at__isnull=True)
    
    total_count = alerts_qs.count()
    alerts = list(alerts_qs[offset:offset + limit])
    
    notifications = []
    for alert in alerts:
        payload = alert.payload or {}
        notifications.append({
            "id": alert.id,
            "type": "incident",
            "title": payload.get("title", f"Incident #{alert.incident_id}"),
            "message": payload.get("message", ""),
            "data": payload.get("data", {}),
            "is_read": alert.delivered_at is not None,
            "created_at": alert.created_at.isoformat(),
            "incident_id": alert.incident_id,
            "incident_type": alert.incident.get_type_display() if alert.incident else None,
            "severity": payload.get("severity", alert.incident.severity if alert.incident else None),
            "severity_level": payload.get("severity_level") or payload.get("data", {}).get("severity_level") or (severity_level_for_value(alert.incident.severity) if alert.incident else None),
            "camera_name": alert.incident.camera.name if alert.incident and alert.incident.camera else None,
            "alert_id": alert.id,
        })
    
    return Response({
        "notifications": notifications,
        "total": total_count,
        "limit": limit,
        "offset": offset,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_mark_read(request):
    """
    POST /api/notifications/mark-read/ — Mark notifications as read.
    
    Body: { "notification_ids": [1, 2, 3] } or { "mark_all": true }
    """
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    
    notification_ids = request.data.get("notification_ids", [])
    mark_all = request.data.get("mark_all", False)
    
    if mark_all:
        # Mark all unread notifications for this tenant as read
        incidents_qs = Incident.objects.filter(tenant=tenant)
        updated = Alert.objects.filter(
            incident__in=incidents_qs,
            ).filter(
            Q(payload__user_id=str(request.user.id))
            | Q(payload__user_id__isnull=True)
        ).filter(
            delivered_at__isnull=True
        ).update(delivered_at=timezone.now())
    elif notification_ids:
        # Mark specific notifications as read
        incidents_qs = Incident.objects.filter(tenant=tenant)
        updated = Alert.objects.filter(
            id__in=notification_ids,
            incident__in=incidents_qs,
            ).filter(
            Q(payload__user_id=str(request.user.id))
            | Q(payload__user_id__isnull=True)
        ).update(delivered_at=timezone.now())
    else:
        return Response({"error": "Provide notification_ids or mark_all=true"}, status=status.HTTP_400_BAD_REQUEST)
    
    return Response({
        "marked_read": updated,
        "success": True,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notifications_unread_count(request):
    """
    GET /api/notifications/unread-count/ — Get unread notification count.
    """
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    
    incidents_qs = Incident.objects.filter(tenant=tenant)
    count = Alert.objects.filter(
        incident__in=incidents_qs,
    ).filter(
        Q(payload__user_id=str(request.user.id))
        | Q(payload__user_id__isnull=True)
    ).filter(
        delivered_at__isnull=True
    ).count()
    
    return Response({"unread_count": count})


def _notification_transport_snapshot() -> dict:
    channel_cfg = settings.CHANNEL_LAYERS.get("default", {}) if hasattr(settings, "CHANNEL_LAYERS") else {}
    backend_path = str(channel_cfg.get("BACKEND", ""))
    uses_redis = "channels_redis" in backend_path
    redis_settings = resolve_backend_redis_settings()

    redis_reachable = False
    redis_error = None
    subscriber_status = None

    try:
        client = create_redis_client(redis_settings)
        client.ping()
        redis_reachable = True
        subscriber_status = read_subscriber_status(client, redis_settings.incident_channel)
        client.close()
    except Exception as exc:
        redis_error = str(exc)

    return {
        "channel_backend": backend_path,
        "uses_redis": uses_redis,
        "realtime_ready": bool(uses_redis and redis_reachable),
        "queue_mode": redis_settings.queue_mode,
        "incident_stream": redis_settings.incident_channel,
        "incident_channel": redis_settings.incident_channel,
        "incident_consumer_group": redis_settings.incident_consumer_group,
        "incident_consumer_name": redis_settings.incident_consumer_name,
        "redis": redis_settings.to_diagnostics(),
        "redis_reachable": redis_reachable,
        "redis_error": redis_error,
        "subscriber": subscriber_status,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notifications_transport_status(request):
    """
    GET /api/notifications/transport-status/ — report notification transport health.

    The status is Redis-based: green when Redis is reachable, red otherwise.
    """
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()

    return Response(_notification_transport_snapshot())


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_broadcast(request):
    """
    POST /api/notifications/broadcast/ — Send a broadcast message to all tenant members.
    Requires owner or admin role.
    """
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    
    assert_role_in(request, tenant, allowed_roles={"owner", "admin"})
    
    title = request.data.get("title", "").strip()
    message = request.data.get("message", "").strip()
    notification_type = request.data.get("type", "broadcast")
    
    if not title or not message:
        return Response({"error": "title and message are required"}, status=status.HTTP_400_BAD_REQUEST)
    
    result = NotificationService.broadcast_message(
        tenant_id=tenant.id,
        title=title,
        message=message,
        notification_type=notification_type,
        data=request.data.get("data", {})
    )
    
    return Response({
        "success": True,
        "result": result,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_test_websocket(request):
    """
    POST /api/notifications/test-websocket/ — Send a test WebSocket notification.
    Useful for testing real-time notifications are working.
    """
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    assert_role_in(request, tenant, allowed_roles={"owner", "admin"})
    
    result = NotificationService.broadcast_message(
        tenant_id=tenant.id,
        title="🔔 Test Notification",
        message="This is a test notification to verify WebSocket connectivity.",
        notification_type="test",
        data={
            "test": True,
            "user_id": request.user.id,
            "username": request.user.username,
        }
    )
    
    return Response({
        "success": True,
        "result": result,
        "message": "Test notification sent to all connected clients"
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_test_incident(request):
    """
    POST /api/notifications/test-incident/ — append a synthetic incident to Redis Streams.
    This exercises the canonical AI -> Redis stream -> subscriber -> websocket path.
    """
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    assert_role_in(request, tenant, allowed_roles={"owner", "admin"})

    camera_token = str(request.data.get("camera_id", "")).strip()
    camera = None
    if camera_token:
        camera = (
            Camera.objects.filter(tenant=tenant)
            .filter(
                Q(ai_camera_id=camera_token)
                | Q(stream_path=camera_token)
                | Q(name=camera_token)
            )
            .first()
        )
        if camera is None and camera_token.isdigit():
            camera = Camera.objects.filter(pk=int(camera_token), tenant=tenant).first()
    if camera is None:
        camera = (
            Camera.objects.filter(tenant=tenant, status=Camera.Status.ACTIVE)
            .order_by("id")
            .first()
            or Camera.objects.filter(tenant=tenant).order_by("id").first()
        )
    if camera is None:
        return Response(
            {"error": "No camera available for this tenant"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    incident_type = str(request.data.get("type", "intrusion")).strip() or "intrusion"
    try:
        severity = max(1, min(5, int(request.data.get("severity", 4))))
    except (TypeError, ValueError):
        severity = 4

    event = build_test_incident_event(
        camera_id=camera.ai_camera_id or camera.stream_path or camera.name,
        tenant_id=tenant.id,
        incident_type=incident_type,
        severity=severity,
    )
    redis_settings = resolve_backend_redis_settings()

    try:
        client = create_redis_client(redis_settings)
        client.ping()
        stream_entry_id = append_incident_event(client, redis_settings.incident_channel, event)
        current_stream_length = stream_length(client, redis_settings.incident_channel)
        subscriber_status = read_subscriber_status(client, redis_settings.incident_channel)
        client.close()
    except Exception as exc:
        return Response(
            {
                "success": False,
                "error": str(exc),
                "redis": redis_settings.to_diagnostics(),
                "incident_stream": redis_settings.incident_channel,
                "incident_channel": redis_settings.incident_channel,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response({
        "success": True,
        "queued": True,
        "event_id": event["data"]["id"],
        "stream_entry_id": stream_entry_id,
        "stream_length": current_stream_length,
        "camera_id": event["data"]["camera_id"],
        "incident_stream": redis_settings.incident_channel,
        "incident_channel": redis_settings.incident_channel,
        "redis": redis_settings.to_diagnostics(),
        "subscriber": subscriber_status,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §7  DEBUG SYSTEM ENDPOINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_DJANGO_START = timezone.now()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def debug_system(request):
    """GET /api/debug/system/ — aggregated system diagnostics with AI fallbacks."""
    import requests as http_client

    # Try multiple AI base URLs in order
    ai_base_env = os.getenv("AI_BASE_INTERNAL", "")
    ai_candidates = [
        url for url in [
            ai_base_env,
            "http://ai:8080",
            "http://127.0.0.1:8080",
            "http://localhost:8080",
        ] if url
    ]
    # Deduplicate while preserving order
    seen = set()
    ai_urls = []
    for u in ai_candidates:
        u = u.rstrip("/")
        if u not in seen:
            seen.add(u)
            ai_urls.append(u)

    # Django info
    django_uptime = (timezone.now() - _DJANGO_START).total_seconds()
    db_ok = False
    try:
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        db_ok = True
    except Exception:
        pass

    # AI info — try each URL until one works
    ai_reachable = False
    ai_error = None
    ai_base_used = None
    ai_status = None
    ai_cameras = None

    for base_url in ai_urls:
        try:
            r = http_client.get(f"{base_url}/api/v1/health", timeout=3)
            if r.status_code == 200:
                ai_reachable = True
                ai_base_used = base_url
                break
        except Exception:
            continue

    if ai_reachable and ai_base_used:
        try:
            r = http_client.get(f"{ai_base_used}/api/v1/system/status", timeout=5)
            if r.status_code == 200:
                ai_status = r.json()
        except Exception as exc:
            ai_error = f"status fetch failed: {exc}"
        try:
            r = http_client.get(f"{ai_base_used}/api/v1/cameras", timeout=5)
            if r.status_code == 200:
                ai_cameras = r.json()
        except Exception:
            pass
    else:
        ai_error = f"AI unreachable at all candidates: {ai_urls}"

    # Fallback camera data from Django DB
    django_cameras = None
    if not ai_cameras:
        tenant = get_active_tenant(request, required=False)
        if tenant:
            django_cameras = list(
                Camera.objects.filter(tenant=tenant).values(
                    "id", "name", "status", "ai_camera_id", "stream_path"
                )
            )

    return Response({
        "django": {
            "uptime_seconds": round(django_uptime),
            "db_ok": db_ok,
            "debug_mode": os.getenv("DJANGO_DEBUG", "1") == "1",
        },
        "notifications": _notification_transport_snapshot(),
        "ai": ai_status,
        "ai_cameras": ai_cameras,
        "ai_reachable": ai_reachable,
        "ai_error": ai_error,
        "ai_base_used": ai_base_used,
        "ai_urls_tried": ai_urls,
        "django_cameras": django_cameras,
    })
