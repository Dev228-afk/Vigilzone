import json
import os
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import BackfillCheckpoint, Camera, CameraZone, SchemaBootstrapState, Tenant
from api.services.camera_config_service import CameraConfigService
from api.services.runtime_registration_service import RuntimeRegistrationService
from api.services.webhook_registry_service import WebhookRegistryService


def _coerce_sample_hz(raw, default: float = 2.0) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, dict):
        detector_hz = raw.get("detector")
        if isinstance(detector_hz, (int, float)):
            return float(detector_hz)
    return float(default)


class Command(BaseCommand):
    help = (
        "Backfill AI file-based config/runtime state into canonical Postgres-backed "
        "tables while keeping legacy files untouched."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--ai-root",
            default="",
            help="Path to services/ai directory. Defaults to repository services/ai.",
        )
        parser.add_argument(
            "--tenant-id",
            type=int,
            default=0,
            help="Tenant id to use for creating missing cameras.",
        )
        parser.add_argument(
            "--create-missing-cameras",
            action="store_true",
            help="Create missing cameras for runtime/yaml entries when not found.",
        )

    def _resolve_ai_root(self, explicit_root: str) -> Path:
        if explicit_root:
            return Path(explicit_root).resolve()
        return (Path(__file__).resolve().parents[4] / "ai").resolve()

    def _resolve_default_tenant(self, tenant_id: int) -> Tenant | None:
        if tenant_id:
            return Tenant.objects.filter(pk=tenant_id).first()

        env_tenant = os.getenv("DEFAULT_AI_TENANT_ID", "").strip()
        if env_tenant.isdigit():
            tenant = Tenant.objects.filter(pk=int(env_tenant)).first()
            if tenant is not None:
                return tenant

        return Tenant.objects.order_by("id").first()

    def _resolve_camera(self, camera_id: str, tenant: Tenant | None) -> Camera | None:
        token = str(camera_id or "").strip()
        if not token:
            return None

        query = Camera.objects.all()
        if tenant is not None:
            query = query.filter(tenant=tenant)

        camera = query.filter(ai_camera_id=token).first()
        if camera:
            return camera
        camera = query.filter(stream_path=token).first()
        if camera:
            return camera
        camera = query.filter(name=token).first()
        return camera

    @transaction.atomic
    def handle(self, *args, **options):
        ai_root = self._resolve_ai_root(options["ai_root"])
        if not ai_root.exists():
            raise CommandError(f"AI root not found: {ai_root}")

        tenant = self._resolve_default_tenant(options["tenant_id"])
        create_missing = bool(options["create_missing_cameras"])

        camera_service = CameraConfigService()
        runtime_service = RuntimeRegistrationService()
        webhook_service = WebhookRegistryService()

        counts = {
            "webhooks_synced": 0,
            "runtime_rows_synced": 0,
            "camera_rows_updated": 0,
            "zones_rows_upserted": 0,
            "policy_rows_synced": 0,
            "missing_camera_entries": 0,
        }

        runtime_path = ai_root / "data" / "cameras_runtime.json"
        webhooks_path = ai_root / "data" / "webhooks.json"
        cameras_yaml_path = ai_root / "configs" / "cameras.yaml"
        zones_yaml_path = ai_root / "configs" / "zones.yaml"
        policy_yaml_path = ai_root / "configs" / "policy.yaml"

        if webhooks_path.exists():
            try:
                webhook_payload = json.loads(webhooks_path.read_text(encoding="utf-8"))
                if isinstance(webhook_payload, dict):
                    counts["webhooks_synced"] = webhook_service.sync_from_ai_registry(
                        webhooks=webhook_payload,
                        tenant=tenant,
                    )
            except Exception as exc:
                raise CommandError(f"Failed to process {webhooks_path}: {exc}")

            BackfillCheckpoint.objects.update_or_create(
                source_key="ai.webhooks.json",
                defaults={
                    "status": "completed",
                    "stats": {"webhooks_synced": counts["webhooks_synced"]},
                },
            )

        runtime_payload: dict = {}
        if runtime_path.exists():
            try:
                loaded_runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
                if isinstance(loaded_runtime, dict):
                    runtime_payload = loaded_runtime
            except Exception as exc:
                raise CommandError(f"Failed to process {runtime_path}: {exc}")

            for camera_id, cfg in runtime_payload.items():
                if not isinstance(cfg, dict):
                    continue

                camera = self._resolve_camera(camera_id, tenant)
                if camera is None and create_missing and tenant is not None:
                    camera = camera_service.create_camera(
                        tenant=tenant,
                        attrs={
                            "name": cfg.get("camera_name") or camera_id,
                            "ai_camera_id": camera_id,
                            "stream_path": cfg.get("stream_path") or camera_id,
                            "rtsp_url": cfg.get("rtsp_url") or "",
                            "source_type": Camera.SourceType.WEBCAM
                            if cfg.get("source_type") in {"webcam", "live_camera"}
                            else Camera.SourceType.REGISTERED,
                        },
                    )

                if camera is None:
                    counts["missing_camera_entries"] += 1
                    continue

                desired_lanes = list(cfg.get("enabled_lanes") or camera.enabled_lanes or [])
                desired_sample_hz = _coerce_sample_hz(cfg.get("sample_hz"), default=2.0)
                ingest_backend = str(cfg.get("ingest_backend") or "opencv")

                runtime_service.register_ai_camera_desired_state(
                    camera=camera,
                    enabled=True,
                    ingest_backend=ingest_backend,
                    sample_hz=desired_sample_hz,
                    lanes=desired_lanes,
                    policy_version=int(cfg.get("policy_version") or 1),
                    metadata={
                        "tenant_id": cfg.get("tenant_id") or camera.tenant_id,
                        "community_id": cfg.get("community_id") or camera.tenant_id,
                        "camera_name": cfg.get("camera_name") or camera.name,
                        "stream_path": cfg.get("stream_path") or camera.stream_path,
                    },
                )

                runtime_service.set_desired_mediamtx_path(
                    camera=camera,
                    stream_path=camera.stream_path or camera.ai_camera_id or camera_id,
                    source_uri=str(cfg.get("rtsp_url") or camera.rtsp_url or ""),
                    source_kind=camera.source_kind,
                    desired_enabled=True,
                )

                counts["runtime_rows_synced"] += 1

            BackfillCheckpoint.objects.update_or_create(
                source_key="ai.cameras_runtime.json",
                defaults={
                    "status": "completed",
                    "stats": {
                        "runtime_rows_synced": counts["runtime_rows_synced"],
                        "missing_camera_entries": counts["missing_camera_entries"],
                    },
                },
            )

        if cameras_yaml_path.exists():
            try:
                cameras_doc = yaml.safe_load(cameras_yaml_path.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                raise CommandError(f"Failed to process {cameras_yaml_path}: {exc}")

            for cfg in cameras_doc.get("cameras", []) or []:
                if not isinstance(cfg, dict):
                    continue
                camera_id = str(cfg.get("camera_id") or "").strip()
                if not camera_id:
                    continue

                camera = self._resolve_camera(camera_id, tenant)
                if camera is None and create_missing and tenant is not None:
                    source_type = Camera.SourceType.WEBCAM if cfg.get("source_type") in {
                        "webcam",
                        "live_camera",
                    } else Camera.SourceType.REGISTERED
                    camera = camera_service.create_camera(
                        tenant=tenant,
                        attrs={
                            "name": camera_id,
                            "ai_camera_id": camera_id,
                            "stream_path": camera_id,
                            "rtsp_url": str(cfg.get("rtsp_url") or ""),
                            "source_type": source_type,
                        },
                    )

                if camera is None:
                    counts["missing_camera_entries"] += 1
                    continue

                attrs = {}
                if cfg.get("rtsp_url") is not None:
                    attrs["rtsp_url"] = str(cfg.get("rtsp_url") or "")
                if cfg.get("enabled_lanes") is not None:
                    attrs["enabled_lanes"] = list(cfg.get("enabled_lanes") or [])
                if cfg.get("cooldown_s") is not None:
                    attrs["cooldown_s"] = int(cfg.get("cooldown_s"))
                k_of_n = cfg.get("k_of_n")
                if isinstance(k_of_n, list) and len(k_of_n) == 2:
                    attrs["k_of_n_k"] = int(k_of_n[0])
                    attrs["k_of_n_n"] = int(k_of_n[1])

                if attrs:
                    camera = camera_service.update_camera(camera=camera, attrs=attrs)
                    counts["camera_rows_updated"] += 1

                runtime_service.register_ai_camera_desired_state(
                    camera=camera,
                    enabled=bool(cfg.get("enabled", True)),
                    ingest_backend=str(cfg.get("ingest_backend") or "opencv"),
                    sample_hz=_coerce_sample_hz(cfg.get("sample_hz"), default=2.0),
                    lanes=list(cfg.get("enabled_lanes") or camera.enabled_lanes or []),
                    policy_version=1,
                    metadata={
                        "source": "configs/cameras.yaml",
                        "camera_name": camera.name,
                        "stream_path": camera.stream_path,
                    },
                )

            BackfillCheckpoint.objects.update_or_create(
                source_key="ai.configs.cameras.yaml",
                defaults={
                    "status": "completed",
                    "stats": {"camera_rows_updated": counts["camera_rows_updated"]},
                },
            )

        if zones_yaml_path.exists():
            try:
                zones_doc = yaml.safe_load(zones_yaml_path.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                raise CommandError(f"Failed to process {zones_yaml_path}: {exc}")

            zones_by_camera = zones_doc.get("zones", {}) or {}
            for camera_id, zones in zones_by_camera.items():
                camera = self._resolve_camera(str(camera_id), tenant)
                if camera is None:
                    counts["missing_camera_entries"] += 1
                    continue
                for zone_cfg in zones or []:
                    if not isinstance(zone_cfg, dict):
                        continue
                    zone_name = str(zone_cfg.get("name") or zone_cfg.get("zone_name") or "restricted").strip()
                    attrs = {
                        "zone_name": zone_name,
                        "zone_type": str(zone_cfg.get("type") or zone_cfg.get("zone_type") or CameraZone.ZoneType.RESTRICTED),
                        "polygon_points": zone_cfg.get("points") or zone_cfg.get("polygon_points") or [],
                        "enabled": bool(zone_cfg.get("enabled", True)),
                    }

                    zone = CameraZone.objects.filter(camera=camera, zone_name=zone_name).first()
                    if zone is None:
                        camera_service.create_camera_zone(camera=camera, attrs=attrs)
                    else:
                        camera_service.update_camera_zone(zone=zone, attrs=attrs)
                    counts["zones_rows_upserted"] += 1

            BackfillCheckpoint.objects.update_or_create(
                source_key="ai.configs.zones.yaml",
                defaults={
                    "status": "completed",
                    "stats": {"zones_rows_upserted": counts["zones_rows_upserted"]},
                },
            )

        if policy_yaml_path.exists():
            try:
                policy_doc = yaml.safe_load(policy_yaml_path.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                raise CommandError(f"Failed to process {policy_yaml_path}: {exc}")

            policy_payload = policy_doc.get("policy", {}) if isinstance(policy_doc, dict) else {}
            if not isinstance(policy_payload, dict):
                policy_payload = {}

            SchemaBootstrapState.objects.update_or_create(
                key="ai.policy.snapshot.v1",
                defaults={
                    "value": {
                        "policy": policy_payload,
                        "version": 1,
                        "source": "configs/policy.yaml",
                    },
                },
            )
            counts["policy_rows_synced"] = 1

            BackfillCheckpoint.objects.update_or_create(
                source_key="ai.configs.policy.yaml",
                defaults={
                    "status": "completed",
                    "stats": {"policy_rows_synced": counts["policy_rows_synced"]},
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Backfill completed: "
                f"webhooks={counts['webhooks_synced']} "
                f"runtime={counts['runtime_rows_synced']} "
                f"cameras_updated={counts['camera_rows_updated']} "
                f"zones={counts['zones_rows_upserted']} "
                f"policy={counts['policy_rows_synced']} "
                f"missing={counts['missing_camera_entries']}"
            )
        )
