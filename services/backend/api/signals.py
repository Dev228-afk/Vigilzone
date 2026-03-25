from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import Profile, Incident

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
    else:
        # only attempt to save if profile exists (avoid AttributeError)
        if hasattr(instance, "profile"):
            instance.profile.save()


@receiver(post_save, sender=Incident)
def broadcast_incident_notification(sender, instance, created, **kwargs):
    """
    Automatically broadcast notifications when an Incident is created.
    This ensures notifications are sent regardless of whether the incident
    was created via API (IncidentViewSet.perform_create) or Django admin.
    """
    if created:
        # Import here to avoid circular imports
        from .notification_service import NotificationService
        
        try:
            NotificationService.broadcast_incident(instance)
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to broadcast notification for incident {instance.pk}: {exc}")
