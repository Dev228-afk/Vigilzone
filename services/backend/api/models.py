from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()


def default_instant_notification_levels():
    return ["critical", "severe", "moderate"]


def severity_level_for_value(severity: int) -> str:
    try:
        sev = int(severity)
    except (TypeError, ValueError):
        sev = 3
    if sev >= 5:
        return "critical"
    if sev >= 4:
        return "severe"
    if sev >= 3:
        return "moderate"
    if sev >= 2:
        return "low"
    return "info"


def normalize_instant_notification_levels(raw_levels) -> list[str]:
    allowed = ["critical", "severe", "moderate", "low", "info"]
    if not isinstance(raw_levels, list):
        return default_instant_notification_levels()
    normalized = []
    for value in raw_levels:
        text = str(value).strip().lower()
        if text in allowed and text not in normalized:
            normalized.append(text)
    return normalized or default_instant_notification_levels()

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    bio = models.TextField(blank=True)
    # Notification preferences
    notify_email = models.BooleanField(default=True)
    notify_push = models.BooleanField(default=True)
    notify_sms = models.BooleanField(default=False)
    instant_notification_levels = models.JSONField(default=default_instant_notification_levels, blank=True)
    # System preferences
    alert_sensitivity = models.CharField(max_length=16, default="medium")  # low|medium|high
    data_retention_days = models.IntegerField(default=60)
    audio_detection = models.BooleanField(default=True)
    blur_faces = models.BooleanField(default=True)
    consent_required = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        self.instant_notification_levels = normalize_instant_notification_levels(self.instant_notification_levels)
        super().save(*args, **kwargs)

    def allows_instant_notification(self, severity: int) -> bool:
        allowed_levels = set(normalize_instant_notification_levels(self.instant_notification_levels))
        return severity_level_for_value(severity) in allowed_levels

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

    class CameraType(models.TextChoices):
        BACKYARD = "backyard", "Backyard"
        FRONT_DOOR = "front_door", "Front Door"
        BEDROOM = "bedroom", "Bedroom"
        GARAGE = "garage", "Garage"
        LIVING_ROOM = "living_room", "Living Room"
        OTHER = "other", "Other"

    class SourceType(models.TextChoices):
        REGISTERED = "registered", "Registered"
        WEBCAM = "webcam", "Webcam"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="cameras")
    name = models.CharField(max_length=200)
    site = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    camera_type = models.CharField(max_length=20, choices=CameraType.choices, default=CameraType.OTHER)
    source_type = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.REGISTERED)
    rtsp_url = models.CharField(max_length=512, blank=True)  # don't return this to clients
    ai_camera_id = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Identifier used by the AI module for this camera",
    )
    stream_path = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Stable camera stream identifier used for UI/AI mapping",
    )
    # Per-camera AI settings (§3 false-positive reduction)
    min_confidence = models.FloatField(default=0.35, help_text="Detection confidence threshold 0-1")
    min_bbox_area = models.IntegerField(default=400, help_text="Min bounding box area in pixels")
    k_of_n_k = models.IntegerField(default=3, help_text="K-of-N persistence: require K")
    k_of_n_n = models.IntegerField(default=5, help_text="K-of-N persistence: out of N")
    cooldown_s = models.IntegerField(default=45, help_text="Alert cooldown seconds")

    def _default_lanes():
        return ["rt_detr", "person_zone"]

    enabled_lanes = models.JSONField(
        default=_default_lanes,
        blank=True,
        help_text="Active detection lanes (e.g. ['rt_detr', 'person_zone', 'fire_smoke_yolo'])"
    )
    source_kind = models.CharField(max_length=50, blank=True, default="", help_text="Derived or explicit source kind (e.g., rtsp, mjpeg, hls)")
    source_fingerprint = models.CharField(max_length=256, blank=True, default="", help_text="Optional TLS fingerprint for HTTPS IP cameras")

    def save(self, *args, **kwargs):
        """Auto-derive stream_path if empty for consistent camera mapping."""
        if not self.stream_path:
            from django.utils.text import slugify
            if self.ai_camera_id:
                self.stream_path = self.ai_camera_id
            elif self.name:
                self.stream_path = slugify(self.name)
        # Keep AI camera id aligned with stream_path when unset.
        # This avoids legacy cam_<pk> IDs and reduces snapshot/preview mismatches.
        if not self.ai_camera_id and self.stream_path:
            self.ai_camera_id = self.stream_path
        super().save(*args, **kwargs)


