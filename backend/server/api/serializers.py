from rest_framework import serializers
from .models import Tenant, Membership, Camera, Incident, Detection, Alert, AuditLog, Profile, Invitation
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

class CameraAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Camera
        fields = "__all__"

class IncidentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Incident
        fields = "__all__"

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

    class Meta:
        model = Profile
        fields = ["id", "user", "bio"]
        read_only_fields = ["id", "user"]

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
