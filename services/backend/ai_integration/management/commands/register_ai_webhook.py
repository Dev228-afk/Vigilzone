"""
Register the Django webhook receiver with the AI module.

Usage:
    python manage.py register_ai_webhook

Environment:
    AI_BASE_INTERNAL  – AI module URL (default: http://ai:8080)
    PUBLIC_BASE_URL   – Public base URL (default: http://localhost:8085)
    AI_WEBHOOK_SECRET – Optional HMAC secret for webhook signature verification
"""
import os

import requests
from django.core.management.base import BaseCommand

from api.models import ServiceWebhook
from api.services.webhook_registry_service import WebhookRegistryService


class Command(BaseCommand):
    help = "Register the Django webhook endpoint with the AI FastAPI module"

    def handle(self, *args, **options):
        webhook_service = WebhookRegistryService()
        ai_base = os.getenv("AI_BASE_INTERNAL", "http://ai:8080")
        public_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8085")
        webhook_secret = os.getenv("AI_WEBHOOK_SECRET", "")
        callback_url = f"{public_url}/api/ai/webhook/receive/"

        self.stdout.write(f"Registering webhook with AI at {ai_base}...")
        self.stdout.write(f"Callback URL: {callback_url}")
        if webhook_secret:
            self.stdout.write("HMAC secret: configured (will send X-Vigilzone-Signature)")

        payload = {
            "url": callback_url,
            "events": ["alert.created"],
        }
        if webhook_secret:
            payload["secret"] = webhook_secret

        try:
            resp = requests.post(
                f"{ai_base}/webhooks",
                json=payload,
                timeout=10,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                webhook_id = data.get("id", "")
                if webhook_id:
                    webhook_service.register_webhook(
                        webhook_id=webhook_id,
                        url=callback_url,
                        events=list(payload.get("events") or []),
                        active=True,
                        has_secret=bool(webhook_secret),
                        source=ServiceWebhook.Source.BACKEND,
                        metadata={"managed_by": "register_ai_webhook"},
                    )
                self.stdout.write(
                    self.style.SUCCESS(f"Webhook registered! ID: {data.get('id', 'n/a')}")
                )
            else:
                self.stderr.write(
                    self.style.ERROR(f"AI returned {resp.status_code}: {resp.text}")
                )
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Failed to reach AI module: {e}"))
