"""
Management command: generate_route_projection

Builds Redis routing projections from canonical Django data.
Phase 1 Workstream 1.2 — introduces cameractx, route, and reverse-index keys.

Usage:
    python manage.py generate_route_projection
"""

import json
import logging
import time
from datetime import datetime, timezone
from django.core.management.base import BaseCommand

from api.models import Tenant, Membership, Incident, Camera, NotificationChannel
from ai_integration.redis_queue import get_redis_client

logger = logging.getLogger(__name__)

# Incident types and severities to project routes for
INCIDENT_TYPES = [choice[0] for choice in Incident.Type.choices]
SEVERITIES = [1, 2, 3, 4, 5]


class Command(BaseCommand):
    help = "Generates Redis route projections for incident fan-out (Phase 1 Workstream 1.2)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print projection counts without writing to Redis",
        )

    def handle(self, *args, **options):
        self.stdout.write("Starting route projection generation...")
        start_time = time.time()
        dry_run = options.get("dry_run", False)

        redis_client = get_redis_client()

        # ── 1. Camera Context Projections ─────────────────────────────
        cameras = Camera.objects.all().select_related("tenant")
        cam_count = 0
        camera_community_index = {}  # community_id -> set of camera_ids

        for cam in cameras:
            cam_key = cam.ai_camera_id or cam.stream_path or str(cam.id)
            ctx_key = f"cameractx:{cam_key}"
            tenant_id_str = str(cam.tenant.id)

            ctx_value = {
                "tenant_id": tenant_id_str,
                "community_id": tenant_id_str,  # Currently tenant == community
                "camera_name": cam.name,
                "stream_path": cam.stream_path,
                "policy_version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            if not dry_run:
                redis_client.set(ctx_key, json.dumps(ctx_value))

            # Build reverse index: routeidx:camera:{camera_id} -> set of route keys
            camera_community_index.setdefault(tenant_id_str, set()).add(cam_key)
            cam_count += 1

        # ── 2. Route Projections ──────────────────────────────────────
        route_count = 0
        tenants = Tenant.objects.all()

        for tenant in tenants:
            tenant_id_str = str(tenant.id)

            # Fetch all members for this tenant (Membership has no is_active field)
            members = (
                Membership.objects
                .filter(tenant=tenant)
                .select_related("user", "user__profile")
            )

            # Check tenant-level notification channel settings
            try:
                channel_settings = NotificationChannel.objects.get(tenant=tenant)
                channel_min_severity = channel_settings.min_severity_int()
            except NotificationChannel.DoesNotExist:
                channel_settings = None
                channel_min_severity = 1  # Allow all by default

            # Collect route keys for the community reverse index
            community_route_keys = []

            for inc_type in INCIDENT_TYPES:
                for severity in SEVERITIES:
                    push_users = []
                    email_users = []
                    sms_users = []

                    for mem in members:
                        if not mem.user or not hasattr(mem.user, "profile"):
                            continue

                        profile = mem.user.profile
                        if profile.allows_instant_notification(severity):
                            user_id_str = str(mem.user.id)
                            push_users.append(user_id_str)

                            if getattr(profile, "notify_email", False):
                                email_users.append(user_id_str)
                            if getattr(profile, "notify_sms", False):
                                sms_users.append(user_id_str)

                    route_key = f"route:{tenant_id_str}:{tenant_id_str}:{inc_type}:{severity}"
                    route_value = {
                        "push": push_users,
                        "email": email_users,
                        "sms": sms_users,
                        "version": 1,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "policy_version": 1,
                    }

                    if not dry_run:
                        redis_client.set(route_key, json.dumps(route_value))

                    community_route_keys.append(route_key)
                    route_count += 1

            # ── 3. Reverse Index: routeidx:community:{community_id} ──
            if not dry_run and community_route_keys:
                community_idx_key = f"routeidx:community:{tenant_id_str}"
                redis_client.delete(community_idx_key)
                redis_client.sadd(community_idx_key, *community_route_keys)

            # ── 4. Reverse Index: routeidx:camera:{camera_id} ────────
            cam_keys_for_tenant = camera_community_index.get(tenant_id_str, set())
            if not dry_run:
                for cam_key in cam_keys_for_tenant:
                    cam_idx_key = f"routeidx:camera:{cam_key}"
                    redis_client.delete(cam_idx_key)
                    redis_client.sadd(cam_idx_key, *community_route_keys)

        elapsed_ms = (time.time() - start_time) * 1000
        msg = (
            f"{'[DRY RUN] ' if dry_run else ''}"
            f"Generated {cam_count} camera contexts and {route_count} routes "
            f"in {elapsed_ms:.1f}ms."
        )
        self.stdout.write(self.style.SUCCESS(msg))
        logger.info(msg)
