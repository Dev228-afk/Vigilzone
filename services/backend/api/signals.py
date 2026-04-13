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

    Uses ``transaction.on_commit`` because ``broadcast_incident()`` pushes
    to the channel layer inline (it no longer wraps with its own on_commit).
    """
    if created:
        if getattr(instance, "_skip_broadcast_notification", False):
            return

        from django.db import transaction

        incident_id = instance.pk

        def _broadcast():
            from .notification_service import NotificationService
            try:
                inc = Incident.objects.select_related("tenant", "camera").get(pk=incident_id)
                NotificationService.broadcast_incident(inc)
            except Incident.DoesNotExist:
                import logging
                logging.getLogger(__name__).warning(
                    "Incident %s disappeared before notification dispatch", incident_id
                )
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to broadcast notification for incident %s: %s", incident_id, exc
                )

        transaction.on_commit(_broadcast)
