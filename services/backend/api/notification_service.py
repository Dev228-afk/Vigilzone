"""
Notification service for broadcasting alerts/incidents to all tenant members.

This service provides:
- Real-time WebSocket broadcasting to all connected tenant members
- Notification history storage
- Multiple notification channels (WebSocket, future: push, SMS, etc.)
"""

import logging
from typing import Optional, Tuple, List, Dict
from datetime import datetime

from django.conf import settings
from django.core.mail import send_mail as django_send_mail
from django.utils import timezone

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import Incident, Alert, Membership, NotificationChannel, severity_level_for_value

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service for sending notifications to all members of a tenant.
    
    Usage:
        from .notification_service import NotificationService
        from django.db import transaction

        transaction.on_commit(lambda: NotificationService.broadcast_incident(instance))
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

        # 2. Build notification payload
        notification = cls._build_incident_notification(incident)

        # 3. Create alert records (obtaining IDs for user-specific routing)
        count, alert_ids, user_map = cls._create_alerts_for_members(incident, notification)
        results["alerts_created"] = count
        
        # 4. Build the WebSocket event payload
        event_payload = {
            **notification,
            "alert_ids_by_user": user_map, # Key: user_id, Value: alert_id (for consumers.py)
        }

        # 5. Request broadcast via channel layer
        ws_result = cls._broadcast_to_channel(
            tenant_id=tenant.id,
            notification_type="incident",
            data=event_payload
        )
        results["websocket"] = ws_result

        # 6. Email notification (if configured and threshold met)
        if channel_settings and channel_settings.email_enabled:
            if incident.severity >= channel_settings.min_severity_int():
                email_result = cls._send_email_notification(
                    incident=incident,
                    channel_settings=channel_settings
                )
                results["email"] = email_result

        # 7. Push notification (FCM) - placeholder for future
        if channel_settings and channel_settings.push_enabled:
            if incident.severity >= channel_settings.min_severity_int():
                results["push"] = cls._send_push_notification(
                    incident=incident,
                    channel_settings=channel_settings
                )

        logger.info(
            f"Broadcast incident #{incident.id} to tenant {tenant.name}: "
            f"websocket={results['websocket']}, alerts={count}"
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
        group_name = f"tenant_notifications_{tenant_id}"
        
        # On Windows, async_to_sync(channel_layer.group_send) often deadlocks when run
        # inside synchronous management commands (like subscribe_incidents) 
        # or synchronous webhooks. We bypass it by natively publishing to the Redis backend.
        import sys
        if sys.platform == "win32":
            try:
                import redis
                import msgpack
                import time
                import secrets
                from server.redis_runtime import resolve_backend_redis_settings
                
                settings = resolve_backend_redis_settings()
                if settings.url:
                    client = redis.from_url(settings.url)
                else:
                    client = redis.Redis(
                        host=settings.host,
                        port=settings.port,
                        db=settings.db,
                        password=settings.password or None,
                        socket_timeout=5
                    )
                
                # channels_redis encodes groups internally with prefix "asgi" and single colon
                prefix = "asgi"
                group_key = f"{prefix}:group:{group_name}"
                channels = client.zrange(group_key, 0, -1)
                
                if not channels:
                    logger.debug(f"Direct push skipped: No channels in group {group_name}")
                    return "sent"
                    
                for channel_bytes in channels:
                    channel_name = channel_bytes.decode("utf-8")
                    
                    # Resolve Redis key for this channel (handled identical to channels_redis)
                    non_local = channel_name
                    if "!" in channel_name:
                        non_local = channel_name.split("!")[0] + "!"
                    channel_key = prefix + non_local
                    
                    # Build message identical to channels_redis group_send output
                    msg = {
                        "__asgi_channel__": [channel_name], 
                        "type": "notification_message", 
                        "data": data
                    }
                    # channels_redis prepends 12 random bytes to every msgpack payload
                    packed = msgpack.packb(msg)
                    payload = secrets.token_bytes(12) + packed
                    
                    # Channels redis pushes to a specific channel's zset
                    client.zadd(channel_key, {payload: time.time()})
                    client.expire(channel_key, 60)
                    
                logger.info(f"Direct push succeeded for group {group_name} to {len(channels)} channels via pure sync.")
                return "sent"
            except Exception as e:
                logger.error(f"Failed direct synchronous Redis push for group {group_name}: {e}")
                # Fall through to default channel_layer just in case
                pass

        channel_layer = cls.get_channel_layer()
        if not channel_layer:
            return "channel_layer_unavailable"

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
        incident: Incident
    ) -> dict:
        """Build notification payload from an incident."""
        severity_labels = {1: "Low", 2: "Medium-Low", 3: "Medium", 4: "High", 5: "Critical"}
        
        severity_level = severity_level_for_value(incident.severity)
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
                "severity_level": severity_level,
                "camera_id": incident.camera_id,
                "camera_name": incident.camera.name,
                "stream_path": getattr(incident.camera, 'stream_path', None),
                "started_at": incident.started_at.isoformat() if incident.started_at else None,
                "details": incident.details,
            },
            "severity": incident.severity,
            "severity_level": severity_level,
            "created_at": timezone.now().isoformat(),
        }
        
        return notification

    @classmethod
    def _create_alerts_for_members(cls, incident: Incident, notification: dict) -> Tuple[int, List[int], Dict[int, int]]:
        """
        Creates Alert records for all members of the tenant.
        Returns (count, alert_ids, user_to_alert_map).
        
        Note: On SQLite, bulk_create with return_objects=True does not return 
        primary keys. We use individual saves here for reliability in dev environments.
        """
        members = Membership.objects.filter(tenant=incident.tenant).select_related("user", "user__profile")
        
        alert_ids = []
        user_to_alert_map = {}
        
        # We perform individual saves to ensure we get IDs back for WebSocket routing
        # In high-volume production, this would be optimized or moved to a task queue
        for member in members:
            # Check preferences
            if not member.user.profile.allows_instant_notification(incident.severity):
                continue

            alert = Alert(
                incident=incident,
                channel="websocket",
                payload={
                    "title": f"🚨 {incident.get_type_display()} Detected",
                    "message": f"{incident.camera.name}: {incident.get_type_display()} alert",
                    "data": notification.get("data", {}),
                    "alert_id": None, # Will be set after save
                    "user_id": member.user.id,
                    "username": member.user.username
                }
            )
            alert.save()
            alert.payload["alert_id"] = alert.id
            alert.save(update_fields=["payload"])
            
            alert_ids.append(alert.id)
            user_to_alert_map[member.user.id] = alert.id
            
        return len(alert_ids), alert_ids, user_to_alert_map

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
