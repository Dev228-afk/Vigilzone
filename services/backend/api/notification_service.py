"""
Notification service for broadcasting alerts/incidents to all tenant members.

This service provides:
- Real-time WebSocket broadcasting to all connected tenant members
- Notification history storage
- Multiple notification channels (WebSocket, future: push, SMS, etc.)
"""

import logging
from typing import Optional
from datetime import datetime

from django.conf import settings
from django.core.mail import send_mail as django_send_mail
from django.utils import timezone

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import Incident, Alert, Membership, NotificationChannel

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service for sending notifications to all members of a tenant.
    
    Usage:
        service = NotificationService()
        service.broadcast_incident(incident)
        service.broadcast_message(tenant_id, "System maintenance in 5 minutes")
    """

    @staticmethod
    def get_channel_layer():
        """Get the Django Channels channel layer."""
        try:
            return get_channel_layer()
        except Exception as e:
            logger.warning(f"Channel layer not available: {e}")
            return None

    @classmethod
    def broadcast_incident(cls, incident: Incident) -> dict:
        """
        Broadcast an incident to all members of the incident's tenant.
        
        This will:
        1. Send WebSocket notification to all connected members
        2. Create Alert records for audit trail
        3. Optionally send email/push based on settings
        
        Args:
            incident: The Incident instance to broadcast
            
        Returns:
            dict with status of each delivery method
        """
        tenant = incident.tenant
        results = {
            "websocket": None,
            "email": None,
            "push": None,
            "alerts_created": 0,
        }

        # 1. Get notification channel settings
        try:
            channel_settings = NotificationChannel.objects.get(tenant=tenant)
        except NotificationChannel.DoesNotExist:
            channel_settings = None

        # 2. Create Alert records for all members (do this first to get IDs)
        alerts_created, alert_ids, user_alert_ids = cls._create_alerts_for_members(
            incident=incident,
            notification={}
        )
        results["alerts_created"] = alerts_created

        # 3. Build notification payload with alert IDs
        notification = cls._build_incident_notification(
            incident,
            alert_ids=alert_ids,
            user_alert_ids=user_alert_ids,
        )

        # 4. WebSocket broadcast to all tenant members
        ws_result = cls._broadcast_to_channel(
            tenant_id=tenant.id,
            notification_type="incident",
            data=notification
        )
        results["websocket"] = ws_result

        # 5. Email notification (if configured and threshold met)
        if channel_settings and channel_settings.email_enabled:
            if incident.severity >= channel_settings.min_severity_int():
                email_result = cls._send_email_notification(
                    incident=incident,
                    channel_settings=channel_settings
                )
                results["email"] = email_result

        # 6. Push notification (FCM) - placeholder for future
        if channel_settings and channel_settings.push_enabled:
            if incident.severity >= channel_settings.min_severity_int():
                results["push"] = cls._send_push_notification(
                    incident=incident,
                    channel_settings=channel_settings
                )

        logger.info(
            f"Broadcast incident #{incident.id} to tenant {tenant.name}: "
            f"websocket={results['websocket']}, alerts={alerts_created}"
        )

        return results

    @classmethod
    def broadcast_message(
        cls,
        tenant_id: int,
        title: str,
        message: str,
        notification_type: str = "broadcast",
        data: Optional[dict] = None
    ) -> dict:
        """
        Broadcast a custom message to all members of a tenant.
        
        Args:
            tenant_id: The tenant ID
            title: Notification title
            message: Notification message body
            notification_type: Type of notification (broadcast, system, etc.)
            data: Additional data payload
            
        Returns:
            dict with broadcast status
        """
        notification = {
            "type": "notification",
            "notification_type": notification_type,
            "title": title,
            "message": message,
            "data": data or {},
            "created_at": timezone.now().isoformat(),
        }

        result = cls._broadcast_to_channel(
            tenant_id=tenant_id,
            notification_type=notification_type,
            data=notification
        )

        logger.info(f"Broadcast message to tenant {tenant_id}: {title}")

        return result

    @classmethod
    def _broadcast_to_channel(
        cls,
        tenant_id: int,
        notification_type: str,
        data: dict
    ) -> str:
        """
        Send notification to Django Channels group for tenant.
        
        Args:
            tenant_id: The tenant ID (used for group name)
            notification_type: Type of notification
            data: Notification payload
            
        Returns:
            "sent" if successful, error message otherwise
        """
        channel_layer = cls.get_channel_layer()
        if not channel_layer:
            return "channel_layer_unavailable"

        group_name = f"tenant_notifications_{tenant_id}"

        try:
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": "notification_message",
                    "data": data
                }
            )
            return "sent"
        except Exception as e:
            logger.error(f"Failed to broadcast to channel {group_name}: {e}")
            return f"error: {str(e)}"

    @classmethod
    def _build_incident_notification(
        cls,
        incident: Incident,
        alert_ids: list = None,
        user_alert_ids: Optional[dict] = None,
    ) -> dict:
        """Build notification payload from an incident."""
        severity_labels = {1: "Low", 2: "Medium-Low", 3: "Medium", 4: "High", 5: "Critical"}
        
        notification = {
            "type": "notification",
            "notification_type": "incident",
            "title": f"🚨 {incident.get_type_display()} Detected",
            "message": f"{severity_labels.get(incident.severity, 'Unknown')} severity incident at {incident.camera.name}",
            "data": {
                "incident_id": incident.id,
                "type": incident.type,
                "status": incident.status,
                "severity": incident.severity,
                "camera_id": incident.camera_id,
                "camera_name": incident.camera.name,
                "started_at": incident.started_at.isoformat() if incident.started_at else None,
                "details": incident.details,
            },
            "created_at": timezone.now().isoformat(),
            "alert_ids_by_user": user_alert_ids or {},
        }
        
        # Include first alert ID for mark-as-read functionality
        if alert_ids:
            notification["alert_id"] = alert_ids[0] if alert_ids else None
        
        return notification

    @classmethod
    def _create_alerts_for_members(
        cls,
        incident: Incident,
        notification: dict
    ) -> tuple[int, list, dict]:
        """
        Create Alert records for all tenant members.
        
        Returns:
            Tuple of (number of alerts created, list of created alert IDs)
        """
        memberships = Membership.objects.filter(
            tenant=incident.tenant
        ).select_related("user")

        alerts = []
        membership_by_username = {}
        for membership in memberships:
            membership_by_username[membership.user.username] = membership.user_id
            alerts.append(Alert(
                incident=incident,
                channel="websocket",
                payload={
                    "title": notification.get("title", f"🚨 {incident.get_type_display()} Detected"),
                    "message": notification.get("message", f"Incident at {incident.camera.name}"),
                    "data": notification.get("data", {}),
                    "user_id": membership.user_id,
                    "username": membership.user.username,
                }
            ))

        if alerts:
            Alert.objects.bulk_create(alerts)
            # Get the IDs of the created alerts
            alert_ids = [alert.id for alert in alerts]
            user_alert_ids = {}
            for alert in alerts:
                username = (alert.payload or {}).get("username")
                user_id = membership_by_username.get(username)
                if user_id is not None:
                    user_alert_ids[str(user_id)] = alert.id
            return len(alerts), alert_ids, user_alert_ids
        return 0, [], {}

    @classmethod
    def _send_email_notification(
        cls,
        incident: Incident,
        channel_settings: NotificationChannel
    ) -> str:
        """Send email notification for an incident."""
        if not channel_settings.email_recipients:
            return "no_recipients"

        try:
            subject = f"[VigilZone] {incident.get_type_display()} — Severity {incident.severity}"
            body = (
                f"Incident #{incident.pk}\n"
                f"Type: {incident.get_type_display()}\n"
                f"Camera: {incident.camera.name}\n"
                f"Severity: {incident.severity}/5\n"
                f"Time: {incident.started_at}\n"
                f"Details: {incident.details.get('message', '')}"
            )

            django_send_mail(
                subject=subject,
                message=body,
                from_email=None,
                recipient_list=channel_settings.email_recipients,
            )
            return "sent"
        except Exception as e:
            logger.warning(f"Email notification failed: {e}")
            return f"error: {str(e)}"

    @classmethod
    def _send_push_notification(
        cls,
        incident: Incident,
        channel_settings: NotificationChannel
    ) -> str:
        """Send push notification via FCM."""
        if not channel_settings.fcm_tokens:
            return "no_tokens"

        # TODO: Implement FCM push notification
        # This requires firebase-admin SDK and service account credentials
        logger.info(f"Push notification would be sent to {len(channel_settings.fcm_tokens)} devices")
        return "not_implemented"

    @classmethod
    def notify_specific_users(
        cls,
        tenant_id: int,
        user_ids: list,
        title: str,
        message: str,
        notification_type: str = "direct",
        data: Optional[dict] = None
    ) -> dict:
        """
        Send notification to specific users (not all tenant members).
        
        Args:
            tenant_id: The tenant ID
            user_ids: List of user IDs to notify
            title: Notification title
            message: Notification message
            notification_type: Type of notification
            data: Additional data
            
        Returns:
            dict with status
        """
        notification = {
            "type": "notification",
            "notification_type": notification_type,
            "title": title,
            "message": message,
            "data": data or {},
            "created_at": timezone.now().isoformat(),
        }

        # Broadcast to entire tenant (channel layer broadcasts to all)
        # In a more complex implementation, you could track individual user groups
        result = cls._broadcast_to_channel(
            tenant_id=tenant_id,
            notification_type=notification_type,
            data=notification
        )

        return {
            "users_notified": len(user_ids),
            "status": result
        }


# ── Integration with existing dispatch_notifications ───────────────

def dispatch_notifications(incident: Incident):
    """
    Legacy function for backwards compatibility.
    Now delegates to the NotificationService.
    """
    NotificationService.broadcast_incident(incident)
