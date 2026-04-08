from __future__ import annotations

import json
from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional, Tuple

from server.redis_runtime import (
    DEFAULT_QUEUE_MODE,
    resolve_backend_redis_settings,
)


SUBSCRIBER_HEARTBEAT_TTL_SECONDS = 30


def create_redis_client(settings=None):
    import redis

    cfg = settings or resolve_backend_redis_settings()
    if cfg.url:
        return redis.Redis.from_url(
            cfg.url,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=10,
            retry_on_timeout=True,
        )
    return redis.Redis(
        host=cfg.host,
        port=cfg.port,
        db=cfg.db,
        username=cfg.username or None,
        password=cfg.password or None,
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=10,
        retry_on_timeout=True,
    )


def ensure_incident_consumer_group(client, settings) -> None:
    try:
        client.xgroup_create(
            name=settings.incident_channel,
            groupname=settings.incident_consumer_group,
            id="0-0",
            mkstream=True,
        )
    except Exception as exc:
        # BUSYGROUP means it already exists.
        if "BUSYGROUP" not in str(exc):
            raise


def append_incident_event(client, channel: str, envelope: Dict[str, Any]) -> str:
    return client.xadd(channel, {"payload": json.dumps(envelope)})


def stream_length(client, channel: str) -> int:
    return int(client.xlen(channel))


def read_stream_events(
    client,
    settings,
    *,
    consumer_name: str,
    pending: bool = False,
    count: int = 10,
    block_ms: int = 2000,
) -> List[Tuple[str, Dict[str, str]]]:
    stream_id = "0" if pending else ">"
    response = client.xreadgroup(
        groupname=settings.incident_consumer_group,
        consumername=consumer_name,
        streams={settings.incident_channel: stream_id},
        count=count,
        block=block_ms,
    )
    if not response:
        return []
    _, entries = response[0]
    return entries


def claim_stale_stream_events(
    client,
    settings,
    *,
    consumer_name: str,
    count: int = 10,
) -> List[Tuple[str, Dict[str, str]]]:
    response = client.xautoclaim(
        name=settings.incident_channel,
        groupname=settings.incident_consumer_group,
        consumername=consumer_name,
        min_idle_time=settings.incident_claim_idle_ms,
        start_id="0-0",
        count=count,
    )
    if not response:
        return []
    # redis-py returns (next_start_id, [(id, fields)...], deleted_ids)
    return response[1] if len(response) > 1 else []


def ack_stream_event(client, settings, stream_entry_id: str) -> int:
    return int(
        client.xack(
            settings.incident_channel,
            settings.incident_consumer_group,
            stream_entry_id,
        )
    )


def build_test_incident_event(
    *,
    camera_id: str,
    tenant_id: Optional[int] = None,
    incident_type: str = "intrusion",
    severity: int = 4,
    source_type: str = "synthetic_test",
) -> Dict[str, Any]:
    event_id = f"test-{camera_id}-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "event": "alert.created",
        "timestamp": now,
        "data": {
            "id": event_id,
            "camera_id": camera_id,
            "type": incident_type,
            "severity": severity,
            "timestamp": now,
            "message": f"Synthetic {incident_type} incident for pipeline verification",
            "confidence": 0.99,
            "tenant_id": tenant_id,
            "source_type": source_type,
            "evidence": {
                "keyframe_path": "",
                "clip_path": "",
            },
        },
    }


def subscriber_status_key(channel: str) -> str:
    return f"{channel}:subscriber_status"


def publish_subscriber_status(client, channel: str, payload: Dict[str, Any]) -> None:
    key = subscriber_status_key(channel)
    client.setex(
        key,
        SUBSCRIBER_HEARTBEAT_TTL_SECONDS,
        json.dumps(payload),
    )


def read_subscriber_status(client, channel: str) -> Optional[Dict[str, Any]]:
    raw = client.get(subscriber_status_key(channel))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def build_subscriber_status(
    *,
    settings,
    phase: str,
    pid: int,
    last_event_id: str = "",
    last_error: str = "",
    processed_count: int = 0,
    stream_entry_id: str = "",
) -> Dict[str, Any]:
    return {
        "phase": phase,
        "pid": pid,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "queue_mode": DEFAULT_QUEUE_MODE,
        "stream": settings.incident_channel,
        "channel": settings.incident_channel,
        "consumer_group": settings.incident_consumer_group,
        "consumer_name": settings.incident_consumer_name,
        "redis": settings.connection_display,
        "last_event_id": last_event_id,
        "last_stream_entry_id": stream_entry_id,
        "last_error": last_error,
        "processed_count": processed_count,
    }
