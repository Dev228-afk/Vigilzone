import os
import logging
from rest_framework import viewsets, permissions, status
from rest_framework.exceptions import PermissionDenied, NotAuthenticated
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from .models import (
    Tenant, Membership, Camera, CameraZone, Incident, Detection,
    Alert, AuditLog, Profile, Invitation, KnownEntity, NotificationChannel,
)
from .serializers import (
    TenantSerializer, MyTenantSerializer, MembershipSerializer,
    CameraSafeSerializer, CameraAdminSerializer, CameraWriteSerializer,
    CameraStreamSerializer,
    IncidentSerializer, DetectionSerializer, AlertSerializer, AuditLogSerializer,
    ProfileSerializer, InvitationCreateSerializer, PendingInvitationSerializer,
    KnownEntitySerializer, CameraZoneSerializer, NotificationChannelSerializer,
)

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
        camera = self.get_object()
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")

        payload = {
            "camera_id": camera.ai_camera_id or f"cam_{camera.pk}",
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

class IncidentViewSet(TenantScopedViewSet):
    queryset = Incident.objects.select_related("camera").all()
    serializer_class = IncidentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset().order_by("-started_at")
        status_filter = self.request.query_params.get("status")
        type_filter = self.request.query_params.get("type")
        if status_filter:
            qs = qs.filter(status=status_filter)
        if type_filter:
            qs = qs.filter(type=type_filter)
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
                    entity.thumbnail_url = f"/api/ai{saved_urls[0]}"
                elif ai_data.get("thumbnail"):
                    entity.thumbnail_url = ai_data["thumbnail"]
                entity.save(update_fields=["ai_entity_id", "thumbnail_url", "updated_at"])
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("AI enrollment failed: %s", exc)
            # Entity is saved locally even if AI is down

        headers = self.get_success_headers(serializer.data)
        result = self.get_serializer(entity).data
        # Include AI enrollment details for the frontend
        result["ai_enrollment"] = {
            "embeddings_stored": ai_data.get("embeddings_stored", 0),
            "saved_images_count": ai_data.get("saved_images_count", 0),
            "failed_images": ai_data.get("failed_images", []),
        }
        return Response(result, status=status.HTTP_201_CREATED, headers=headers)

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
# §B  STREAM ENDPOINTS (WebRTC/HLS URLs)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def streams_list(request):
    """GET /api/streams/ — list cameras with derived WebRTC/HLS URLs."""
    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    cameras = Camera.objects.filter(tenant=tenant).order_by("name")
    return Response(CameraStreamSerializer(cameras, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def streams_detail(request, camera_id):
    """GET /api/streams/<camera_id>/ — single camera stream URLs."""
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
def streams_snapshot(request, camera_id):
    """GET /api/streams/<camera_id>/snapshot/ — grab a still frame via FFmpeg from RTSP."""
    import subprocess
    import tempfile
    import time as _time

    tenant = get_active_tenant(request)
    if not assert_member(request, tenant):
        raise PermissionDenied()
    try:
        camera = Camera.objects.get(pk=camera_id, tenant=tenant)
    except Camera.DoesNotExist:
        return Response({"error": "Camera not found"}, status=status.HTTP_404_NOT_FOUND)

    # Determine RTSP source
    stream_path = camera.stream_path or camera.ai_camera_id or f"cam_{camera.pk}"
    rtsp_url = camera.rtsp_url or f"rtsp://mediamtx:8554/{stream_path}"

    # Simple cache: store last snapshot per camera in memory
    cache_key = f"_snapshot_{camera.pk}"
    cached = getattr(streams_snapshot, '_cache', {}).get(cache_key)
    now = _time.time()
    if cached and (now - cached['ts']) < 3.0:
        from django.http import HttpResponse
        return HttpResponse(cached['data'], content_type='image/jpeg')

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-rtsp_transport", "tcp",
                "-i", rtsp_url,
                "-frames:v", "1",
                "-q:v", "5",
                "-f", "image2", "-vcodec", "mjpeg",
                "pipe:1",
            ],
            capture_output=True, timeout=8,
        )
        if result.returncode != 0 or not result.stdout:
            return Response({"error": "Failed to capture frame"}, status=status.HTTP_502_BAD_GATEWAY)

        # Cache it
        if not hasattr(streams_snapshot, '_cache'):
            streams_snapshot._cache = {}
        streams_snapshot._cache[cache_key] = {'ts': now, 'data': result.stdout}

        from django.http import HttpResponse
        resp = HttpResponse(result.stdout, content_type='image/jpeg')
        resp['Cache-Control'] = 'no-store'
        return resp
    except FileNotFoundError:
        return Response({"error": "ffmpeg not installed on backend"}, status=status.HTTP_501_NOT_IMPLEMENTED)
    except subprocess.TimeoutExpired:
        return Response({"error": "RTSP snapshot timed out"}, status=status.HTTP_504_GATEWAY_TIMEOUT)
    except Exception as exc:
        return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
    """Fire email/push for an incident that meets severity threshold.
    Called from webhook receiver after incident create/escalate."""
    from django.core.mail import send_mail as django_send_mail

    try:
        channel = NotificationChannel.objects.get(tenant=incident.tenant)
    except NotificationChannel.DoesNotExist:
        return
    if incident.severity < channel.min_severity_int():
        return

    subject = f"[VigilZone] {incident.get_type_display()} — Severity {incident.severity}"
    body = (
        f"Incident #{incident.pk}\n"
        f"Type: {incident.get_type_display()}\n"
        f"Camera: {incident.camera.name}\n"
        f"Severity: {incident.severity}/5\n"
        f"Time: {incident.started_at}\n"
        f"Details: {incident.details.get('message', '')}"
    )
    # Email
    if channel.email_enabled and channel.email_recipients:
        try:
            django_send_mail(
                subject=subject,
                message=body,
                from_email=None,
                recipient_list=channel.email_recipients,
            )
        except Exception as exc:
            logger.warning("Notification email failed: %s", exc)

    # TODO: FCM push when service account configured


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