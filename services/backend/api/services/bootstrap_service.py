from __future__ import annotations

from django.db import connection, transaction

from api.models import Camera, SchemaBootstrapState, Tenant
from api.services.runtime_registration_service import RuntimeRegistrationService
from api.services.tenant_config_service import TenantConfigService


class BootstrapService:
    """Idempotent bootstrap helper for canonical config defaults."""

    def __init__(
        self,
        tenant_service: TenantConfigService | None = None,
        runtime_service: RuntimeRegistrationService | None = None,
    ):
        self.tenant_service = tenant_service or TenantConfigService()
        self.runtime_service = runtime_service or RuntimeRegistrationService()

    def install_postgres_objects(self) -> bool:
        """Install SQL bootstrap helpers when running on PostgreSQL."""
        if connection.vendor != "postgresql":
            return False
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS ops")
            cursor.execute("CREATE SCHEMA IF NOT EXISTS routing")
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        return True

    @transaction.atomic
    def bootstrap_defaults(self) -> dict:
        tenant_count = 0
        camera_count = 0

        for tenant in Tenant.objects.all().order_by("id"):
            self.tenant_service.ensure_tenant_defaults(tenant=tenant)
            tenant_count += 1

        for camera in Camera.objects.all().order_by("id"):
            self.runtime_service.register_ai_camera_desired_state(
                camera=camera,
                enabled=camera.status == Camera.Status.ACTIVE,
                ingest_backend="opencv",
                sample_hz=2.0,
                lanes=list(camera.enabled_lanes or []),
                policy_version=1,
                metadata={
                    "tenant_id": camera.tenant_id,
                    "camera_name": camera.name,
                    "stream_path": camera.stream_path,
                },
            )
            self.runtime_service.set_desired_mediamtx_path(
                camera=camera,
                stream_path=camera.stream_path or camera.ai_camera_id or f"camera-{camera.pk}",
                source_uri=camera.rtsp_url,
                source_kind=camera.source_kind,
                desired_enabled=camera.status == Camera.Status.ACTIVE,
            )
            camera_count += 1

        SchemaBootstrapState.objects.update_or_create(
            key="bootstrap.system_defaults.v1",
            defaults={
                "value": {
                    "tenants_bootstrapped": tenant_count,
                    "cameras_bootstrapped": camera_count,
                }
            },
        )

        return {
            "tenants_bootstrapped": tenant_count,
            "cameras_bootstrapped": camera_count,
        }
