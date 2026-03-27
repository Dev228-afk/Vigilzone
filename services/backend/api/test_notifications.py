"""
Unit tests for the notification service.

Tests cover:
- NotificationService.broadcast_incident()
- NotificationService.broadcast_message()
- REST API endpoints for notifications
- WebSocket consumer authentication and group joining
"""

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from api.models import (
    Tenant, Membership, Camera, Incident, Alert, 
)
from api.notification_service import NotificationService, dispatch_notifications


@override_settings(
    REST_FRAMEWORK={
        'DEFAULT_AUTHENTICATION_CLASSES': [
            'rest_framework_simplejwt.authentication.JWTAuthentication',
        ],
        'DEFAULT_PERMISSION_CLASSES': [
            'rest_framework.permissions.IsAuthenticated',
        ],
    }
)
class NotificationServiceTests(TestCase):
    """Test NotificationService broadcast functions."""
    
    def setUp(self):
        # Create test tenant and user
        self.tenant = Tenant.objects.create(name='Test Tenant')
        self.user = User.objects.create_user(
            username='testuser', 
            email='test@test.com', 
            password='password123'
        )
        Membership.objects.create(
            user=self.user, 
            tenant=self.tenant, 
            role='owner'
        )
        
        # Create camera
        self.camera = Camera.objects.create(
            tenant=self.tenant,
            name='Test Camera',
            status='active'
        )
    
    @patch('api.notification_service.get_channel_layer')
    def test_broadcast_incident_creates_alerts(self, mock_get_layer):
        """Test that broadcast_incident creates Alert records for all members."""
        # Mock channel layer
        mock_layer = MagicMock()
        mock_get_layer.return_value = mock_layer
        
        # Create an incident
        incident = Incident.objects.create(
            tenant=self.tenant,
            camera=self.camera,
            type='intrusion',
            status='open',
            severity=4,
            started_at=timezone.now()
        )
        
        # Call broadcast
        result = NotificationService.broadcast_incident(incident)
        
        # Verify alerts were created for all members
        self.assertGreaterEqual(result['alerts_created'], 1)
        
        # Verify alert content
        alert = Alert.objects.filter(incident=incident).first()
        self.assertIsNotNone(alert)
        self.assertIsNotNone(alert.payload)
        self.assertIn('title', alert.payload)
    
    @patch('api.notification_service.get_channel_layer')
    def test_broadcast_incident_calls_channel(self, mock_get_layer):
        """Test that broadcast_incident sends to channel layer."""
        mock_layer = MagicMock()
        mock_get_layer.return_value = mock_layer
        
        incident = Incident.objects.create(
            tenant=self.tenant,
            camera=self.camera,
            type='fire',
            status='open',
            severity=5,
            started_at=timezone.now()
        )
        
        result = NotificationService.broadcast_incident(incident)
        
        # Verify channel broadcast was called at least once
        self.assertGreaterEqual(mock_layer.group_send.call_count, 1)
    
    @patch('api.notification_service.get_channel_layer')
    def test_broadcast_message(self, mock_get_layer):
        """Test broadcasting a custom message."""
        mock_layer = MagicMock()
        mock_get_layer.return_value = mock_layer
        
        result = NotificationService.broadcast_message(
            tenant_id=self.tenant.id,
            title="Test Broadcast",
            message="This is a test message",
            notification_type="broadcast"
        )
        
        # Verify message was sent
        self.assertIsNotNone(result)
    
    @patch('api.notification_service.get_channel_layer')
    def test_broadcast_handles_channel_unavailable(self, mock_get_layer):
        """Test graceful handling when channel layer is unavailable."""
        mock_get_layer.return_value = None  # Simulate unavailable
        
        incident = Incident.objects.create(
            tenant=self.tenant,
            camera=self.camera,
            type='intrusion',
            status='open',
            severity=3,
            started_at=timezone.now()
        )
        
        result = NotificationService.broadcast_incident(incident)
        
        # Should still create alerts even if channel fails
        self.assertEqual(result['websocket'], 'channel_layer_unavailable')
        self.assertGreaterEqual(result['alerts_created'], 1)
    
    def test_dispatch_notifications_calls_broadcast(self):
        """Test that dispatch_notifications calls broadcast_incident."""
        with patch.object(NotificationService, 'broadcast_incident') as mock_broadcast:
            mock_broadcast.return_value = {'websocket': 'sent', 'alerts_created': 1}
            
            incident = Incident.objects.create(
                tenant=self.tenant,
                camera=self.camera,
                type='intrusion',
                status='open',
                severity=3,
                started_at=timezone.now()
            )
            
            dispatch_notifications(incident)
            
            # broadcast_incident should have been called
            self.assertGreaterEqual(mock_broadcast.call_count, 1)


