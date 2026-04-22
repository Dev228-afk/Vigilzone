from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction

from api.models import Tenant, normalize_instant_notification_levels
from api.repositories.notification_repository import NotificationConfigRepository
from api.services.outbox_service import OutboxService

User = get_user_model()


class NotificationPolicyService:
    def __init__(
        self,
        repository: NotificationConfigRepository | None = None,
        outbox_service: OutboxService | None = None,
    ):
        self.repository = repository or NotificationConfigRepository()
        self.outbox_service = outbox_service or OutboxService()

    def get_notification_settings(self, *, tenant: Tenant, user: User):
        channel = self.repository.get_or_create_channel(tenant=tenant)
        profile = self.repository.get_or_create_profile(user=user)
        return {
            "channel": channel,
            "profile": profile,
            "instant_notification_levels": normalize_instant_notification_levels(
                profile.instant_notification_levels
            ),
        }

    @transaction.atomic
    def set_notification_settings(
        self,
        *,
        tenant: Tenant,
        user: User,
        channel_payload: dict,
        instant_levels: list[str] | None,
    ):
        channel = self.repository.get_or_create_channel(tenant=tenant)
        profile = self.repository.get_or_create_profile(user=user)

        if instant_levels is not None:
            profile = self.repository.set_instant_notification_levels(
                profile=profile,
                levels=instant_levels,
            )

        if channel_payload:
            channel = self.repository.update_channel(channel=channel, attrs=channel_payload)

        self.outbox_service.emit(
            aggregate_type="notification_policy",
            aggregate_id=f"{tenant.id}:{user.id}",
            event_type="notification_policy.updated",
            payload={
                "tenant_id": tenant.id,
                "user_id": user.id,
                "channel_updated": bool(channel_payload),
                "instant_levels_updated": instant_levels is not None,
            },
        )

        return {
            "channel": channel,
            "profile": profile,
            "instant_notification_levels": normalize_instant_notification_levels(
                profile.instant_notification_levels
            ),
        }

    @transaction.atomic
    def register_device_token(self, *, tenant: Tenant, token: str):
        channel = self.repository.get_or_create_channel(tenant=tenant)
        channel = self.repository.add_fcm_token(channel=channel, token=token)
        self.outbox_service.emit(
            aggregate_type="notification_channel",
            aggregate_id=tenant.id,
            event_type="notification.device_token_registered",
            payload={
                "tenant_id": tenant.id,
                "token_length": len(token),
            },
        )
        return channel
