import logging
import os
import threading

from django.apps import AppConfig

logger = logging.getLogger(__name__)


def _auto_register_webhook():
    """Best-effort webhook registration on startup (non-blocking)."""
    import time
    time.sleep(5)  # Give AI module time to boot

    import requests

    ai_base = os.getenv("AI_BASE_INTERNAL", "http://127.0.0.1:8080")
    public_url = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    webhook_secret = os.getenv("AI_WEBHOOK_SECRET", "")
    callback_url = f"{public_url}/api/ai/webhook/receive/"

    payload = {"url": callback_url, "events": ["alert.created"]}
    if webhook_secret:
        payload["secret"] = webhook_secret

    for attempt in range(3):
        try:
            resp = requests.post(f"{ai_base}/webhooks", json=payload, timeout=10)
            if resp.status_code in (200, 201):
                data = resp.json()
                logger.info(
                    "Auto-registered webhook with AI module: id=%s url=%s",
                    data.get("id", "?"),
                    callback_url,
                )
                return
            logger.warning("AI webhook registration returned %s: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.debug("Webhook registration attempt %d failed: %s", attempt + 1, e)
        time.sleep(5)

    logger.warning(
        "Could not auto-register webhook after 3 attempts. "
        "Run 'python manage.py register_ai_webhook' manually."
    )


class AiIntegrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ai_integration"
    verbose_name = "AI Integration"

    def ready(self):
        # Auto-register webhook in a background thread (non-blocking).
        # In local debug, default to off to avoid noisy retries when AI service is down.
        debug_mode = os.getenv("DJANGO_DEBUG", "1") not in ("0", "false", "False")
        auto_register = os.getenv("AI_AUTO_REGISTER_WEBHOOK")
        if auto_register is None:
            auto_register_enabled = not debug_mode
        else:
            auto_register_enabled = auto_register.lower() in ("1", "true", "yes")

        if auto_register_enabled and (os.getenv("RUN_MAIN") == "true" or not debug_mode):
            thread = threading.Thread(target=_auto_register_webhook, daemon=True)
            thread.start()
