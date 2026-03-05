from rest_framework import viewsets, permissions, status
from rest_framework.exceptions import PermissionDenied, NotAuthenticated
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from .models import Tenant, Membership, Camera, Incident, Detection, Alert, AuditLog, Profile, Invitation
from .serializers import (
    TenantSerializer, MyTenantSerializer, MembershipSerializer, CameraSafeSerializer, CameraAdminSerializer,
    IncidentSerializer, DetectionSerializer, AlertSerializer, AuditLogSerializer, ProfileSerializer, InvitationCreateSerializer, PendingInvitationSerializer
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
        # Use admin serializer only for staff; otherwise hide rtsp_url
        return CameraAdminSerializer if (self.request.user and self.request.user.is_staff) else CameraSafeSerializer

class IncidentViewSet(TenantScopedViewSet):
    queryset = Incident.objects.all()
    serializer_class = IncidentSerializer
    permission_classes = [permissions.IsAuthenticated]

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