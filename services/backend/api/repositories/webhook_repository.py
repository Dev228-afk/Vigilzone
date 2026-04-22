from __future__ import annotations

from django.utils import timezone

from api.models import ServiceWebhook, Tenant


class WebhookRepository:
    def list_webhooks(self, *, tenant: Tenant | None = None):
        query = ServiceWebhook.objects.all().order_by("-updated_at")
        if tenant is not None:
            query = query.filter(tenant=tenant)
        return query

    def get_webhook(self, *, webhook_id: str) -> ServiceWebhook:
        return ServiceWebhook.objects.get(webhook_id=webhook_id)

    def upsert_webhook(
        self,
        *,
        webhook_id: str,
        url: str,
        events: list[str],
        tenant: Tenant | None = None,
        metadata: dict | None = None,
        delivery_stats: dict | None = None,
        active: bool = True,
        has_secret: bool = False,
        source: str = ServiceWebhook.Source.AI,
    ) -> ServiceWebhook:
        webhook, created = ServiceWebhook.objects.get_or_create(
            webhook_id=webhook_id,
            defaults={
                "tenant": tenant,
                "url": url,
                "events": list(events or []),
                "metadata": metadata or {},
                "delivery_stats": delivery_stats or {},
                "active": active,
                "has_secret": has_secret,
                "source": source,
                "last_synced_at": timezone.now(),
            },
        )
        if not created:
            webhook.tenant = tenant
            webhook.url = url
            webhook.events = list(events or [])
            webhook.metadata = metadata or {}
            webhook.delivery_stats = delivery_stats or {}
            webhook.active = active
            webhook.has_secret = has_secret
            webhook.source = source
            webhook.last_synced_at = timezone.now()
            webhook.save(
                update_fields=[
                    "tenant",
                    "url",
                    "events",
                    "metadata",
                    "delivery_stats",
                    "active",
                    "has_secret",
                    "source",
                    "last_synced_at",
                    "updated_at",
                ]
            )
        return webhook

    def delete_webhook(self, *, webhook_id: str) -> None:
        ServiceWebhook.objects.filter(webhook_id=webhook_id).delete()
