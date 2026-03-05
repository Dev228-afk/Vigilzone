from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    bio = models.TextField(blank=True)
    # Additional profile fields can be added here as needed

    def __str__(self):
        return f"Profile for {self.user.username}"

class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True

class Tenant(TimeStamped):
    name = models.CharField(max_length=200, unique=True)
    plan = models.CharField(max_length=50, default="free")

    def __str__(self):
        return self.name

class Membership(TimeStamped):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"
        VIEWER = "viewer", "Viewer"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    class Meta:
        unique_together = [("tenant", "user")]
    
    def __str__(self):
        return f"{self.user.username} @ {self.tenant.name} ({self.role})"

class Camera(TimeStamped):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cameras")
    name = models.CharField(max_length=200)
    site = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    rtsp_url = models.CharField(max_length=512, blank=True)  # don’t return this to clients

class Incident(TimeStamped):
    class Type(models.TextChoices):
        ROBBERY = "robbery", "Robbery"
        STRANGER = "stranger", "Stranger"
        FIRE = "fire", "Fire"
        INTRUSION = "intrusion", "Intrusion"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACK = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="incidents")
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="incidents")
    type = models.CharField(max_length=24, choices=Type.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    severity = models.IntegerField(default=1)  # 1..5
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)       # extra info
    media_key = models.CharField(max_length=512, blank=True)   # S3/MinIO key or path

class Detection(TimeStamped):
    """
    Lightweight per-interval summary (e.g., 1s/5s) of model output.
    Use JSONField for flexibility during dev (SQLite ok). Partition later in Postgres.
    """
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="detections")
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="detections")
    ts = models.DateTimeField(db_index=True)
    payload = models.JSONField(default=dict)  # boxes, scores, classes, counts, etc.

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "camera", "ts"]),
        ]

class Alert(TimeStamped):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="alerts")
    channel = models.CharField(max_length=32, default="email")   # email|webhook|sms|push
    payload = models.JSONField(default=dict, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

class AuditLog(TimeStamped):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="audit_logs")
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=64)       # e.g., incident.update_status
    target_type = models.CharField(max_length=64)  # e.g., incident, camera
    target_id = models.CharField(max_length=64, blank=True)
    meta = models.JSONField(default=dict, blank=True)

import secrets
from django.utils import timezone
from datetime import timedelta

class Invitation(TimeStamped):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Membership.Role.choices, default=Membership.Role.MEMBER)

    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="sent_invitations")
    token = models.CharField(max_length=64, unique=True, default="", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    expires_at = models.DateTimeField()

    accepted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="accepted_invitations")
    accepted_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    def is_valid(self):
        return self.status == self.Status.PENDING and timezone.now() < self.expires_at

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "email"],
                condition=models.Q(status="pending", expires_at__gt=timezone.now()),
                name="unique_pending_invitation_per_tenant_email"
            ),
        ]
        indexes = [
            models.Index(fields=["email", "status"]),
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self):
        return f"Invite {self.email} -> {self.tenant.name} ({self.role}) [{self.status}]"