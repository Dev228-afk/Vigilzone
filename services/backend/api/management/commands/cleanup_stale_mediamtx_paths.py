"""
One-time management command to clean up stale MediaMTX paths
that have no corresponding active MediaMTXDesiredPath row.

Fixes paths that accumulated before the SET_NULL FK migration.
"""
import logging

import requests

from django.core.management.base import BaseCommand

from api.models import MediaMTXDesiredPath
from api.services.mediamtx_helpers import get_mediamtx_api_base

logger = logging.getLogger("cleanup_stale_mediamtx_paths")


class Command(BaseCommand):
    help = "Remove stale MediaMTX paths that have no matching MediaMTXDesiredPath row."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="List stale paths without removing them.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        api_base = get_mediamtx_api_base()

        # Fetch all paths from MediaMTX
        try:
            resp = requests.get(f"{api_base}/v3/config/paths/list", timeout=10)
            resp.raise_for_status()
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Failed to list MediaMTX paths: {exc}"))
            return

        data = resp.json()
        # MediaMTX v1.x returns {"items": [...]} or {"paths": {...}}
        if "items" in data:
            mtx_paths = {item.get("name", "") for item in data["items"] if item.get("name")}
        elif "paths" in data:
            mtx_paths = set(data["paths"].keys())
        else:
            # Fallback: try to extract path names from top-level keys
            mtx_paths = set()
            self.stderr.write(self.style.WARNING(f"Unexpected MediaMTX response shape: {list(data.keys())}"))

        if not mtx_paths:
            self.stdout.write(self.style.SUCCESS("No paths found in MediaMTX. Nothing to clean."))
            return

        # Get all active desired paths from Postgres
        desired_stream_paths = set(
            MediaMTXDesiredPath.objects
            .filter(desired_enabled=True)
            .values_list("stream_path", flat=True)
        )

        # Find orphans: in MediaMTX but not in desired state
        # Exclude _probe_ paths (temporary test paths that should self-clean)
        stale_paths = {
            p for p in mtx_paths
            if p not in desired_stream_paths and not p.startswith("_probe_")
        }

        if not stale_paths:
            self.stdout.write(self.style.SUCCESS("No stale paths found. All clean."))
            return

        self.stdout.write(f"Found {len(stale_paths)} stale path(s):")
        for p in sorted(stale_paths):
            self.stdout.write(f"  - {p}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes made."))
            return

        removed = 0
        for path_name in sorted(stale_paths):
            try:
                del_resp = requests.delete(
                    f"{api_base}/v3/config/paths/delete/{path_name}",
                    timeout=5,
                )
                if del_resp.status_code in (200, 404):
                    self.stdout.write(self.style.SUCCESS(f"  Removed: {path_name}"))
                    removed += 1
                else:
                    self.stdout.write(self.style.ERROR(
                        f"  Failed to remove {path_name}: HTTP {del_resp.status_code}"
                    ))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  Error removing {path_name}: {exc}"))

        self.stdout.write(self.style.SUCCESS(f"\nDone. Removed {removed}/{len(stale_paths)} stale paths."))
