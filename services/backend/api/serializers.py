from rest_framework import serializers
from django.utils.text import slugify
from .models import (
    Tenant, Membership, Camera, CameraZone, Incident, Detection,
    Alert, AuditLog, Profile, Invitation, KnownEntity, NotificationChannel,
)
from django.contrib.auth.models import User

class TenantSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = ["id", "name", "plan", "role", "created_at", "updated_at"]

    def get_role(self, obj):
        user = self.context["request"].user
        memberships = Membership.objects.filter(tenant=obj)
        if memberships.exists():
            membership = memberships.first()
            return membership.role
        return None

class MyTenantSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    role = serializers.CharField()
    
    def to_representation(self, instance):
        return {
            "id": instance.tenant.id,
            "name": instance.tenant.name,
            "role": instance.role,
        }

class MemberUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]

class MembershipSerializer(serializers.ModelSerializer):
    user = MemberUserSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "tenant", "user", "role", "created_at", "updated_at"]
        read_only_fields = ["id", "tenant", "created_at", "updated_at"]

    def to_representation(self, instance):
        print("USING NESTED MEMBERSHIP SERIALIZER")
        return super().to_representation(instance)
class CameraSafeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Camera
        exclude = ("rtsp_url",)  # don't leak RTSP in public responses


class CameraStreamSerializer(serializers.ModelSerializer):
    """Read-only serializer that exposes stream URLs derived from stream_path."""
    webrtc_url = serializers.SerializerMethodField()
    whep_url = serializers.SerializerMethodField()
    hls_url = serializers.SerializerMethodField()

    class Meta:
        model = Camera
        fields = ["id", "name", "site", "status", "ai_camera_id", "stream_path",
                  "camera_type", "webrtc_url", "whep_url", "hls_url"]

    def _stream_path(self, obj):
        return obj.stream_path or obj.ai_camera_id or f"cam_{obj.pk}"

    def get_webrtc_url(self, obj):
        p = self._stream_path(obj)
        return f"/webrtc/{p}" if p else None

    def get_whep_url(self, obj):
        p = self._stream_path(obj)
        return f"/webrtc/{p}/whep" if p else None

    def get_hls_url(self, obj):
        p = self._stream_path(obj)
        return f"/hls/{p}" if p else None

class CameraAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Camera
        fields = "__all__"

class CameraWriteSerializer(serializers.ModelSerializer):
    """
    Accepts both canonical fields AND legacy aliases from the UI:
      location  -> site
      streamUrl -> rtsp_url
      status "offline" -> "inactive"
    rtsp_url is write_only (never leaked in responses).
    """
    # Legacy aliases (write-only, optional)
    location = serializers.CharField(required=False, write_only=True)
    streamUrl = serializers.CharField(required=False, write_only=True)

    class Meta:
        model = Camera
        fields = [
            "id", "name", "site", "rtsp_url", "ai_camera_id", "stream_path", "status",
            "camera_type", "min_confidence", "min_bbox_area",
            "k_of_n_k", "k_of_n_n", "cooldown_s",
            "created_at", "updated_at", "tenant",
            # legacy aliases
            "location", "streamUrl",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "tenant"]
        extra_kwargs = {
            "rtsp_url": {"write_only": True, "required": False},
            "site": {"required": False},
            "ai_camera_id": {"required": False},
            "status": {"required": False},
        }

    def validate_status(self, value):
        mapping = {"offline": "inactive", "online": "active"}
        return mapping.get(value, value)

    def validate(self, attrs):
        # Merge legacy aliases into canonical fields
        if "location" in attrs and not attrs.get("site"):
            attrs["site"] = attrs.pop("location")
        else:
            attrs.pop("location", None)
        if "streamUrl" in attrs and not attrs.get("rtsp_url"):
            attrs["rtsp_url"] = attrs.pop("streamUrl")
        else:
            attrs.pop("streamUrl", None)

        # ── Auto-derive stream_path when empty ──────────────────────
        if not attrs.get("stream_path"):
            # Prefer ai_camera_id, then slugified name, then leave for
            # model.save() to handle with cam_{pk} fallback
            if attrs.get("ai_camera_id"):
                attrs["stream_path"] = attrs["ai_camera_id"]
            elif attrs.get("name"):
                attrs["stream_path"] = slugify(attrs["name"])

        return attrs

    def to_representation(self, instance):
        """Use CameraSafeSerializer for read (hides rtsp_url)."""
        return CameraSafeSerializer(instance).data

class IncidentSerializer(serializers.ModelSerializer):
    camera_name = serializers.CharField(source="camera.name", read_only=True, default="")

    class Meta:
        model = Incident
        fields = "__all__"
        extra_fields = ["camera_name"]

    def get_field_names(self, declared_fields, info):
        fields = super().get_field_names(declared_fields, info)
        if "camera_name" not in fields:
            fields = list(fields) + ["camera_name"]
        return fields

class DetectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Detection
        fields = "__all__"

class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = "__all__"

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = "__all__"

class ProfileSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = Profile
        fields = [
            "id", "user", "username", "email", "bio",
            "notify_email", "notify_push", "notify_sms",
            "alert_sensitivity", "data_retention_days", "audio_detection",
            "blur_faces", "consent_required",
        ]
        read_only_fields = ["id", "user", "username", "email"]

class KnownEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = KnownEntity
        fields = [
            "id", "name", "category", "group", "notes",
            "ai_entity_id", "thumbnail_url", "last_seen",
            "created_at", "updated_at", "tenant",
        ]
        read_only_fields = ["id", "ai_entity_id", "thumbnail_url", "last_seen", "created_at", "updated_at", "tenant"]


class InvitationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = ["id", "email", "role"]

    def validate_role(self, value):
        valid = {c[0] for c in Membership.Role.choices}
        if value not in valid:
            raise serializers.ValidationError("Invalid role.")
        return value


class PendingInvitationSerializer(serializers.ModelSerializer):
    tenant = serializers.SerializerMethodField()
    invited_by = serializers.SerializerMethodField()
    email = serializers.EmailField(read_only=True)

    class Meta:
        model = Invitation
        fields = ["id", "tenant", "email", "role", "invited_by", "expires_at"]

    def get_tenant(self, obj):
        return {"id": obj.tenant.id, "name": obj.tenant.name}

    def get_invited_by(self, obj):
        return obj.invited_by.username if obj.invited_by else None


class CameraZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = CameraZone
        fields = ["id", "camera", "zone_name", "zone_type", "polygon_points", "enabled", "created_at", "updated_at"]
        read_only_fields = ["id", "camera", "created_at", "updated_at"]


class NotificationChannelSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationChannel
        fields = [
            "id", "email_enabled", "push_enabled",
            "email_recipients", "fcm_tokens", "severity_threshold",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
