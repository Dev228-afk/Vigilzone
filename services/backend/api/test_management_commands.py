import json
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from ai_integration.management.commands.subscribe_incidents import Command as SubscribeIncidentsCommand
from ai_integration.redis_queue import build_test_incident_event
from api.models import Alert, Camera, Detection, Incident, IncidentEventReceipt, Membership, Tenant


class DedupeBackfilledAlertsCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="password123")
        self.tenant = Tenant.objects.create(name="Test Tenant")
        Membership.objects.create(user=self.user, tenant=self.tenant, role="owner")
        self.camera = Camera.objects.create(tenant=self.tenant, name="Test Camera", status="active")
        self.incident = Incident.objects.create(
            tenant=self.tenant,
            camera=self.camera,
            type="fire",
            status="open",
            severity=4,
            started_at=timezone.now(),
        )

    def test_command_keeps_read_alert_when_deduping(self):
        unread = Alert.objects.create(
            incident=self.incident,
            channel="websocket",
            payload={"user_id": self.user.id, "username": self.user.username, "backfilled": True},
        )
        read = Alert.objects.create(
            incident=self.incident,
            channel="websocket",
            payload={"user_id": self.user.id, "username": self.user.username, "backfilled": True},
            delivered_at=timezone.now(),
        )

        out = StringIO()
        call_command("dedupe_backfilled_alerts", stdout=out)

        remaining_ids = list(
            Alert.objects.filter(incident=self.incident, payload__backfilled=True)
            .values_list("id", flat=True)
        )
        self.assertEqual(remaining_ids, [read.id])
        self.assertIn(str(unread.id), out.getvalue())

    def test_command_dry_run_does_not_delete(self):
        Alert.objects.create(
            incident=self.incident,
            channel="websocket",
            payload={"user_id": self.user.id, "username": self.user.username, "backfilled": True},
        )
        Alert.objects.create(
            incident=self.incident,
            channel="websocket",
            payload={"user_id": self.user.id, "username": self.user.username, "backfilled": True},
        )

        call_command("dedupe_backfilled_alerts", "--dry-run")

        self.assertEqual(
            Alert.objects.filter(incident=self.incident, payload__backfilled=True).count(),
            2,
        )


class SubscribeIncidentsCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="password123")
        self.tenant = Tenant.objects.create(name="Queue Tenant")
        Membership.objects.create(user=self.user, tenant=self.tenant, role="owner")
        self.camera = Camera.objects.create(
            tenant=self.tenant,
            name="Queue Camera",
            ai_camera_id="queue_cam_01",
            stream_path="queue_cam_01",
            status="active",
        )

    @patch('api.notification_service.get_channel_layer')
    @patch('api.notification_service.NotificationService.broadcast_incident')
    def test_process_message_creates_records_from_queue_event(self, mock_broadcast, mock_get_layer):
        mock_get_layer.return_value = MagicMock()
        mock_broadcast.return_value = {'websocket': 'sent', 'alerts_created': 1}
        command = SubscribeIncidentsCommand()
        raw_message = json.dumps(
            build_test_incident_event(
                camera_id='queue_cam_01',
                tenant_id=self.tenant.id,
                incident_type='fire',
                severity=4,
            )
        )

        with self.captureOnCommitCallbacks(execute=True):
            handled = command._process_message(raw_message)

        self.assertTrue(handled)
        self.assertEqual(Incident.objects.filter(camera=self.camera).count(), 1)
        self.assertEqual(Detection.objects.filter(camera=self.camera).count(), 1)
        self.assertEqual(IncidentEventReceipt.objects.count(), 1)
        self.assertEqual(mock_broadcast.call_count, 1)

    @patch('api.notification_service.get_channel_layer')
    @patch('api.notification_service.NotificationService.broadcast_incident')
    def test_process_message_updates_open_incident_from_queue_event(self, mock_broadcast, mock_get_layer):
        mock_get_layer.return_value = MagicMock()
        mock_broadcast.return_value = {'websocket': 'sent', 'alerts_created': 1}
        existing = Incident.objects.create(
            tenant=self.tenant,
            camera=self.camera,
            type='fire',
            status='open',
            severity=3,
            started_at=timezone.now(),
        )
        mock_broadcast.reset_mock()
        command = SubscribeIncidentsCommand()
        raw_message = json.dumps(
            build_test_incident_event(
                camera_id='queue_cam_01',
                tenant_id=self.tenant.id,
                incident_type='fire',
                severity=5,
            )
        )

        with self.captureOnCommitCallbacks(execute=True):
            handled = command._process_message(raw_message)

        self.assertTrue(handled)
        existing.refresh_from_db()
        self.assertEqual(existing.severity, 5)
        self.assertEqual(Incident.objects.filter(camera=self.camera).count(), 1)
        self.assertEqual(Detection.objects.filter(camera=self.camera).count(), 1)
        self.assertEqual(IncidentEventReceipt.objects.count(), 1)
        self.assertEqual(mock_broadcast.call_count, 1)