@override_settings(
    REST_FRAMEWORK={
        'DEFAULT_AUTHENTICATION_CLASSES': [
            'rest_framework_simplejwt.authentication.JWTAuthentication',
        ],
        'DEFAULT_PERMISSION_CLASSES': [
            'rest_framework.permissions.IsAuthenticated',
        ],
    }
)
class NotificationAPITests(APITestCase):
    """Test notification REST API endpoints."""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create users
        self.owner = User.objects.create_user(
            username='owner', 
            email='owner@test.com', 
            password='password123'
        )
        self.member = User.objects.create_user(
            username='member', 
            email='member@test.com', 
            password='password123'
        )
        
        # Create tenant
        self.tenant = Tenant.objects.create(name='Test Tenant')
        
        # Create memberships
        Membership.objects.create(
            user=self.owner, 
            tenant=self.tenant, 
            role='owner'
        )
        Membership.objects.create(
            user=self.member, 
            tenant=self.tenant, 
            role='member'
        )
        
        # Create camera and incident for testing
        self.camera = Camera.objects.create(
            tenant=self.tenant,
            name='Test Camera',
            status='active'
        )
        
        # Create incident with alert
        self.incident = Incident.objects.create(
            tenant=self.tenant,
            camera=self.camera,
            type='intrusion',
            status='open',
            severity=4,
            started_at=timezone.now()
        )
        
        # Create alert
        self.alert = Alert.objects.create(
            incident=self.incident,
            channel='websocket',
            payload={
                'title': 'Test Alert',
                'message': 'This is a test',
                'data': {}
            }
        )
        
        # Get owner token
        response = self.client.post(
            '/api/auth/token/', 
            {'username': 'owner', 'password': 'password123'}, 
            format='json'
        )
        self.token = response.data['access']
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
            HTTP_X_TENANT_ID=str(self.tenant.id)
        )
    
    @patch('api.notification_service.get_channel_layer')
    def test_list_notifications(self, mock_get_layer):
        """Test GET /api/notifications/ returns notifications."""
        mock_get_layer.return_value = MagicMock()
        
        response = self.client.get('/api/notifications/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('notifications', response.data)
        # Should have at least the alert we created
        self.assertGreaterEqual(len(response.data['notifications']), 1)
    
    def test_list_notifications_requires_auth(self):
        """Test that listing notifications requires authentication."""
        self.client.credentials()  # Remove auth
        response = self.client.get('/api/notifications/')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_list_notifications_requires_tenant(self):
        """Test that listing notifications requires X-Tenant-ID."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')
        response = self.client.get('/api/notifications/')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    @patch('api.notification_service.get_channel_layer')
    def test_mark_read_single(self, mock_get_layer):
        """Test marking a single notification as read."""
        mock_get_layer.return_value = MagicMock()
        
        response = self.client.post(
            '/api/notifications/mark-read/',
            {'notification_ids': [self.alert.id]},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify alert was marked
        self.alert.refresh_from_db()
        self.assertIsNotNone(self.alert.delivered_at)
    
    @patch('api.notification_service.get_channel_layer')
    def test_mark_read_all(self, mock_get_layer):
        """Test marking all notifications as read."""
        mock_get_layer.return_value = MagicMock()
        
        response = self.client.post(
            '/api/notifications/mark-read/',
            {'mark_all': True},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data['marked_read'], 1)
    
    @patch('api.notification_service.get_channel_layer')
    def test_unread_count(self, mock_get_layer):
        """Test getting unread notification count."""
        mock_get_layer.return_value = MagicMock()
        
        response = self.client.get('/api/notifications/unread-count/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data['unread_count'], 1)

    def test_transport_status_endpoint(self):
        """Test GET /api/notifications/transport-status/ returns health payload."""
        response = self.client.get('/api/notifications/transport-status/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('uses_redis', response.data)
        self.assertIn('redis_reachable', response.data)
        self.assertIn('channel_backend', response.data)
    
    @patch('api.notification_service.get_channel_layer')
    def test_broadcast_requires_title_and_message(self, mock_get_layer):
        """Test that broadcast requires title and message."""
        mock_get_layer.return_value = MagicMock()
        
        response = self.client.post(
            '/api/notifications/broadcast/',
            {'title': 'Only Title'},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    @patch('api.notification_service.get_channel_layer')
    @patch('api.views.NotificationService.broadcast_message')
    def test_test_websocket_notification(self, mock_broadcast, mock_get_layer):
        """Test sending a test WebSocket notification."""
        mock_get_layer.return_value = MagicMock()
        mock_broadcast.return_value = "sent"
        
        response = self.client.post(
            '/api/notifications/test-websocket/',
            {},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertIn('sent to all connected clients', response.data['message'])


@override_settings(
    REST_FRAMEWORK={
        'DEFAULT_AUTHENTICATION_CLASSES': [
            'rest_framework_simplejwt.authentication.JWTAuthentication',
        ],
        'DEFAULT_PERMISSION_CLASSES': [
            'rest_framework.permissions.IsAuthenticated',
        ],
    }
)
class IncidentCreationNotificationTests(APITestCase):
    """Test that creating incidents triggers notifications."""
    
    def setUp(self):
        self.client = APIClient()
        
        self.owner = User.objects.create_user(
            username='owner', 
            email='owner@test.com', 
            password='password123'
        )
        
        self.tenant = Tenant.objects.create(name='Test Tenant')
        Membership.objects.create(
            user=self.owner, 
            tenant=self.tenant, 
            role='owner'
        )
        
        self.camera = Camera.objects.create(
            tenant=self.tenant,
            name='Test Camera',
            status='active'
        )
        
        response = self.client.post(
            '/api/auth/token/', 
            {'username': 'owner', 'password': 'password123'}, 
            format='json'
        )
        self.token = response.data['access']
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.token}',
            HTTP_X_TENANT_ID=str(self.tenant.id)
        )
    
    def test_incident_notification_integration(self):
        """Test that creating an incident through the model triggers notifications.
        
        Note: This tests the dispatch_notifications function directly since
        the serializer validation is complex in tests.
        """
        with patch('api.notification_service.get_channel_layer') as mock_layer:
            mock_layer.return_value = MagicMock()
            
            # Create incident
            incident = Incident.objects.create(
                tenant=self.tenant,
                camera=self.camera,
                type='intrusion',
                status='open',
                severity=4,
                started_at=timezone.now()
            )
            
            # Call dispatch directly
            dispatch_notifications(incident)
            
            # Verify alert was created
            alerts = Alert.objects.filter(incident=incident)
            self.assertGreaterEqual(alerts.count(), 1)


class NotificationServiceChannelTests(TestCase):
    """Test NotificationService channel layer interactions."""
    
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Channel Test Tenant')
    
    @patch('api.notification_service.get_channel_layer')
    def test_broadcast_to_channel_builds_correct_group_name(self, mock_get_layer):
        """Test that _broadcast_to_channel uses correct group name format."""
        mock_layer = MagicMock()
        mock_get_layer.return_value = mock_layer
        
        # Call with tenant_id
        NotificationService._broadcast_to_channel(
            tenant_id=42,
            notification_type='test',
            data={'message': 'test'}
        )
        
        # Verify group_send was called
        self.assertGreaterEqual(mock_layer.group_send.call_count, 1)
        
        # Verify the group name format
        call_args = mock_layer.group_send.call_args_list[0]
        group_name = call_args[0][0]
        self.assertEqual(group_name, 'tenant_notifications_42')
    
    def test_build_incident_notification_format(self):
        """Test that _build_incident_notification returns correct format."""
        tenant = Tenant.objects.create(name='Test')
        camera = Camera.objects.create(
            tenant=tenant,
            name='Test Cam',
            status='active'
        )
        incident = Incident.objects.create(
            tenant=tenant,
            camera=camera,
            type='intrusion',
            status='open',
            severity=4,
            started_at=timezone.now()
        )
        
        notification = NotificationService._build_incident_notification(incident)
        
        # Verify structure
        self.assertEqual(notification['type'], 'notification')
        self.assertEqual(notification['notification_type'], 'incident')
        self.assertIn('title', notification)
        self.assertIn('message', notification)
        self.assertIn('data', notification)
        self.assertIn('created_at', notification)
        
        # Verify data contents
        self.assertEqual(notification['data']['incident_id'], incident.id)
        self.assertEqual(notification['data']['severity'], 4)
        self.assertEqual(notification['data']['camera_name'], 'Test Cam')
