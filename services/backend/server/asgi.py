"""
ASGI config for server project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
import logging

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

logger = logging.getLogger(__name__)


class SafeHttpAsgiApp:
    """Return a clean 503 when autoreload is shutting down the interpreter."""

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        try:
            return await self._app(scope, receive, send)
        except RuntimeError as exc:
            msg = str(exc)
            if "cannot schedule new futures after interpreter shutdown" not in msg:
                raise

            logger.info("Suppressing reload-time request during interpreter shutdown")
            await send({
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"detail":"Service restarting"}',
            })

from api.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": SafeHttpAsgiApp(django_asgi_app),
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                websocket_urlpatterns
            )
        )
    ),
})
