import os
import logging
import hashlib
import hmac
import time
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
from .models import (
    Tenant, Membership, Camera, CameraZone, Incident, Detection,
    Alert, AuditLog, Profile, Invitation, KnownEntity, NotificationChannel,
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
        if not assert_member(self.request, tenant):
            raise PermissionDenied("Not a member of this tenant.")
        serializer.save(**{self.tenant_field: tenant})

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
            proc = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-rtsp_transport", "tcp",
                    "-rw_timeout", str(timeout_s * 1_000_000),
                    "-show_streams", "-select_streams", "v:0",
                    "-print_format", "json",
                    rtsp_url,
                ],
                capture_output=True, timeout=timeout_s + 2,
            )
            latency = int((_time.monotonic() - t0) * 1000)
            if proc.returncode == 0 and proc.stdout:
                try:
                    info = _json.loads(proc.stdout)
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
            result["error"] = (proc.stderr or b"").decode(errors="replace").strip()[:300]
        except subprocess.TimeoutExpired:
            result["error"] = f"ffprobe timed out ({timeout_s}s)"
            result["latency_ms"] = timeout_s * 1000
            return result
        except FileNotFoundError:
            pass  # fall through to ffmpeg

    # ── Fallback: ffmpeg single-frame grab ────────────────────
    t0 = _time.monotonic()
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-rtsp_transport", "tcp",
                "-rw_timeout", str(timeout_s * 1_000_000),
                "-i", rtsp_url,
                "-frames:v", "1",
                "-f", "null", "-",
            ],
            capture_output=True, timeout=timeout_s + 2,
        )
        latency = int((_time.monotonic() - t0) * 1000)
        if proc.returncode == 0:
            return {"ok": True, "method": "ffmpeg", "latency_ms": latency}
        result["method"] = "ffmpeg"
        result["latency_ms"] = latency
        result["error"] = (proc.stderr or b"").decode(errors="replace").strip()[:300]
    except FileNotFoundError:
        result["error"] = "Neither ffprobe nor ffmpeg found on PATH"
    except subprocess.TimeoutExpired:
        result["error"] = f"ffmpeg timed out ({timeout_s}s)"
        result["latency_ms"] = timeout_s * 1000

    return result


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

    @action(detail=True, methods=["post"], url_path="sync_to_ai")
    def sync_to_ai(self, request, pk=None):
        """POST /api/cameras/{id}/sync_to_ai/ — register camera with AI module."""
        import requests as http_client
        import re
        from django.utils.text import slugify
        camera = self.get_object()
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")

        # Prefer stable IDs that match what the UI/streams use.
        # Avoid the old fallback cam_<pk> unless absolutely necessary.
        def _default_camera_id() -> str:
            if camera.ai_camera_id and not re.match(r"^cam_\d+$", camera.ai_camera_id):
                return camera.ai_camera_id
            if camera.stream_path:
                return camera.stream_path
            if camera.name:
                return slugify(camera.name)
            return f"cam_{camera.pk}"

        payload = {
            "camera_id": _default_camera_id(),
            "rtsp_url": camera.rtsp_url or "",
            "ingest_backend": "opencv",
            "enabled_lanes": ["rt_detr", "yolov8_fallback", "fire_smoke_yolo", "person_zone"],
            "sample_hz": 2.0,
        }
        # Allow request body to override any field
        for key in ("camera_id", "rtsp_url", "ingest_backend", "enabled_lanes", "sample_hz"):
            if key in request.data:
                payload[key] = request.data[key]

        try:
            resp = http_client.post(
                f"{ai_base}/api/v1/cameras/register",
                json=payload, timeout=15,
            )
            if resp.status_code in (200, 201):
                ai_data = resp.json()
                camera.ai_camera_id = ai_data.get("camera_id", payload["camera_id"])
                camera.status = Camera.Status.ACTIVE
                # Ensure stream_path is populated (auto-derive triggers on save)
                update_fields = ["ai_camera_id", "status", "updated_at"]
                if not camera.stream_path:
                    camera.stream_path = camera.ai_camera_id
                    update_fields.append("stream_path")
                camera.save(update_fields=update_fields)
                return Response({
                    "status": "synced",
                    "ai_camera_id": camera.ai_camera_id,
                    "stream_path": camera.stream_path,
                    "hot_loaded": ai_data.get("hot_loaded", False),
                })
            else:
                camera.status = Camera.Status.INACTIVE
                camera.save(update_fields=["status", "updated_at"])
                return Response(
                    {"error": f"AI returned {resp.status_code}", "detail": resp.text[:500]},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
        except http_client.ConnectionError:
            return Response({"error": "AI service unavailable"}, status=status.HTTP_502_BAD_GATEWAY)
        except http_client.Timeout:
            return Response({"error": "AI service timeout"}, status=status.HTTP_504_GATEWAY_TIMEOUT)

    # ── Zone CRUD ────────────────────────────────────────────
    @action(detail=True, methods=["get", "post"], url_path="zones")
    def zones(self, request, pk=None):
        """GET/POST /api/cameras/{id}/zones/"""
        camera = self.get_object()
        if request.method == "GET":
            qs = CameraZone.objects.filter(camera=camera).order_by("zone_name")
            return Response(CameraZoneSerializer(qs, many=True).data)
        # POST — create new zone
        ser = CameraZoneSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save(camera=camera)
        return Response(ser.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["put", "delete"], url_path=r"zones/(?P<zone_id>\d+)")
    def zone_detail(self, request, pk=None, zone_id=None):
        """PUT/DELETE /api/cameras/{id}/zones/{zone_id}/"""
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
                json=zones_payload, timeout=10,
            )
            return Response({"status": "synced", "ai_status": resp.status_code, "zones_sent": len(zones_payload)})
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=["post"], url_path="sync_ai_settings")
    def sync_ai_settings(self, request, pk=None):
        """POST /api/cameras/{id}/sync_ai_settings/ — push per-camera thresholds to AI."""
        import requests as http_client
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
                json=payload, timeout=10,
            )
            return Response({"status": "synced", "ai_status": resp.status_code})
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    # ── Test connection (existing camera) ───────────────────
    @action(detail=True, methods=["post"], url_path="test_connection")
    def test_connection_detail(self, request, pk=None):
        """POST /api/cameras/{id}/test_connection/ — test stored RTSP URL."""
        camera = self.get_object()
        rtsp_url = camera.rtsp_url
        if not rtsp_url:
            return Response({"ok": False, "error": "No RTSP URL stored for this camera"}, status=status.HTTP_400_BAD_REQUEST)
        timeout_s = min(int(request.data.get("timeout_s", 3)), 10)
        return Response(_probe_rtsp(rtsp_url, timeout_s))

    # ── Test connection (unsaved URL) ───────────────────────
    @action(detail=False, methods=["post"], url_path="test_connection")
    def test_connection_list(self, request):
        """POST /api/cameras/test_connection/ — test an arbitrary RTSP URL."""
        rtsp_url = request.data.get("rtsp_url", "").strip()
        if not rtsp_url:
            return Response({"ok": False, "error": "rtsp_url is required"}, status=status.HTTP_400_BAD_REQUEST)
        timeout_s = min(int(request.data.get("timeout_s", 3)), 10)
        return Response(_probe_rtsp(rtsp_url, timeout_s))

