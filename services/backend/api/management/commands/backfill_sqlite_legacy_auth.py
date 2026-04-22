from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Legacy SQLite auth backfill has been removed."

    def handle(self, *args, **options):
        raise CommandError(
            "backfill_sqlite_legacy_auth is no longer supported. "
            "Local SQLite backfill has been retired to enforce canonical PostgreSQL-only operation."
        )