class CameraZone(TimeStamped):
    """Intrusion / monitoring zone polygon for a camera."""
    class ZoneType(models.TextChoices):
        RESTRICTED = "restricted", "Restricted"
        MONITOR = "monitor", "Monitor"

    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="zones")
    zone_name = models.CharField(max_length=100, default="restricted")
    zone_type = models.CharField(max_length=20, choices=ZoneType.choices, default=ZoneType.RESTRICTED)
    polygon_points = models.JSONField(default=list, help_text="List of [x,y] normalised coords")
    enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = [("camera", "zone_name")]

    def __str__(self):
        return f"{self.zone_name} ({self.zone_type}) on {self.camera.name}"

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

class KnownEntity(TimeStamped):
    """Source-of-truth for enrolled entities (persons / pets / vehicles)."""
    class Category(models.TextChoices):
        PERSON = "person", "Person"
        PET = "pet", "Pet"
        VEHICLE = "vehicle", "Vehicle"

    class Group(models.TextChoices):
        HOUSEHOLD = "household", "Household"
        NEIGHBOR = "neighbor", "Neighbor"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="entities")
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.PERSON)
    group = models.CharField(max_length=20, choices=Group.choices, default=Group.HOUSEHOLD)
    notes = models.TextField(blank=True)
    cameras = models.ManyToManyField(Camera, related_name="known_entities", blank=True)
    ai_entity_id = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Identifier returned by the AI module after enrollment",
    )
    thumbnail_url = models.CharField(max_length=512, blank=True, default="")
    last_seen = models.DateTimeField(null=True, blank=True)
    last_camera = models.ForeignKey(
        Camera,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="last_seen_entities",
    )

    def __str__(self):
        return f"{self.name} ({self.category})"


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
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
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
                condition=models.Q(status="pending"),
                name="unique_pending_invitation_per_tenant_email"
            ),
        ]
        indexes = [
            models.Index(fields=["email", "status"]),
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self):
        return f"Invite {self.email} -> {self.tenant.name} ({self.role}) [{self.status}]"


class NotificationChannel(TimeStamped):
    """Tenant-level notification preferences (§4)."""
    class SeverityThreshold(models.TextChoices):
        HIGH_ONLY = "high", "High only (sev >= 4)"
        MEDIUM_AND_HIGH = "medium", "Medium & High (sev >= 3)"
        ALL = "all", "All severities"

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="notification_channel")
    email_enabled = models.BooleanField(default=False)
    push_enabled = models.BooleanField(default=False)
    email_recipients = models.JSONField(default=list, blank=True, help_text='["a@b.com"]')
    fcm_tokens = models.JSONField(default=list, blank=True, help_text="FCM device tokens")
    severity_threshold = models.CharField(
        max_length=10,
        choices=SeverityThreshold.choices,
        default=SeverityThreshold.HIGH_ONLY,
    )

    def min_severity_int(self) -> int:
        return {"high": 4, "medium": 3, "all": 1}.get(self.severity_threshold, 4)

    def __str__(self):
        return f"Notifications for {self.tenant.name}"


class TenantRuntimeSetting(TimeStamped):
    """Tenant-level runtime controls for AI integration behavior."""

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="runtime_settings")
    webcam_enabled = models.BooleanField(default=False)

    def __str__(self):
        return f"Runtime settings for {self.tenant.name}"


class IncidentEventReceipt(models.Model):
    """
    Idempotency ledger for processed AI incident events.

    Prevents duplicate Incident/Detection/notification creation when
    the same logical event arrives through both Redis Pub/Sub and webhook.

    The event_id is the stable identifier from the AI alert payload
    (e.g., alert session ID or unique alert ID).
    """
    class Source(models.TextChoices):
        REDIS = "redis", "Redis"
        WEBHOOK = "webhook", "Webhook"

    event_id = models.CharField(max_length=255, unique=True, db_index=True)
    source = models.CharField(max_length=16, choices=Source.choices)
    processed_at = models.DateTimeField(auto_now_add=True)
    incident = models.ForeignKey(
        Incident,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_receipts",
    )

    class Meta:
        indexes = [
            models.Index(fields=["event_id"]),
        ]

    def __str__(self):
        return f"Receipt {self.event_id} via {self.source}"