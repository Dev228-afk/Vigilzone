import asyncio
from datetime import timedelta
from typing import Any

from django.conf import settings
from livekit import api


class LiveKitConfigError(RuntimeError):
    pass


def _require_livekit_config() -> tuple[str, str, str]:
    url = (getattr(settings, "LIVEKIT_URL", "") or "").strip()
    key = (getattr(settings, "LIVEKIT_API_KEY", "") or "").strip()
    secret = (getattr(settings, "LIVEKIT_API_SECRET", "") or "").strip()
    if not url or not key or not secret:
        raise LiveKitConfigError(
            "Missing LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET configuration"
        )
    return url, key, secret


async def _create_ingress_async(
    *,
    room_name: str,
    ingress_name: str,
    participant_identity: str,
    participant_name: str,
) -> dict[str, Any]:
    url, key, secret = _require_livekit_config()
    lk = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        req = api.CreateIngressRequest()
        req.input_type = api.IngressInput.RTMP_INPUT
        req.name = ingress_name
        req.room_name = room_name
        req.participant_identity = participant_identity
        req.participant_name = participant_name
        req.enable_transcoding = True

        info = await lk.ingress.create_ingress(req)
        return {
            "ingress_id": info.ingress_id,
            "url": info.url,
            "stream_key": info.stream_key,
            "room_name": info.room_name,
            "name": info.name,
            "state": int(info.state),
        }
    finally:
        await lk.aclose()


async def _delete_ingress_async(ingress_id: str) -> None:
    url, key, secret = _require_livekit_config()
    lk = api.LiveKitAPI(url=url, api_key=key, api_secret=secret)
    try:
        req = api.DeleteIngressRequest()
        req.ingress_id = ingress_id
        await lk.ingress.delete_ingress(req)
    finally:
        await lk.aclose()


def provision_rtmp_ingress(
    *,
    room_name: str,
    ingress_name: str,
    participant_identity: str,
    participant_name: str,
) -> dict[str, Any]:
    return asyncio.run(
        _create_ingress_async(
            room_name=room_name,
            ingress_name=ingress_name,
            participant_identity=participant_identity,
            participant_name=participant_name,
        )
    )


def delete_ingress(ingress_id: str) -> None:
    if ingress_id:
        asyncio.run(_delete_ingress_async(ingress_id))


def create_viewer_token(*, room_name: str, identity: str, name: str, ttl_s: int = 300) -> str:
    _, key, secret = _require_livekit_config()
    token = (
        api.AccessToken(key, secret)
        .with_identity(identity)
        .with_name(name)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_subscribe=True,
                can_publish=False,
                can_publish_data=False,
            )
        )
        .with_ttl(timedelta(seconds=ttl_s))
        .to_jwt()
    )
    return token
