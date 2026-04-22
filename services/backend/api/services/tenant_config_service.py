from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction

from api.models import Membership, Tenant
from api.repositories.tenant_repository import TenantConfigRepository
from api.services.outbox_service import OutboxService

User = get_user_model()


class TenantConfigService:
    def __init__(
        self,
        repository: TenantConfigRepository | None = None,
        outbox_service: OutboxService | None = None,
    ):
        self.repository = repository or TenantConfigRepository()
        self.outbox_service = outbox_service or OutboxService()

    @transaction.atomic
    def create_tenant_with_owner(self, *, user: User, name: str, plan: str = "free") -> Tenant:
        tenant = self.repository.create_tenant(name=name, plan=plan)
        membership = self.repository.ensure_membership(
            tenant=tenant,
            user=user,
            role=Membership.Role.OWNER,
        )
        self.repository.ensure_tenant_runtime_settings(tenant=tenant)
        self.repository.ensure_notification_channel(tenant=tenant)
        self.outbox_service.emit(
            aggregate_type="tenant",
            aggregate_id=tenant.id,
            event_type="tenant.created",
            payload={
                "tenant_id": tenant.id,
                "owner_user_id": user.id,
                "membership_id": membership.id,
                "plan": tenant.plan,
            },
        )
        return tenant

    @transaction.atomic
    def ensure_tenant_defaults(self, *, tenant: Tenant) -> None:
        self.repository.ensure_tenant_runtime_settings(tenant=tenant)
        self.repository.ensure_notification_channel(tenant=tenant)

    @transaction.atomic
    def ensure_membership(self, *, tenant: Tenant, user: User, role: str) -> Membership:
        membership = self.repository.ensure_membership(tenant=tenant, user=user, role=role)
        self.outbox_service.emit(
            aggregate_type="membership",
            aggregate_id=membership.id,
            event_type="membership.upserted",
            payload={
                "tenant_id": tenant.id,
                "user_id": user.id,
                "role": membership.role,
            },
        )
        return membership
