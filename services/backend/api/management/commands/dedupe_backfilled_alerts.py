from collections import defaultdict

from django.core.management.base import BaseCommand

from api.models import Alert


def choose_alert_to_keep(alerts):
    read_alerts = [alert for alert in alerts if alert.delivered_at is not None]
    pool = read_alerts or alerts
    return max(
        pool,
        key=lambda alert: (
            alert.delivered_at.isoformat() if alert.delivered_at else "",
            alert.id,
        ),
    )


def collect_duplicate_backfilled_alerts():
    grouped = defaultdict(list)
    alerts = Alert.objects.filter(payload__backfilled=True).order_by("incident_id", "id")

    for alert in alerts:
        user_id = (alert.payload or {}).get("user_id")
        if user_id is None:
            continue
        grouped[(alert.incident_id, str(user_id))].append(alert)

    duplicates = []
    for (incident_id, user_id), items in grouped.items():
        if len(items) < 2:
            continue
        keep = choose_alert_to_keep(items)
        delete_ids = [alert.id for alert in items if alert.id != keep.id]
        duplicates.append({
            "incident_id": incident_id,
            "user_id": user_id,
            "keep_id": keep.id,
            "delete_ids": delete_ids,
        })
    return duplicates


class Command(BaseCommand):
    help = "Remove duplicate backfilled alerts, keeping one alert per incident/user pair."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview duplicate backfilled alerts without deleting them.",
        )

    def handle(self, *args, **options):
        duplicates = collect_duplicate_backfilled_alerts()
        delete_ids = [alert_id for item in duplicates for alert_id in item["delete_ids"]]

        if not duplicates:
            self.stdout.write(self.style.SUCCESS("No duplicate backfilled alerts found."))
            return

        self.stdout.write(
            f"Found {len(duplicates)} duplicate backfilled alert group(s), {len(delete_ids)} alert(s) eligible for deletion."
        )
        for item in duplicates:
            self.stdout.write(
                f"incident={item['incident_id']} user={item['user_id']} keep={item['keep_id']} delete={item['delete_ids']}"
            )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run only; no alerts were deleted."))
            return

        deleted, _ = Alert.objects.filter(id__in=delete_ids).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} duplicate backfilled alert(s)."))
