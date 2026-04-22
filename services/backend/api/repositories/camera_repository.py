from __future__ import annotations

from django.db.models import Q

from api.models import Camera, CameraZone, Tenant


class CameraConfigRepository:
    def get_camera(self, camera_id: int, *, tenant: Tenant | None = None) -> Camera:
        query = Camera.objects.filter(pk=camera_id)
        if tenant is not None:
            query = query.filter(tenant=tenant)
        return query.get()

    def list_cameras_for_tenant(self, *, tenant: Tenant):
        return Camera.objects.filter(tenant=tenant).order_by("id")

    def create_camera(self, *, tenant: Tenant, attrs: dict) -> Camera:
        return Camera.objects.create(tenant=tenant, **attrs)

    def update_camera(self, *, camera: Camera, attrs: dict) -> Camera:
        for key, value in attrs.items():
            setattr(camera, key, value)
        camera.save()
        return camera

    def delete_camera(self, *, camera: Camera) -> None:
        camera.delete()

    def ensure_webcam_camera(self, *, tenant: Tenant, enabled: bool | None = None) -> Camera:
        camera = (
            Camera.objects.filter(tenant=tenant)
            .filter(
                Q(ai_camera_id="cam_live")
                | Q(stream_path="cam_live")
                | Q(source_type=Camera.SourceType.WEBCAM)
            )
            .order_by("id")
            .first()
        )

        target_status = (
            Camera.Status.ACTIVE
            if enabled is True
            else Camera.Status.INACTIVE
            if enabled is False
            else None
        )

        if camera is None:
            return Camera.objects.create(
                tenant=tenant,
                name="Live Webcam",
                ai_camera_id="cam_live",
                stream_path="cam_live",
                source_type=Camera.SourceType.WEBCAM,
                status=target_status or Camera.Status.INACTIVE,
            )

        update_fields: list[str] = []
        if not camera.name:
            camera.name = "Live Webcam"
            update_fields.append("name")
        if camera.ai_camera_id != "cam_live":
            camera.ai_camera_id = "cam_live"
            update_fields.append("ai_camera_id")
        if camera.stream_path != "cam_live":
            camera.stream_path = "cam_live"
            update_fields.append("stream_path")
        if camera.source_type != Camera.SourceType.WEBCAM:
            camera.source_type = Camera.SourceType.WEBCAM
            update_fields.append("source_type")
        if target_status and camera.status != target_status:
            camera.status = target_status
            update_fields.append("status")

        if update_fields:
            update_fields.append("updated_at")
            camera.save(update_fields=update_fields)
        return camera

    def list_camera_zones(self, *, camera: Camera):
        return CameraZone.objects.filter(camera=camera).order_by("zone_name")

    def create_camera_zone(self, *, camera: Camera, attrs: dict) -> CameraZone:
        return CameraZone.objects.create(camera=camera, **attrs)

    def update_camera_zone(self, *, zone: CameraZone, attrs: dict) -> CameraZone:
        for key, value in attrs.items():
            setattr(zone, key, value)
        zone.save()
        return zone

    def delete_camera_zone(self, *, zone: CameraZone) -> None:
        zone.delete()
