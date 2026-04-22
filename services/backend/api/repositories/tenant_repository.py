from django.contrib.auth import get_user_model

from api.models import Membership, NotificationChannel, Tenant, TenantRuntimeSetting

User = get_user_model()


class TenantConfigRepository:
    def get_tenant(self, tenant_id: int) -> Tenant:
        return Tenant.objects.get(pk=tenant_id)

    def create_tenant(self, *, name: str, plan: str = "free") -> Tenant:
        return Tenant.objects.create(name=name, plan=plan)

    def ensure_membership(self, *, tenant: Tenant, user: User, role: str) -> Membership:
        membership, _ = Membership.objects.get_or_create(
            tenant=tenant,
            user=user,
            defaults={"role": role},
        )
        if membership.role != role:
            membership.role = role
            membership.save(update_fields=["role", "updated_at"])
        return membership

    def ensure_tenant_runtime_settings(self, *, tenant: Tenant) -> TenantRuntimeSetting:
        runtime_settings, _ = TenantRuntimeSetting.objects.get_or_create(tenant=tenant)
        return runtime_settings

    def ensure_notification_channel(self, *, tenant: Tenant) -> NotificationChannel:
        channel, _ = NotificationChannel.objects.get_or_create(tenant=tenant)
        return channel
