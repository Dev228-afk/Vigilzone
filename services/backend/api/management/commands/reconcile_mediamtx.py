from django.core.management.base import BaseCommand
from api.views import reconcile_all_cameras_to_mediamtx
import json

class Command(BaseCommand):
    help = "Replays all database camera RTSP sources into MediaMTX path configurations."

    def handle(self, *args, **options):
        self.stdout.write("Starting MediaMTX path reconciliation...")
        
        try:
            summary = reconcile_all_cameras_to_mediamtx()
            
            # Print cleanly formatted JSON summary
            self.stdout.write(json.dumps(summary, indent=2))
            
            if summary["failed"] > 0:
                self.stderr.write(self.style.WARNING(f"\nReconciliation completed with {summary['failed']} failures."))
            else:
                self.stdout.write(self.style.SUCCESS(f"\nReconciliation completed successfully. {summary['success']} paths provisioned."))
                
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Reconciliation completely failed: {str(e)}"))
