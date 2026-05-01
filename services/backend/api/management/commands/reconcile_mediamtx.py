from django.core.management.base import BaseCommand
from api.services.relay_reconciler import RelayReconciler
import json


class Command(BaseCommand):
    help = "Runs a single MediaMTX relay reconciliation sweep (break-glass / migration tool)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--shadow",
            action="store_true",
            default=False,
            help="Shadow mode: verify and log drift without applying changes.",
        )

    def handle(self, *args, **options):
        shadow = options["shadow"]
        mode_label = "SHADOW" if shadow else "ACTIVE"
        self.stdout.write(f"Starting MediaMTX path reconciliation [{mode_label}]...")

        reconciler = RelayReconciler(shadow_mode=shadow)

        try:
            result = reconciler.reconcile_all()

            # Print cleanly formatted JSON summary
            self.stdout.write(json.dumps(result.as_dict(), indent=2))

            if result.failed > 0:
                self.stderr.write(self.style.WARNING(
                    f"\nReconciliation completed with {result.failed} failures."
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"\nReconciliation completed. "
                    f"{result.applied} applied, {result.removed} removed, "
                    f"{result.verified} verified."
                ))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Reconciliation completely failed: {str(e)}"))