class IncidentViewSet(TenantScopedViewSet):
    queryset = Incident.objects.select_related("camera").all()
    serializer_class = IncidentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        """Create incident. Notifications are sent automatically via Django signal."""
        tenant = get_active_tenant(self.request)
        if not assert_member(self.request, tenant):
            raise PermissionDenied("Not a member of this tenant.")
        
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
        incident = self.get_object()
        if incident.status == "resolved":
            return Response({"error": "Incident already resolved"}, status=status.HTTP_400_BAD_REQUEST)
        incident.status = "acknowledged"
        incident.save(update_fields=["status", "updated_at"])
        # Audit
        tenant = get_active_tenant(request)
        AuditLog.objects.create(
            tenant=tenant, actor=request.user,
            action="incident.acknowledge", target_type="incident", target_id=str(incident.pk),
        )
        return Response(IncidentSerializer(incident).data)

    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve(self, request, pk=None):
        incident = self.get_object()
        incident.status = "resolved"
        incident.ended_at = timezone.now()
        incident.save(update_fields=["status", "ended_at", "updated_at"])
        tenant = get_active_tenant(request)
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

    # Cameras
    cameras = list(Camera.objects.filter(tenant=tenant).values("id", "name", "site", "status", "ai_camera_id"))

    # Incident counts
    stats = {
        "today": incidents.filter(started_at__gte=today_start).count(),
        "week": incidents.filter(started_at__gte=week_start).count(),
        "month": incidents.filter(started_at__gte=month_start).count(),
    }

    # Recent incidents (last 10)
    recent_incidents = list(
        incidents.order_by("-started_at")[:10].values(
            "id", "type", "status", "severity", "started_at",
            "camera__name", "details",
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
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
        resp = http_client.get(f"{ai_base}/api/v1/health", timeout=3)
        ai_healthy = resp.status_code == 200
    except Exception:
        pass

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
        if not assert_member(self.request, tenant):
            raise PermissionDenied("Not a member of this tenant.")
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
                # Build thumbnail URL from first saved image
                saved_urls = ai_data.get("saved_image_urls", [])
                if saved_urls:
                    # IMPORTANT: store a URL that the frontend can fetch through
                    # the Django API base (/api) without double-prefixing.
                    # Frontend axios baseURL is "/api", so we store paths like "/ai/...".
                    # AI returns paths like "/enroll_images/<id>/<file>", which are served
                    # through Django at "/api/ai/enroll_images/...".
                    p = str(saved_urls[0])
                    if p.startswith("/api/"):
                        p = p[4:]  # "/api/ai/..." -> "/ai/..."
                    if p.startswith("/enroll_images/"):
                        p = f"/ai{p}"  # -> "/ai/enroll_images/..."
                    entity.thumbnail_url = p
                elif ai_data.get("thumbnail"):
                    p = str(ai_data["thumbnail"])
                    if p.startswith("/api/"):
                        p = p[4:]
                    if p.startswith("/enroll_images/"):
                        p = f"/ai{p}"
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
    """Signed query token auth for browser <img> compatibility."""
    from django.http import StreamingHttpResponse

    token_param = request.GET.get("token", "")
    ok, _payload = _verify_stream_token(token_param, camera_id) if token_param else (False, {})
    if not ok:
        return Response({"error": "Invalid stream token"}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        camera = Camera.objects.get(pk=camera_id)
    except Camera.DoesNotExist:
        return Response({"error": "Camera not found"}, status=status.HTTP_404_NOT_FOUND)

    cfg = _stream_preview_config()
    STREAM_WORKERS.ensure_running(camera, **cfg)
    STREAM_WORKERS.add_viewer(int(camera.pk))

    resp = StreamingHttpResponse(
        _mjpeg_generator(int(camera.pk), cfg["fps"]),
        content_type="multipart/x-mixed-replace; boundary=frame",
    )
    resp["Cache-Control"] = "no-store"
    resp["X-Accel-Buffering"] = "no"
    return resp


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
    """GET/PUT /api/notifications/settings/ — tenant notification prefs."""
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    channel, _ = NotificationChannel.objects.get_or_create(tenant=tenant)
    if request.method == "GET":
        return Response(NotificationChannelSerializer(channel).data)
    ser = NotificationChannelSerializer(channel, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notification_test(request):
    """POST /api/notifications/test/ — send a test notification."""
    from django.core.mail import send_mail as django_send_mail

    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
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
    
    limit = min(int(request.query_params.get("limit", 50)), 100)
    offset = int(request.query_params.get("offset", 0))
    unread_only = request.query_params.get("unread_only", "false").lower() == "true"
    
    # Get incidents for this tenant
    incidents_qs = Incident.objects.filter(tenant=tenant)
    
    # Get alerts for these incidents
    alerts_qs = Alert.objects.filter(
        incident__in=incidents_qs
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
            "severity": alert.incident.severity if alert.incident else None,
            "camera_name": alert.incident.camera.name if alert.incident and alert.incident.camera else None,
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
            delivered_at__isnull=True
        ).update(delivered_at=timezone.now())
    elif notification_ids:
        # Mark specific notifications as read
        incidents_qs = Incident.objects.filter(tenant=tenant)
        updated = Alert.objects.filter(
            id__in=notification_ids,
            incident__in=incidents_qs,
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
        delivered_at__isnull=True
    ).count()
    
    return Response({"unread_count": count})


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
        "ai": ai_status,
        "ai_cameras": ai_cameras,
        "ai_reachable": ai_reachable,
        "ai_error": ai_error,
        "ai_base_used": ai_base_used,
        "ai_urls_tried": ai_urls,
        "django_cameras": django_cameras,
    })