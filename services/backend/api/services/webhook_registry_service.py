from __future__ import annotations

from django.db import transaction

from api.models import ServiceWebhook, Tenant
from api.repositories.webhook_repository import WebhookRepository
from api.services.outbox_service import OutboxService


class WebhookRegistryService:
    def __init__(
        self,
        repository: WebhookRepository | None = None,
        outbox_service: OutboxService | None = None,
    ):
        self.repository = repository or WebhookRepository()
        self.outbox_service = outbox_service or OutboxService()

    def list_webhooks(self, *, tenant: Tenant | None = None):
        return self.repository.list_webhooks(tenant=tenant)

    @transaction.atomic
    def register_webhook(
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
        webhook = self.repository.upsert_webhook(
            webhook_id=webhook_id,
            url=url,
            events=events,
            tenant=tenant,
            metadata=metadata,
            delivery_stats=delivery_stats,
            active=active,
            has_secret=has_secret,
            source=source,
        )
        self.outbox_service.emit(
            aggregate_type="service_webhook",
            aggregate_id=webhook.webhook_id,
            event_type="webhook.upserted",
            payload={
                "tenant_id": webhook.tenant_id,
                "webhook_id": webhook.webhook_id,
                "url": webhook.url,
                "events": list(webhook.events or []),
                "active": bool(webhook.active),
                "source": webhook.source,
            },
        )
        return webhook

    @transaction.atomic
    def update_webhook(self, **kwargs) -> ServiceWebhook:
        return self.register_webhook(**kwargs)

    @transaction.atomic
    def delete_webhook(self, *, webhook_id: str) -> None:
        self.repository.delete_webhook(webhook_id=webhook_id)
        self.outbox_service.emit(
            aggregate_type="service_webhook",
            aggregate_id=webhook_id,
            event_type="webhook.deleted",
            payload={"webhook_id": webhook_id},
        )

    @transaction.atomic
    def sync_from_ai_registry(self, *, webhooks: dict, tenant: Tenant | None = None) -> int:
        synced = 0
        for webhook_id, payload in (webhooks or {}).items():
            if not isinstance(payload, dict):
                continue
            self.repository.upsert_webhook(
                webhook_id=webhook_id,
                url=str(payload.get("url", "")).strip(),
                events=list(payload.get("events") or []),
                tenant=tenant,
                metadata=payload.get("metadata") or {},
                delivery_stats=payload.get("delivery_stats") or {},
                active=bool(payload.get("active", True)),
                has_secret=bool(payload.get("secret")),
                source=ServiceWebhook.Source.AI,
            )
            synced += 1
        if synced:
            self.outbox_service.emit(
                aggregate_type="service_webhook",
                aggregate_id=tenant.id if tenant is not None else "global",
                event_type="webhook.synced",
                payload={
                    "tenant_id": tenant.id if tenant is not None else None,
                    "count": synced,
                },
            )
        return synced
