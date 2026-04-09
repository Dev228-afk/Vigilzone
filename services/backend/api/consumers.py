"""
WebSocket consumers for real-time notifications.

Handles:
- User authentication via JWT tokens
- Tenant-based channel subscriptions
- Real-time incident/alert broadcasting
"""

import json
import logging
from typing import Optional

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from django.db.models import Q
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from .models import Tenant, Membership

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time tenant notifications.
    
    Connection URL: ws://host/ws/notifications/
    
    On connect:
    1. Authenticate via JWT token in query string or headers
    2. Get tenant_id from query string
    3. Join the tenant's notification group
    
    Message format (send to client):
    {
        "type": "notification",
        "notification_type": "incident",  # incident, alert, broadcast
        "title": "New Incident Detected",
        "message": "Motion detected at Front Door camera",
        "data": {
            "incident_id": 123,
            "severity": 4,
            "camera_name": "Front Door",
            "timestamp": "2026-03-24T10:20:00Z"
        },
        "created_at": "2026-03-24T10:20:00Z"
    }
    
    On disconnect:
    - Leave tenant group
    """

    async def connect(self):
        """Handle WebSocket connection."""
        self.user = None
        self.tenant_id: Optional[int] = None
        self.group_name: Optional[str] = None
        self.user_identifier: Optional[str] = None

        # Authenticate user
        if not await self.authenticate_user():
            logger.warning("WebSocket connection rejected: authentication failed")
            await self.close(code=4001)
            return

        # Get tenant from query string
        self.tenant_id = self.get_tenant_from_query()
        if not self.tenant_id:
            logger.warning("WebSocket connection rejected: no tenant_id provided")
            await self.close(code=4002)
            return

        # Verify user is member of tenant
        if not await self.verify_tenant_membership():
            logger.warning(f"WebSocket connection rejected: user not member of tenant {self.tenant_id}")
            await self.close(code=4003)
            return

        # Join tenant notification group
        self.group_name = f"tenant_notifications_{self.tenant_id}"
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()
        
        # Send welcome message
        await self.send(text_data=json.dumps({
            "type": "connection_established",
            "message": f"Connected to tenant {self.tenant_id} notifications",
            "tenant_id": self.tenant_id
        }))

        logger.info(f"User {self.user.username} connected to tenant {self.tenant_id} notifications")

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if self.group_name:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
            logger.info(f"User disconnected from tenant {self.tenant_id} notifications")

    async def receive(self, text_data=None, bytes_data=None):
        """
        Handle incoming WebSocket messages from client.
        Currently supports:
        - ping/pong for keep-alive
        - mark_read notifications
        """
        if not text_data:
            return

        try:
            data = json.loads(text_data)
            message_type = data.get("type", "")

            if message_type == "ping":
                await self.send(text_data=json.dumps({
                    "type": "pong"
                }))

            elif message_type == "mark_read":
                # Client acknowledges notification receipt
                notification_ids = data.get("notification_ids", [])
                if notification_ids:
                    await self.mark_notifications_read(notification_ids)

            elif message_type == "subscribe":
                # Allow dynamic tenant subscription
                new_tenant_id = data.get("tenant_id")
                if new_tenant_id and new_tenant_id != self.tenant_id:
                    # Leave old group
                    if self.group_name:
                        await self.channel_layer.group_discard(
                            self.group_name,
                            self.channel_name
                        )
                    
                    # Join new group
                    self.tenant_id = new_tenant_id
                    if await self.verify_tenant_membership():
                        self.group_name = f"tenant_notifications_{self.tenant_id}"
                        await self.channel_layer.group_add(
                            self.group_name,
                            self.channel_name
                        )
                        await self.send(text_data=json.dumps({
                            "type": "subscribed",
                            "tenant_id": self.tenant_id
                        }))

        except json.JSONDecodeError:
            logger.warning("Received invalid JSON from client")
        except Exception as e:
            logger.error(f"Error processing client message: {e}")

    # ── Channel message handlers ───────────────────────────────

    async def notification_message(self, event):
        """
        Catches the 'notification_message' event broadcasted by Redis 
        and pushes it down the WebSocket to the React frontend.
        """
        # 'event' is the exact dictionary we sent in notification_service.py
        message_data = event.get("data", {})
        
        # Send the payload to the browser
        import json
        await self.send(text_data=json.dumps(message_data))

    async def broadcast_message(self, event):
        """
        Handler for general broadcasts (e.g., system announcements).
        """
        await self.send(text_data=json.dumps(event["data"]))

    # ── Authentication & Authorization ───────────────────────

    async def authenticate_user(self) -> bool:
        """Authenticate user from JWT token in query string or headers."""
        # Try query string first
        token = self.scope.get("query_string", b"").decode()
        if token:
            # Parse token from query string
            for param in token.split("&"):
                if param.startswith("token="):
                    token = param[6:]  # Remove "token="
                    break
        
        # Also check headers
        if not token or token == "null":
            headers = dict(self.scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token or token == "null":
            return False

        try:
            # Validate JWT token
            access_token = AccessToken(token)
            user_id = access_token.get("user_id")
            
            if not user_id:
                return False

            # Get user from database
            self.user = await self.get_user_by_id(user_id)
            return self.user is not None

        except (TokenError, InvalidToken) as e:
            logger.debug(f"JWT validation failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    @database_sync_to_async
    def get_user_by_id(self, user_id: int):
        """Get user from database."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    def get_tenant_from_query(self) -> Optional[int]:
        """Extract tenant_id from query string."""
        query_string = self.scope.get("query_string", b"").decode()
        for param in query_string.split("&"):
            if param.startswith("tenant_id="):
                try:
                    return int(param.split("=")[1])
                except (ValueError, IndexError):
                    pass
        return None

    @database_sync_to_async
    def verify_tenant_membership(self) -> bool:
        """Verify user is a member of the specified tenant."""
        if not self.user or not self.tenant_id:
            return False
        
        return Membership.objects.filter(
            user=self.user,
            tenant_id=self.tenant_id
        ).exists()

    @database_sync_to_async
    def mark_notifications_read(self, notification_ids: list):
        """Mark notifications as read for the user."""
        from .models import Alert
        Alert.objects.filter(
            id__in=notification_ids,
            incident__tenant_id=self.tenant_id,
        ).filter(
            Q(payload__user_id=self.user.id) | Q(payload__user_id=str(self.user.id))
        ).update(delivered_at=timezone.now())


# Import at module level to avoid circular imports
import django
