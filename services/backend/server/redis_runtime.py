from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Mapping
from urllib.parse import quote, urlparse, urlunparse


DEFAULT_REDIS_HOST = "127.0.0.1"
DEFAULT_REDIS_PORT = 6379
DEFAULT_REDIS_DB = 0
DEFAULT_AI_INCIDENT_CHANNEL = "vigilzone.ai.incidents"
DEFAULT_QUEUE_MODE = "redis_stream"
DEFAULT_INCIDENT_CONSUMER_GROUP = "vigilzone.ai.incidents.group"
DEFAULT_INCIDENT_CONSUMER_NAME = "backend-subscriber"
DEFAULT_INCIDENT_CLAIM_IDLE_MS = 30000


def _env_text(environ: Mapping[str, str], key: str, default: str = "") -> str:
    return str(environ.get(key, default) or "").strip()


def _env_int(environ: Mapping[str, str], key: str, default: int) -> int:
    raw = _env_text(environ, key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _sanitize_redis_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme:
        return url
    if parsed.password is None:
        return url

    username = parsed.username or ""
    auth = quote(username, safe="") if username else ""
    if auth:
        auth = f"{auth}:***"
    else:
        auth = ":***"

    netloc = auth + "@"
    if parsed.hostname:
        netloc += parsed.hostname
    if parsed.port:
        netloc += f":{parsed.port}"

    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def _build_redis_url(
    host: str,
    port: int,
    db: int,
    username: str = "",
    password: str = "",
) -> str:
    auth = ""
    if username or password:
        safe_user = quote(username or "default", safe="")
        safe_password = quote(password, safe="")
        auth = f"{safe_user}:{safe_password}@"
    path = f"/{db}" if db else ""
    return f"redis://{auth}{host}:{port}{path}"


@dataclass(frozen=True)
class BackendRedisSettings:
    url: str
    host: str
    port: int
    db: int
    username: str
    password: str
    configured: bool
    source: str
    incident_channel: str
    incident_consumer_group: str
    incident_consumer_name: str
    incident_claim_idle_ms: int
    queue_mode: str = DEFAULT_QUEUE_MODE

    @property
    def connection_display(self) -> str:
        if self.url:
            return _sanitize_redis_url(self.url)
        return _sanitize_redis_url(
            _build_redis_url(
                host=self.host,
                port=self.port,
                db=self.db,
                username=self.username,
                password=self.password,
            )
        )

    @property
    def channels_host(self):
        if self.url:
            return self.url
        return (self.host, self.port)

    def to_diagnostics(self) -> dict:
        payload = asdict(self)
        payload["password"] = "***" if self.password else ""
        payload["url"] = _sanitize_redis_url(self.url)
        payload["connection_display"] = self.connection_display
        return payload


def resolve_backend_redis_settings(
    environ: Mapping[str, str] | None = None,
) -> BackendRedisSettings:
    env = environ or os.environ
    redis_url = _env_text(env, "REDIS_URL", "")
    redis_host = _env_text(env, "REDIS_HOST", "")
    redis_port = _env_int(env, "REDIS_PORT", DEFAULT_REDIS_PORT)
    redis_db = _env_int(env, "REDIS_DB", DEFAULT_REDIS_DB)
    redis_username = _env_text(env, "REDIS_USERNAME", _env_text(env, "REDIS_USER", ""))
    redis_password = _env_text(env, "REDIS_PASSWORD", "")
    incident_channel = _env_text(env, "AI_INCIDENT_CHANNEL", DEFAULT_AI_INCIDENT_CHANNEL)
    consumer_group = _env_text(
        env,
        "AI_INCIDENT_CONSUMER_GROUP",
        DEFAULT_INCIDENT_CONSUMER_GROUP,
    )
    consumer_name = _env_text(
        env,
        "AI_INCIDENT_CONSUMER_NAME",
        DEFAULT_INCIDENT_CONSUMER_NAME,
    )
    claim_idle_ms = _env_int(
        env,
        "AI_INCIDENT_CLAIM_IDLE_MS",
        DEFAULT_INCIDENT_CLAIM_IDLE_MS,
    )

    configured = bool(redis_url or redis_host)
    source = "redis_url" if redis_url else "host_port" if redis_host else "defaults"

    return BackendRedisSettings(
        url=redis_url,
        host=redis_host or DEFAULT_REDIS_HOST,
        port=redis_port,
        db=redis_db,
        username=redis_username,
        password=redis_password,
        configured=configured,
        source=source,
        incident_channel=incident_channel or DEFAULT_AI_INCIDENT_CHANNEL,
        incident_consumer_group=consumer_group or DEFAULT_INCIDENT_CONSUMER_GROUP,
        incident_consumer_name=consumer_name or DEFAULT_INCIDENT_CONSUMER_NAME,
        incident_claim_idle_ms=claim_idle_ms,
    )
