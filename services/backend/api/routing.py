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

websocket_urlpatterns = [
    re_path(r"^ws/notifications/$", consumers.NotificationConsumer.as_asgi()),
]
