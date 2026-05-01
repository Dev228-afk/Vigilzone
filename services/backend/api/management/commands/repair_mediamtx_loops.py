"""
Management command to repair cameras with self-referential RTSP URLs.

These loopback URLs cause MediaMTX to try to pull from itself,
resulting in "connection actively refused" errors and socket exhaustion.

Usage:
    python manage.py repair_mediamtx_loops              # dry-run (default)
    python manage.py repair_mediamtx_loops --fix        # apply repairs
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from api.models import Camera, MediaMTXDesiredPath
from api.services.mediamtx_helpers import is_self_referential

logger = logging.getLogger("repair_mediamtx_loops")


class Command(BaseCommand):
    help = "Detect and repair cameras whose rtsp_url points back to our own MediaMTX relay."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix",
            action="store_true",
            default=False,
            help="Actually apply repairs. Without this flag, only a dry-run report is printed.",
        )

    def handle(self, *args, **options):
        apply_fix = options["fix"]
        mode = "FIX" if apply_fix else "DRY-RUN"
        self.stdout.write(f"[{mode}] Scanning for self-referential RTSP URLs...\n")

        cameras = Camera.objects.all()
        loopback_cameras: list[Camera] = []

        for camera in cameras:
            url = (camera.rtsp_url or "").strip()
            if url and is_self_referential(url):
                loopback_cameras.append(camera)

        if not loopback_cameras:
            self.stdout.write(self.style.SUCCESS("No self-referential URLs found. System is clean."))
            return

        self.stdout.write(self.style.WARNING(
            f"Found {len(loopback_cameras)} camera(s) with loopback URLs:"
        ))

        for camera in loopback_cameras:
            label = f"  [{camera.id}] {camera.name} (source_type={camera.source_type})"
            self.stdout.write(f"{label}")
            self.stdout.write(f"    rtsp_url = {camera.rtsp_url}")

            if apply_fix:
                old_url = camera.rtsp_url

                # Clear the self-referential URL.
                camera.rtsp_url = ""
                camera.save(update_fields=["rtsp_url", "updated_at"])

                # Also clear the source_uri in the desired path so the
                # reconciler picks up the change on its next sweep.
                desired = MediaMTXDesiredPath.objects.filter(camera=camera).first()
                if desired:
                    desired.source_uri = ""
                    desired.source_kind = ""
                    desired.path_generation = max(1, desired.path_generation + 1)
                    desired.save(update_fields=[
                        "source_uri", "source_kind", "path_generation", "updated_at",
                    ])

                self.stdout.write(self.style.SUCCESS(
                    f"    FIXED: cleared rtsp_url (was {old_url})"
                ))
            else:
                self.stdout.write(f"    ACTION: would clear rtsp_url")

        self.stdout.write("")
        if apply_fix:
            self.stdout.write(self.style.SUCCESS(
                f"Repaired {len(loopback_cameras)} camera(s). "
                "The relay reconciler will reconfigure MediaMTX on its next sweep."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"Re-run with --fix to apply repairs to {len(loopback_cameras)} camera(s)."
            ))
