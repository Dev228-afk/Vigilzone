"""
Close stale incidents that have not received updates for a configurable duration.

Usage:
    python manage.py close_stale_incidents [--minutes 5]
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import Incident


class Command(BaseCommand):
    help = "Close OPEN incidents that have had no updates for --minutes (default 5)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=5,
            help="Minutes of inactivity before closing an incident (default: 5)",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options["minutes"])
        stale = Incident.objects.filter(
            status=Incident.Status.OPEN,
            updated_at__lt=cutoff,
        )
        count = stale.count()
        if count:
            stale.update(
                status=Incident.Status.RESOLVED,
                ended_at=timezone.now(),
            )
            self.stdout.write(self.style.SUCCESS(f"Closed {count} stale incident(s)."))
        else:
            self.stdout.write("No stale incidents.")
