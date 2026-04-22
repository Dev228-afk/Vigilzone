from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from api.models import Camera, Tenant
from api.services.bootstrap_service import BootstrapService


class Command(BaseCommand):
    help = (
        "Install and run idempotent canonical-config bootstrap tasks "
        "for PostgreSQL-backed deployments."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-migration-check",
            action="store_true",
            help="Skip pending migration validation before bootstrap.",
        )

    def handle(self, *args, **options):
        if not options["skip_migration_check"]:
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes()
            plan = executor.migration_plan(targets)
            if plan:
                raise CommandError(
                    "Pending migrations detected. Apply migrations before bootstrap_postgres_config."
                )

        bootstrap_service = BootstrapService()

        postgres_objects_installed = bootstrap_service.install_postgres_objects()
        self.stdout.write(
            self.style.NOTICE(
                f"Postgres objects installed: {'yes' if postgres_objects_installed else 'no'}"
            )
        )

        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT ops.bootstrap_system_defaults()")
                for tenant_id in Tenant.objects.values_list("id", flat=True):
                    cursor.execute("SELECT ops.ensure_tenant_defaults(%s)", [tenant_id])
                for camera_id in Camera.objects.values_list("id", flat=True):
                    cursor.execute("SELECT ops.ensure_camera_sidecars(%s)", [camera_id])

        summary = bootstrap_service.bootstrap_defaults()
        self.stdout.write(
            self.style.SUCCESS(
                "Bootstrap complete: "
                f"tenants={summary['tenants_bootstrapped']} "
                f"cameras={summary['cameras_bootstrapped']}"
            )
        )
