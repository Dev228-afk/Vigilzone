from __future__ import annotations

from django.db import transaction

from api.models import Camera, MediaMTXDesiredPath, Tenant
from api.repositories.runtime_repository import RuntimeRepository
from api.services.outbox_service import OutboxService


class RuntimeRegistrationService:
    def __init__(
        self,
        repository: RuntimeRepository | None = None,
        outbox_service: OutboxService | None = None,
    ):
        self.repository = repository or RuntimeRepository()
        self.outbox_service = outbox_service or OutboxService()

    def get_or_create_tenant_runtime_setting(self, *, tenant: Tenant):
        return self.repository.get_or_create_tenant_runtime_setting(tenant=tenant)

    @transaction.atomic
    def set_webcam_enabled(self, *, tenant: Tenant, enabled: bool):
        runtime_setting = self.repository.set_webcam_enabled(tenant=tenant, enabled=enabled)
        self.outbox_service.emit(
            aggregate_type="tenant_runtime_setting",
            aggregate_id=tenant.id,
            event_type="runtime.webcam_enabled_set",
            payload={
                "tenant_id": tenant.id,
                "webcam_enabled": bool(enabled),
            },
        )
        return runtime_setting

    @transaction.atomic
    def set_identity_runtime_enabled(self, *, tenant: Tenant, enabled: bool):
        runtime_setting = self.repository.set_identity_runtime_enabled(tenant=tenant, enabled=enabled)
        self.outbox_service.emit(
            aggregate_type="tenant_runtime_setting",
            aggregate_id=tenant.id,
            event_type="runtime.identity_runtime_enabled_set",
            payload={
                "tenant_id": tenant.id,
                "identity_runtime_enabled": bool(enabled),
            },
        )
        return runtime_setting

    @transaction.atomic
    def register_ai_camera_desired_state(
        self,
        *,
        camera: Camera,
        enabled: bool,
        ingest_backend: str,
        sample_hz: float,
        lanes: list[str],
        policy_version: int,
        metadata: dict | None = None,
    ):
        registration = self.repository.set_ai_runtime_desired_state(
            camera=camera,
            enabled=enabled,
            ingest_backend=ingest_backend,
            sample_hz=sample_hz,
            lanes=lanes,
            policy_version=policy_version,
            metadata=metadata,
        )
        self.outbox_service.emit(
            aggregate_type="ai_runtime_registration",
            aggregate_id=camera.id,
            event_type="ai_runtime.desired_state_set",
            payload={
                "tenant_id": camera.tenant_id,
                "camera_id": camera.id,
                "enabled": bool(enabled),
                "ingest_backend": ingest_backend,
                "sample_hz": float(sample_hz),
                "lanes": list(lanes or []),
                "policy_version": int(policy_version),
            },
        )
        return registration

    @transaction.atomic
    def mark_ai_camera_observed_state(
        self,
        *,
        camera: Camera,
        running: bool | None,
        ingest_backend: str = "",
        sample_hz: float | None = None,
        lanes: list[str] | None = None,
        error: str = "",
    ):
        return self.repository.set_ai_runtime_observed_state(
            camera=camera,
            running=running,
            ingest_backend=ingest_backend,
            sample_hz=sample_hz,
            lanes=lanes,
            error=error,
        )

    @transaction.atomic
    def set_desired_mediamtx_path(
        self,
        *,
        camera: Camera,
        stream_path: str,
        source_uri: str,
        source_kind: str,
        desired_enabled: bool,
        relay_mode: str = MediaMTXDesiredPath.RelayMode.RELAY_ONLY,
        transcode_required: bool = False,
    ):
        desired_path = self.repository.set_desired_mediamtx_path(
            camera=camera,
            stream_path=stream_path,
            source_uri=source_uri,
            source_kind=source_kind,
            desired_enabled=desired_enabled,
            relay_mode=relay_mode,
            transcode_required=transcode_required,
        )
        self.outbox_service.emit(
            aggregate_type="mediamtx_desired_path",
            aggregate_id=camera.id,
            event_type="mediamtx.desired_path_set",
            payload={
                "tenant_id": camera.tenant_id,
                "camera_id": camera.id,
                "stream_path": desired_path.stream_path,
                "desired_enabled": bool(desired_enabled),
                "relay_mode": relay_mode,
                "transcode_required": bool(transcode_required),
                "path_generation": int(desired_path.path_generation),
            },
        )
        return desired_path

    @transaction.atomic
    def mark_observed_mediamtx_path(
        self,
        *,
        desired_path: MediaMTXDesiredPath,
        observed_enabled: bool | None,
        observed_source: str,
        observed_payload: dict | None = None,
        last_error: str = "",
    ):
        return self.repository.mark_observed_mediamtx_path(
            desired_path=desired_path,
            observed_enabled=observed_enabled,
            observed_source=observed_source,
            observed_payload=observed_payload,
            last_error=last_error,
        )
