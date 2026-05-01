import abc
import json
import logging
import os
import time
import signal
import threading
from typing import List, Protocol

from django.db import transaction
from django.utils import timezone
import redis

from api.models import KnownEntityProcessingJob, OutboxEvent
from api.services.entity_processing_service import EntityProcessingService
from server.redis_runtime import resolve_backend_redis_settings

logger = logging.getLogger("worker_services")

class WorkerProcessor(abc.ABC):
    """SRP interface for a background task runner."""
    
    @abc.abstractmethod
    def run_once(self) -> int:
        """Execute one batch. Returns number of items processed."""
        pass

    @abc.abstractmethod
    def get_name(self) -> str:
        pass


class EntityEmbeddingProcessor(WorkerProcessor):
    """Processes queued entity enrollment/embedding jobs."""
    
    def __init__(self, limit: int = 10):
        self.limit = limit
        self.service = EntityProcessingService()

    def run_once(self) -> int:
        summary = self.service.process_queued_jobs(limit=self.limit)
        return summary.get("processed", 0)

    def get_name(self) -> str:
        return "EntityEmbeddingProcessor"


class OutboxStreamPublisherProcessor(WorkerProcessor):
    """Drains transactional outbox rows into Redis Streams with safe claiming."""
    
    def __init__(self, batch_size: int = 100, stream_name: str = "vigilzone:stream:events"):
        self.batch_size = batch_size
        self.stream_name = stream_name
        self._redis_client = None

    def _get_client(self):
        if self._redis_client is None:
            cfg = resolve_backend_redis_settings()
            if cfg.url:
                # Prioritize full URL (handles passwords and non-standard ports from .env)
                self._redis_client = redis.from_url(cfg.url, decode_responses=True)
            else:
                # Fallback to discrete settings
                pool = redis.ConnectionPool(
                    host=cfg.host,
                    port=cfg.port,
                    db=cfg.db,
                    password=cfg.password,
                    decode_responses=True,
                )
                self._redis_client = redis.Redis(connection_pool=pool)
        return self._redis_client

    def run_once(self) -> int:
        r = self._get_client()

        # Version Check: Redis Streams (XADD) require Redis 5.0+
        # The user's system was found running Redis 3.0.504, which does not support XADD.
        info = r.info("server")
        ver_str = info.get("redis_version", "0.0.0")
        major_ver = int(ver_str.split(".")[0])
        if major_ver < 5:
            raise RuntimeError(
                f"Redis version {ver_str} is too old. Redis Streams (XADD) require version 5.0 or higher. "
                "Please upgrade your Redis server or use the version provided in docker-compose."
            )

        processed = 0
        with transaction.atomic():
            # Hardened Claiming: Claim unpublished rows using select_for_update(skip_locked=True)
            # as per the Repaired Plan to support horizontal scaling safety.
            events = list(
                OutboxEvent.objects.select_for_update(skip_locked=True)
                .filter(published_at__isnull=True)
                .order_by("created_at")[:self.batch_size]
            )
            
            processed = 0
            for event in events:
                try:
                    # Tier 1: Publish to the Redis event stream (Advisory Backbone)
                    # We use the stream name from self.stream_name or an env override.
                    actual_stream = os.getenv("AI_EVENT_STREAM", self.stream_name)
                    r.xadd(
                        actual_stream,
                        {
                            "event_id": str(event.id),
                            "event_type": event.event_type,
                            "aggregate_type": event.aggregate_type,
                            "aggregate_id": str(event.aggregate_id),
                            "payload": json.dumps(event.payload or {}),
                            "timestamp": str(event.created_at.timestamp()),
                        },
                    )
                    # Tier 2: Update database as processed (Authoritative)
                    event.published_at = timezone.now()
                    event.save(update_fields=["published_at"])
                    processed += 1
                except Exception as e:
                    logger.error(f"Failed to publish event {event.id} to Redis: {e}")
                    # On Redis error, we stop the batch to allow for backoff
                    break
        
        return processed

    def get_name(self) -> str:
        return "OutboxStreamPublisherProcessor"


class RelayReconcilerProcessor(WorkerProcessor):
    """Reconciles MediaMTX relay paths from Postgres desired state."""

    def __init__(self, shadow_mode: bool = False):
        self.shadow_mode = shadow_mode
        self._reconciler = None

    def _get_reconciler(self):
        if self._reconciler is None:
            from api.services.relay_reconciler import RelayReconciler
            self._reconciler = RelayReconciler(shadow_mode=self.shadow_mode)
        return self._reconciler

    def run_once(self) -> int:
        reconciler = self._get_reconciler()
        reconciler.reconcile_all()
        # Always return 0 to force full poll_interval sleep.
        # The reconciler is infrastructure — it must never trigger
        # the BaseWorkerService tight-loop (10ms re-run) after mutations.
        return 0

    def get_name(self) -> str:
        mode = "shadow" if self.shadow_mode else "active"
        return f"RelayReconcilerProcessor({mode})"


class BaseWorkerService:
    """Orchestrates the lifecycle of a WorkerProcessor."""
    
    def __init__(self, processor: WorkerProcessor, poll_interval: float = 1.0):
        self.processor = processor
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run_forever(self):
        name = self.processor.get_name()
        logger.info(f"Starting {name} loop (poll={self.poll_interval}s)")
        
        while not self._stop_event.is_set():
            try:
                processed_count = self.processor.run_once()
                
                if processed_count == 0:
                    # Queue is empty, sleep for poll interval
                    time.sleep(self.poll_interval)
                else:
                    # Immediate yield but keep draining if busy
                    time.sleep(0.01)
                    
            except Exception as e:
                logger.error(f"Unexpected error in {name}: {e}", exc_info=True)
                # Exponential backoff on error
                time.sleep(5.0)
        
        logger.info(f"{name} loop stopped.")
