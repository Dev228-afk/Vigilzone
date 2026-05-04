import shutil
import tempfile
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from api.models import (
    AIRuntimeRegistration,
    AuditLog,
    Camera,
    CameraZone,
    Invitation,
    KnownEntity,
    KnownEntityAsset,
    KnownEntityEmbedding,
    KnownEntityProcessingJob,
    MediaMTXDesiredPath,
    Membership,
    NotificationChannel,
    OutboxEvent,
    Profile,
    SchemaBootstrapState,
    ServiceWebhook,
    Tenant,
    TenantRuntimeSetting,
)
from api.services.camera_config_service import CameraConfigService
from api.services.entity_processing_service import EntityProcessingService
from api.services.notification_policy_service import NotificationPolicyService
from api.services.runtime_registration_service import RuntimeRegistrationService


class BootstrapPostgresConfigCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="password123")
        self.tenant = Tenant.objects.create(name="Bootstrap Tenant")
        Membership.objects.create(user=self.user, tenant=self.tenant, role=Membership.Role.OWNER)
        self.camera = Camera.objects.create(
            tenant=self.tenant,
            name="Boot Camera",
            ai_camera_id="boot_cam",
            stream_path="boot_cam",
            rtsp_url="rtsp://example.local/stream",
        )

    def test_bootstrap_command_is_idempotent(self):
        call_command("bootstrap_postgres_config", "--skip-migration-check")
        call_command("bootstrap_postgres_config", "--skip-migration-check")

        self.assertEqual(NotificationChannel.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(TenantRuntimeSetting.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(AIRuntimeRegistration.objects.filter(camera=self.camera).count(), 1)
        self.assertEqual(MediaMTXDesiredPath.objects.filter(camera=self.camera).count(), 1)


class Phase1ServiceLayerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="svc-owner", password="password123")
        self.tenant = Tenant.objects.create(name="Service Tenant")
        Membership.objects.create(user=self.user, tenant=self.tenant, role=Membership.Role.OWNER)
        self.camera_service = CameraConfigService()
        self.notification_service = NotificationPolicyService()
        self.runtime_service = RuntimeRegistrationService()

    def test_camera_service_creates_runtime_sidecars(self):
        camera = self.camera_service.create_camera(
            tenant=self.tenant,
            attrs={
                "name": "Front Gate",
                "rtsp_url": "rtsp://camera/front",
            },
        )

        self.assertTrue(camera.stream_path)
        self.assertTrue(camera.ai_camera_id)
        self.assertTrue(AIRuntimeRegistration.objects.filter(camera=camera).exists())
        self.assertFalse(AIRuntimeRegistration.objects.get(camera=camera).desired_enabled)
        self.assertTrue(MediaMTXDesiredPath.objects.filter(camera=camera).exists())
        self.assertTrue(
            OutboxEvent.objects.filter(
                aggregate_type="camera",
                aggregate_id=str(camera.id),
                event_type="camera.created",
            ).exists()
        )

    def test_camera_service_update_preserves_unsynced_ai_state(self):
        camera = self.camera_service.create_camera(
            tenant=self.tenant,
            attrs={
                "name": "Driveway Cam",
                "status": Camera.Status.ACTIVE,
                "rtsp_url": "rtsp://camera/driveway",
            },
        )

        reg = AIRuntimeRegistration.objects.get(camera=camera)
        self.assertFalse(reg.desired_enabled)

        self.camera_service.update_camera(camera=camera, attrs={"site": "North Gate"})

        reg.refresh_from_db()
        self.assertFalse(reg.desired_enabled)

    def test_notification_service_updates_channel_and_profile(self):
        self.notification_service.set_notification_settings(
            tenant=self.tenant,
            user=self.user,
            channel_payload={
                "email_enabled": True,
                "severity_threshold": NotificationChannel.SeverityThreshold.MEDIUM_AND_HIGH,
            },
            instant_levels=["critical", "moderate"],
        )

        channel = NotificationChannel.objects.get(tenant=self.tenant)
        profile = Profile.objects.get(user=self.user)
        self.assertTrue(channel.email_enabled)
        self.assertEqual(
            channel.severity_threshold,
            NotificationChannel.SeverityThreshold.MEDIUM_AND_HIGH,
        )
        self.assertEqual(profile.instant_notification_levels, ["critical", "moderate"])
        self.assertTrue(
            OutboxEvent.objects.filter(
                aggregate_type="notification_policy",
                aggregate_id=f"{self.tenant.id}:{self.user.id}",
                event_type="notification_policy.updated",
            ).exists()
        )

    def test_runtime_service_sets_webcam_enabled(self):
        setting = self.runtime_service.set_webcam_enabled(tenant=self.tenant, enabled=True)
        self.assertTrue(setting.webcam_enabled)
        self.assertTrue(
            OutboxEvent.objects.filter(
                aggregate_type="tenant_runtime_setting",
                aggregate_id=str(self.tenant.id),
                event_type="runtime.webcam_enabled_set",
            ).exists()
        )

    def test_runtime_service_emits_outbox_for_desired_state(self):
        camera = Camera.objects.create(
            tenant=self.tenant,
            name="Desired State Camera",
            ai_camera_id="desired_cam",
            stream_path="desired_cam",
            rtsp_url="rtsp://camera/desired",
        )

        self.runtime_service.register_ai_camera_desired_state(
            camera=camera,
            enabled=True,
            ingest_backend="opencv",
            sample_hz=2.0,
            lanes=["rt_detr", "person_zone"],
            policy_version=1,
        )

        self.assertTrue(
            OutboxEvent.objects.filter(
                aggregate_type="ai_runtime_registration",
                aggregate_id=str(camera.id),
                event_type="ai_runtime.desired_state_set",
            ).exists()
        )


class CanonicalCrudCreateAPITests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="api-owner",
            email="owner@example.com",
            password="password123",
        )
        self.tenant = Tenant.objects.create(name="CRUD Tenant")
        Membership.objects.create(user=self.user, tenant=self.tenant, role=Membership.Role.OWNER)

        token_resp = self.client.post(
            "/api/auth/token/",
            {"username": "api-owner", "password": "password123"},
            format="json",
        )
        self.assertEqual(token_resp.status_code, status.HTTP_200_OK)
        token = token_resp.data["access"]
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )

    def test_create_camera_entry_persists_sidecars(self):
        response = self.client.post(
            "/api/cameras/",
            {
                "name": "Gate Camera",
                "status": "active",
                "source_type": "registered",
                "rtsp_url": "rtsp://example.local/gate",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        camera = Camera.objects.get(tenant=self.tenant, name="Gate Camera")
        self.assertTrue(camera.stream_path)
        self.assertTrue(camera.ai_camera_id)
        self.assertTrue(AIRuntimeRegistration.objects.filter(camera=camera).exists())
        self.assertFalse(AIRuntimeRegistration.objects.get(camera=camera).desired_enabled)
        self.assertTrue(MediaMTXDesiredPath.objects.filter(camera=camera).exists())
        self.assertFalse(response.data["is_ai_synced"])

    def test_create_entity_entry_persists_when_ai_unavailable(self):
        with patch("requests.post", side_effect=Exception("AI unavailable")), patch(
            "requests.get", side_effect=Exception("AI unavailable")
        ):
            response = self.client.post(
                "/api/entities/",
                {
                    "name": "Visitor Person",
                    "category": "person",
                    "group": "neighbor",
                    "notes": "created from canonical test",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            KnownEntity.objects.filter(
                tenant=self.tenant,
                name="Visitor Person",
                category=KnownEntity.Category.PERSON,
            ).exists()
        )

    def test_create_invitation_entry(self):
        response = self.client.post(
            "/api/invitations/",
            {
                "email": "invitee@example.com",
                "role": Membership.Role.MEMBER,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Invitation.objects.filter(
                tenant=self.tenant,
                email="invitee@example.com",
                role=Membership.Role.MEMBER,
                status=Invitation.Status.PENDING,
            ).exists()
        )


class EntityPhase1AccessAndLifecycleTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Entity Phase1 Tenant")

        self.owner = User.objects.create_user("phase1_owner", password="password123")
        self.admin = User.objects.create_user("phase1_admin", password="password123")
        self.member = User.objects.create_user("phase1_member", password="password123")
        self.viewer = User.objects.create_user("phase1_viewer", password="password123")

        Membership.objects.create(user=self.owner, tenant=self.tenant, role=Membership.Role.OWNER)
        Membership.objects.create(user=self.admin, tenant=self.tenant, role=Membership.Role.ADMIN)
        Membership.objects.create(user=self.member, tenant=self.tenant, role=Membership.Role.MEMBER)
        Membership.objects.create(user=self.viewer, tenant=self.tenant, role=Membership.Role.VIEWER)

    def _auth_as(self, user: User):
        token_resp = self.client.post(
            "/api/auth/token/",
            {"username": user.username, "password": "password123"},
            format="json",
        )
        self.assertEqual(token_resp.status_code, status.HTTP_200_OK)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token_resp.data['access']}",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )

    def _create_entity_as_owner(self, *, name: str = "Entity One", status_value: str = KnownEntity.Status.PENDING, detection_enabled: bool = False):
        return KnownEntity.objects.create(
            tenant=self.tenant,
            name=name,
            category=KnownEntity.Category.PERSON,
            group=KnownEntity.Group.HOUSEHOLD,
            status=status_value,
            detection_enabled=detection_enabled,
            created_by=self.owner,
            updated_by=self.owner,
        )

    def test_owner_can_create_entity_with_phase1_defaults_and_audit(self):
        self._auth_as(self.owner)

        with patch("requests.post", side_effect=Exception("AI unavailable")):
            response = self.client.post(
                "/api/entities/",
                {
                    "name": "Phase1 Owner Entity",
                    "category": "person",
                    "group": "household",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        entity = KnownEntity.objects.get(tenant=self.tenant, name="Phase1 Owner Entity")
        self.assertEqual(entity.status, KnownEntity.Status.PENDING)
        self.assertFalse(entity.detection_enabled)
        self.assertEqual(entity.created_by_id, self.owner.id)
        self.assertEqual(entity.updated_by_id, self.owner.id)
        self.assertTrue(
            AuditLog.objects.filter(
                tenant=self.tenant,
                actor=self.owner,
                action="entity.create",
                target_type="entity",
                target_id=str(entity.id),
            ).exists()
        )

    def test_admin_can_create_entity(self):
        self._auth_as(self.admin)

        with patch("requests.post", side_effect=Exception("AI unavailable")):
            response = self.client.post(
                "/api/entities/",
                {
                    "name": "Phase1 Admin Entity",
                    "category": "person",
                    "group": "neighbor",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        entity = KnownEntity.objects.get(tenant=self.tenant, name="Phase1 Admin Entity")
        self.assertEqual(entity.created_by_id, self.admin.id)
        self.assertEqual(entity.status, KnownEntity.Status.PENDING)
        self.assertFalse(entity.detection_enabled)

    def test_member_cannot_create_entity(self):
        self._auth_as(self.member)
        response = self.client.post(
            "/api/entities/",
            {
                "name": "Blocked Member Entity",
                "category": "person",
                "group": "household",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_entity(self):
        entity = self._create_entity_as_owner(name="Viewer Update Block")
        self._auth_as(self.viewer)

        response = self.client.patch(
            f"/api/entities/{entity.id}/",
            {"notes": "viewer should not update"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_delete_entity(self):
        entity = self._create_entity_as_owner(name="Member Delete Block")
        self._auth_as(self.member)

        response = self.client.delete(f"/api/entities/{entity.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        entity.refresh_from_db()
        self.assertEqual(entity.status, KnownEntity.Status.PENDING)

    def test_admin_can_disable_detection_and_logs_toggle(self):
        entity = self._create_entity_as_owner(
            name="Admin Disable Detection",
            status_value=KnownEntity.Status.READY,
            detection_enabled=True,
        )
        self._auth_as(self.admin)

        response = self.client.patch(
            f"/api/entities/{entity.id}/",
            {"detection_enabled": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entity.refresh_from_db()
        self.assertFalse(entity.detection_enabled)
        self.assertEqual(entity.updated_by_id, self.admin.id)
        self.assertTrue(
            AuditLog.objects.filter(
                tenant=self.tenant,
                actor=self.admin,
                action="entity.toggle_detection",
                target_type="entity",
                target_id=str(entity.id),
            ).exists()
        )

    def test_enable_detection_requires_ready_status(self):
        entity = self._create_entity_as_owner(name="Enable Requires Ready", status_value=KnownEntity.Status.PENDING)
        self._auth_as(self.owner)

        response = self.client.patch(
            f"/api/entities/{entity.id}/",
            {"detection_enabled": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detection_enabled", response.data)

    def test_owner_delete_soft_deletes_and_logs_audit(self):
        entity = self._create_entity_as_owner(
            name="Soft Delete Entity",
            status_value=KnownEntity.Status.READY,
            detection_enabled=True,
        )
        self._auth_as(self.owner)

        response = self.client.delete(f"/api/entities/{entity.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        entity.refresh_from_db()
        self.assertEqual(entity.status, KnownEntity.Status.DELETED)
        self.assertFalse(entity.detection_enabled)
        self.assertIsNotNone(entity.deleted_at)
        self.assertEqual(entity.updated_by_id, self.owner.id)
        self.assertTrue(
            AuditLog.objects.filter(
                tenant=self.tenant,
                actor=self.owner,
                action="entity.delete",
                target_type="entity",
                target_id=str(entity.id),
            ).exists()
        )


class AIInternalSyncEndpointTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Sync Tenant")
        self.camera = Camera.objects.create(
            tenant=self.tenant,
            name="Sync Cam",
            ai_camera_id="sync_cam",
            stream_path="sync_cam",
            rtsp_url="rtsp://example.local/sync",
        )

    def test_runtime_sync_endpoint_upserts_runtime_registration(self):
        response = self.client.post(
            "/api/ai/internal/runtime/sync/",
            {
                "camera_id": "sync_cam",
                "tenant_id": self.tenant.id,
                "camera_name": "Sync Cam",
                "stream_path": "sync_cam",
                "rtsp_url": "rtsp://example.local/sync",
                "enabled": True,
                "running": True,
                "ingest_backend": "opencv",
                "enabled_lanes": ["rt_detr", "person_zone"],
                "sample_hz": 2.0,
                "policy_version": 1,
                "entity_detection_enabled": False,
                "identity_runtime_enabled": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        reg = AIRuntimeRegistration.objects.get(camera=self.camera)
        self.assertTrue(reg.desired_enabled)
        self.assertEqual(reg.desired_ingest_backend, "opencv")
        self.assertTrue(reg.observed_enabled)

        self.camera.refresh_from_db()
        self.assertFalse(self.camera.entity_detection_enabled)

        runtime_setting = TenantRuntimeSetting.objects.get(tenant=self.tenant)
        self.assertFalse(runtime_setting.identity_runtime_enabled)

    def test_webhooks_sync_endpoint_upserts_service_webhooks(self):
        response = self.client.post(
            "/api/ai/internal/webhooks/sync/",
            {
                "tenant_id": self.tenant.id,
                "webhooks": {
                    "wh_test_001": {
                        "id": "wh_test_001",
                        "url": "http://localhost:8000/api/ai/webhook/receive/",
                        "events": ["alert.created"],
                        "active": True,
                        "metadata": {},
                        "delivery_stats": {"success": 1, "failure": 0, "last_status": 200},
                    }
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        webhook = ServiceWebhook.objects.get(webhook_id="wh_test_001")
        self.assertEqual(webhook.url, "http://localhost:8000/api/ai/webhook/receive/")
        self.assertTrue(webhook.active)
        self.assertTrue(
            OutboxEvent.objects.filter(
                aggregate_type="service_webhook",
                event_type="webhook.synced",
            ).exists()
        )

    def test_webhooks_snapshot_endpoint_returns_canonical_registry(self):
        ServiceWebhook.objects.create(
            webhook_id="wh_snapshot_001",
            tenant=self.tenant,
            url="http://localhost:8000/api/ai/webhook/receive/",
            events=["alert.created"],
            metadata={"source": "test"},
            delivery_stats={"success": 2, "failure": 0},
            active=True,
            has_secret=False,
            source=ServiceWebhook.Source.AI,
        )

        response = self.client.get("/api/ai/internal/webhooks/snapshot/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("webhooks", response.data)
        self.assertIn("wh_snapshot_001", response.data["webhooks"])
        snapshot_row = response.data["webhooks"]["wh_snapshot_001"]
        self.assertEqual(snapshot_row["url"], "http://localhost:8000/api/ai/webhook/receive/")
        self.assertEqual(snapshot_row["events"], ["alert.created"])

    def test_cameras_snapshot_endpoint_returns_canonical_camera_and_zone_state(self):
        self.camera.enabled_lanes = ["rt_detr", "entity_identity", "person_zone"]
        self.camera.entity_detection_enabled = False
        self.camera.save(update_fields=["enabled_lanes", "entity_detection_enabled", "updated_at"])

        TenantRuntimeSetting.objects.update_or_create(
            tenant=self.tenant,
            defaults={"identity_runtime_enabled": True},
        )

        CameraZone.objects.create(
            camera=self.camera,
            zone_name="restricted_1",
            zone_type=CameraZone.ZoneType.RESTRICTED,
            polygon_points=[[10, 10], [100, 10], [100, 100], [10, 100]],
            enabled=True,
        )

        response = self.client.get("/api/ai/internal/cameras/snapshot/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data.get("count", 0), 1)

        row = next((item for item in response.data.get("cameras", []) if item.get("camera_id") == "sync_cam"), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["camera_name"], "Sync Cam")
        self.assertEqual(row["stream_path"], "sync_cam")
        self.assertEqual(row["source_type"], "rtsp")
        self.assertFalse(row["entity_detection_enabled"])
        self.assertTrue(row["identity_runtime_enabled"])
        self.assertFalse(row["effective_entity_detection_enabled"])
        self.assertNotIn("entity_identity", row["enabled_lanes"])

        zones = response.data.get("zones", {}).get("sync_cam", [])
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["name"], "restricted_1")

    def test_policy_snapshot_endpoint_returns_canonical_policy(self):
        SchemaBootstrapState.objects.create(
            key="ai.policy.snapshot.v1",
            value={
                "policy": {
                    "intrusion": {
                        "unknown_in_restricted": "HIGH",
                    }
                },
                "version": 2,
                "source": "test",
            },
        )

        response = self.client.get("/api/ai/internal/policy/snapshot/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("policy", response.data)
        self.assertEqual(response.data.get("version"), 2)
        self.assertEqual(
            response.data["policy"]["intrusion"]["unknown_in_restricted"],
            "HIGH",
        )

    def test_identity_sync_upsert_updates_existing_entity_and_emits_outbox_event(self):
        existing = KnownEntity.objects.create(
            tenant=self.tenant,
            name="Existing Internal Sync Person",
            category=KnownEntity.Category.PERSON,
            group=KnownEntity.Group.HOUSEHOLD,
            status=KnownEntity.Status.PROCESSING,
            detection_enabled=False,
        )

        response = self.client.post(
            "/api/ai/internal/identity/sync/",
            {
                "op": "upsert_entity",
                "tenant_id": self.tenant.id,
                "entity_id": "ent_sync_001",
                "known_entity_id": existing.id,
                "name": "Internal Sync Person",
                "category": "KNOWN_PERSON",
                "role": "VISITOR",
                "metadata": {
                    "allowed_camera_ids": ["sync_cam"],
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entity = KnownEntity.objects.get(ai_entity_id="ent_sync_001", tenant=self.tenant)
        self.assertEqual(entity.name, "Internal Sync Person")
        self.assertTrue(
            OutboxEvent.objects.filter(
                aggregate_type="known_entity",
                aggregate_id=str(entity.id),
                event_type="identity.entity_updated",
            ).exists()
        )

    def test_identity_sync_upsert_blocks_ai_side_entity_creation_by_default(self):
        response = self.client.post(
            "/api/ai/internal/identity/sync/",
            {
                "op": "upsert_entity",
                "tenant_id": self.tenant.id,
                "entity_id": "ent_sync_create_blocked",
                "name": "Blocked Creation",
                "category": "KNOWN_PERSON",
                "role": "VISITOR",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(KnownEntity.objects.filter(ai_entity_id="ent_sync_create_blocked").exists())

    def test_identity_snapshot_filters_to_ready_detection_enabled_entities(self):
        eligible = KnownEntity.objects.create(
            tenant=self.tenant,
            name="Eligible Entity",
            category=KnownEntity.Category.PERSON,
            group=KnownEntity.Group.HOUSEHOLD,
            ai_entity_id="ent_ready_enabled",
            status=KnownEntity.Status.READY,
            detection_enabled=True,
            embedding_version=3,
        )
        KnownEntityEmbedding.objects.create(
            tenant=self.tenant,
            entity=eligible,
            modality=KnownEntityEmbedding.Modality.FACE,
            vector=[0.1] * 512,
            source_dim=512,
            metadata={"source": "test"},
        )

        KnownEntity.objects.create(
            tenant=self.tenant,
            name="Disabled Entity",
            category=KnownEntity.Category.PERSON,
            group=KnownEntity.Group.HOUSEHOLD,
            ai_entity_id="ent_ready_disabled",
            status=KnownEntity.Status.READY,
            detection_enabled=False,
        )
        KnownEntity.objects.create(
            tenant=self.tenant,
            name="Pending Entity",
            category=KnownEntity.Category.PERSON,
            group=KnownEntity.Group.HOUSEHOLD,
            ai_entity_id="ent_pending_enabled",
            status=KnownEntity.Status.PENDING,
            detection_enabled=True,
        )

        response = self.client.get(
            "/api/ai/internal/identity/snapshot/",
            {"tenant_id": self.tenant.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("identity_version", response.data)
        entities = response.data.get("entities", [])
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["entity_id"], "ent_ready_enabled")
        self.assertEqual(entities[0]["status"], KnownEntity.Status.READY)
        self.assertTrue(entities[0]["detection_enabled"])
        self.assertEqual(entities[0]["embedding_version"], 3)

        embeddings = response.data.get("embeddings", [])
        self.assertEqual(len(embeddings), 1)
        self.assertEqual(embeddings[0]["entity_id"], "ent_ready_enabled")

    def test_identity_snapshot_camera_scope_returns_empty_when_camera_identity_disabled(self):
        entity = KnownEntity.objects.create(
            tenant=self.tenant,
            name="Camera Scoped Entity",
            category=KnownEntity.Category.PERSON,
            group=KnownEntity.Group.HOUSEHOLD,
            ai_entity_id="ent_cam_scoped",
            status=KnownEntity.Status.READY,
            detection_enabled=True,
        )
        entity.cameras.add(self.camera)
        KnownEntityEmbedding.objects.create(
            tenant=self.tenant,
            entity=entity,
            modality=KnownEntityEmbedding.Modality.FACE,
            vector=[0.2] * 512,
            source_dim=512,
            metadata={"source": "camera-scope-test"},
        )

        self.camera.entity_detection_enabled = False
        self.camera.save(update_fields=["entity_detection_enabled", "updated_at"])

        TenantRuntimeSetting.objects.update_or_create(
            tenant=self.tenant,
            defaults={"identity_runtime_enabled": True},
        )

        response = self.client.get(
            "/api/ai/internal/identity/snapshot/",
            {"tenant_id": self.tenant.id, "camera_id": "sync_cam"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get("entities"), [])
        self.assertEqual(response.data.get("embeddings"), [])
        self.assertEqual(response.data.get("count_entities"), 0)
        self.assertEqual(response.data.get("count_embeddings"), 0)
        self.assertTrue(str(response.data.get("identity_version", "")).startswith("camera_disabled:"))

    def test_identity_sync_add_embedding_emits_outbox_event(self):
        entity = KnownEntity.objects.create(
            tenant=self.tenant,
            name="Embedded Entity",
            category=KnownEntity.Category.PERSON,
            group=KnownEntity.Group.HOUSEHOLD,
            ai_entity_id="ent_embedding_001",
        )

        response = self.client.post(
            "/api/ai/internal/identity/sync/",
            {
                "op": "add_embedding",
                "tenant_id": self.tenant.id,
                "entity_id": "ent_embedding_001",
                "modality": "face",
                "vector": [0.1, 0.2, 0.3],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(KnownEntityEmbedding.objects.filter(entity=entity).count(), 1)
        embedding = KnownEntityEmbedding.objects.get(entity=entity)
        self.assertEqual(embedding.source_dim, 3)
        self.assertTrue(
            OutboxEvent.objects.filter(
                aggregate_type="known_entity_embedding",
                aggregate_id=str(embedding.id),
                event_type="identity.embedding_added",
            ).exists()
        )

    def test_identity_sync_record_sighting_emits_outbox_event(self):
        entity = KnownEntity.objects.create(
            tenant=self.tenant,
            name="Sighted Entity",
            category=KnownEntity.Category.PERSON,
            group=KnownEntity.Group.HOUSEHOLD,
            ai_entity_id="ent_sighting_001",
        )

        response = self.client.post(
            "/api/ai/internal/identity/sync/",
            {
                "op": "record_sighting",
                "tenant_id": self.tenant.id,
                "entity_id": "ent_sighting_001",
                "camera_id": "sync_cam",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entity.refresh_from_db()
        self.assertIsNotNone(entity.last_seen)
        self.assertEqual(entity.last_camera_id, self.camera.id)
        self.assertTrue(
            OutboxEvent.objects.filter(
                aggregate_type="known_entity",
                aggregate_id=str(entity.id),
                event_type="identity.entity_sighting_recorded",
            ).exists()
        )


class EntityPhase2RegistrationProcessingTests(APITestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="entity-phase2-media-")
        self._media_override = override_settings(MEDIA_ROOT=self.media_root)
        self._media_override.enable()

        self.client = APIClient()
        self.processing_service = EntityProcessingService()

        self.tenant = Tenant.objects.create(name="Entity Phase2 Tenant")
        self.owner = User.objects.create_user("phase2_owner", password="password123")
        Membership.objects.create(user=self.owner, tenant=self.tenant, role=Membership.Role.OWNER)

        token_resp = self.client.post(
            "/api/auth/token/",
            {"username": self.owner.username, "password": "password123"},
            format="json",
        )
        self.assertEqual(token_resp.status_code, status.HTTP_200_OK)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token_resp.data['access']}",
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )

    def tearDown(self):
        self._media_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def test_create_entity_enqueues_processing_and_persists_assets(self):
        upload = SimpleUploadedFile(
            "person_1.jpg",
            b"\xff\xd8\xff\xdb\x00Cphase2-image",
            content_type="image/jpeg",
        )

        with patch("api.services.entity_processing_service.requests.post") as ai_post:
            response = self.client.post(
                "/api/entities/",
                {
                    "name": "Queued Entity",
                    "category": KnownEntity.Category.PERSON,
                    "group": KnownEntity.Group.HOUSEHOLD,
                    "files": [upload],
                },
                format="multipart",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ai_post.assert_not_called()

        entity = KnownEntity.objects.get(tenant=self.tenant, name="Queued Entity")
        self.assertEqual(entity.status, KnownEntity.Status.PENDING)
        self.assertFalse(entity.detection_enabled)
        self.assertEqual(KnownEntityAsset.objects.filter(entity=entity, is_active=True).count(), 1)

        job = KnownEntityProcessingJob.objects.get(entity=entity)
        self.assertEqual(job.status, KnownEntityProcessingJob.Status.QUEUED)
        self.assertEqual(job.metadata.get("asset_count"), 1)

        self.assertIn("processing", response.data)
        self.assertEqual(response.data["processing"]["job_id"], job.id)

    def test_processing_worker_marks_entity_ready_when_embeddings_exist(self):
        entity = KnownEntity.objects.create(
            tenant=self.tenant,
            name="Worker Success",
            category=KnownEntity.Category.PERSON,
            group=KnownEntity.Group.HOUSEHOLD,
            status=KnownEntity.Status.PENDING,
            created_by=self.owner,
            updated_by=self.owner,
        )
        upload = SimpleUploadedFile(
            "worker_success.jpg",
            b"\xff\xd8\xff\xdb\x00Cworker-success",
            content_type="image/jpeg",
        )
        KnownEntityAsset.objects.create(
            tenant=self.tenant,
            entity=entity,
            asset_type=KnownEntityAsset.AssetType.ENROLLMENT_IMAGE,
            file=upload,
            checksum="",
            content_type="image/jpeg",
            uploaded_by=self.owner,
            is_active=True,
        )
        job, created = self.processing_service.enqueue_job(entity=entity, requested_by=self.owner)
        self.assertTrue(created)

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "entity_id": "ent_phase2_ready",
            "thumbnail": "/enroll_images/ent_phase2_ready/thumb.jpg",
            "embeddings_stored": 2,
        }

        with patch("api.services.entity_processing_service.requests.post", return_value=mock_response), patch(
            "api.services.entity_processing_service.EntityProcessingService._wait_for_synced_embeddings",
            return_value=2,
        ):
            summary = self.processing_service.process_queued_jobs(limit=1)

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["failed"], 0)

        job.refresh_from_db()
        entity.refresh_from_db()
        self.assertEqual(job.status, KnownEntityProcessingJob.Status.COMPLETED)
        self.assertEqual(entity.status, KnownEntity.Status.READY)
        self.assertEqual(entity.ai_entity_id, "ent_phase2_ready")
        self.assertTrue(entity.thumbnail_url.endswith("thumb.jpg"))
        self.assertEqual(entity.processing_error, "")

    def test_processing_worker_marks_entity_failed_when_ai_unavailable(self):
        entity = KnownEntity.objects.create(
            tenant=self.tenant,
            name="Worker Failure",
            category=KnownEntity.Category.PERSON,
            group=KnownEntity.Group.HOUSEHOLD,
            status=KnownEntity.Status.PENDING,
            created_by=self.owner,
            updated_by=self.owner,
        )
        upload = SimpleUploadedFile(
            "worker_failure.jpg",
            b"\xff\xd8\xff\xdb\x00Cworker-failure",
            content_type="image/jpeg",
        )
        KnownEntityAsset.objects.create(
            tenant=self.tenant,
            entity=entity,
            asset_type=KnownEntityAsset.AssetType.ENROLLMENT_IMAGE,
            file=upload,
            checksum="",
            content_type="image/jpeg",
            uploaded_by=self.owner,
            is_active=True,
        )
        self.processing_service.enqueue_job(entity=entity, requested_by=self.owner)

        with patch(
            "api.services.entity_processing_service.requests.post",
            side_effect=RuntimeError("AI unavailable"),
        ):
            summary = self.processing_service.process_queued_jobs(limit=1)

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["succeeded"], 0)
        self.assertEqual(summary["failed"], 1)

        entity.refresh_from_db()
        job = KnownEntityProcessingJob.objects.get(entity=entity)
        self.assertEqual(job.status, KnownEntityProcessingJob.Status.FAILED)
        self.assertEqual(entity.status, KnownEntity.Status.FAILED)
        self.assertIn("AI unavailable", entity.processing_error)
