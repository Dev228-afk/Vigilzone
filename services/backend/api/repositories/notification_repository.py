from django.contrib.auth import get_user_model

from api.models import NotificationChannel, Profile, Tenant, normalize_instant_notification_levels

User = get_user_model()


class NotificationConfigRepository:
    def get_or_create_channel(self, *, tenant: Tenant) -> NotificationChannel:
        channel, _ = NotificationChannel.objects.get_or_create(tenant=tenant)
        return channel

    def update_channel(self, *, channel: NotificationChannel, attrs: dict) -> NotificationChannel:
        for key, value in attrs.items():
            setattr(channel, key, value)
        channel.save()
        return channel

    def get_or_create_profile(self, *, user: User) -> Profile:
        profile, _ = Profile.objects.get_or_create(user=user)
        return profile

    def set_instant_notification_levels(self, *, profile: Profile, levels: list[str]) -> Profile:
        profile.instant_notification_levels = normalize_instant_notification_levels(levels)
        profile.save(update_fields=["instant_notification_levels"])
        return profile

    def add_fcm_token(self, *, channel: NotificationChannel, token: str) -> NotificationChannel:
        tokens = list(channel.fcm_tokens or [])
        if token not in tokens:
            tokens.append(token)
            channel.fcm_tokens = tokens
            channel.save(update_fields=["fcm_tokens", "updated_at"])
        return channel
