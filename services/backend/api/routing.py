"""
WebSocket URL routing for the API app.

Add this to the project's URL configuration:
    from api.routing import websocket_urlpatterns
    from channels.routing import ProtocolTypeRouter, URLRouter

    application = ProtocolTypeRouter({
        "websocket": URLRouter(websocket_urlpatterns),
    })
"""

from django.urls import re_path
from . import consumers
from . import consumers_sse


websocket_urlpatterns = [
    re_path(r"ws/notifications/", consumers.NotificationConsumer.as_asgi()),
]

http_urlpatterns = [
    re_path(r"^/?api/notifications/stream/?$", consumers_sse.NotificationSSEConsumer.as_asgi()),
]
