import logging
import os
import signal
import sys
import threading
import time

from django.core.management.base import BaseCommand
import requests as http_client
import redis
from api.services.worker_services import (
    EntityEmbeddingProcessor,
    OutboxStreamPublisherProcessor,
    RelayReconcilerProcessor,
    BaseWorkerService,
)
from api.services.mediamtx_helpers import get_mediamtx_api_base
from server.redis_runtime import resolve_backend_redis_settings

logger = logging.getLogger("run_worker_node")

class Command(BaseCommand):
    help = "[DEV-ONLY] Runs all background worker threads in one process for local development."

    def add_arguments(self, parser):
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=1.0,
            help="Polling interval for all workers (except reconciler)",
        )
        parser.add_argument(
            "--reconciler-shadow",
            action="store_true",
            default=False,
            help="Run the relay reconciler in shadow (verify-only) mode.",
        )

    def handle(self, *args, **options):
        poll_interval = options["poll_interval"]
        reconciler_shadow = options["reconciler_shadow"]
        reconciler_interval = float(
            os.getenv("RECONCILER_POLL_INTERVAL_S", "10")
        )

        self.stdout.write(self.style.WARNING("!!! [DEV-ONLY] Starting Unified Worker Node !!!"))
        self.stdout.write("Use only for local development and testing. Deploy separate workers in cloud.")
        self._wait_for_redis()
        self._wait_for_mediamtx()

        # Instantiate processors
        processors = [
            EntityEmbeddingProcessor(limit=10),
            OutboxStreamPublisherProcessor(batch_size=100),
        ]
        reconciler_processor = RelayReconcilerProcessor(shadow_mode=reconciler_shadow)

        # Wrap in services (reconciler gets its own poll interval)
        services = [BaseWorkerService(p, poll_interval=poll_interval) for p in processors]
        services.append(
            BaseWorkerService(reconciler_processor, poll_interval=reconciler_interval)
        )
        threads = []

        def run_service(svc):
            try:
                svc.run_forever()
            except Exception as e:
                logger.error(f"Worker thread crashed: {e}", exc_info=True)

        for svc in services:
            t = threading.Thread(target=run_service, args=(svc,), daemon=True)
            t.start()
            threads.append(t)
            self.stdout.write(self.style.SUCCESS(f"Spawned thread for {svc.processor.get_name()}"))

        self.stdout.write(self.style.SUCCESS("All workers running. Press Ctrl+C to stop."))

        # Cross-platform graceful shutdown handling
        def shutdown_handler(signum, frame):
            self.stdout.write(self.style.WARNING("\nShutdown signal received. Stopping workers..."))
            for svc in services:
                svc.stop()
            # We don't join threads here to avoid blocking a signal handler
            # instead we just exit as they are daemon=True
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

        try:
            # Keep main thread alive
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            shutdown_handler(None, None)

    def _wait_for_mediamtx(self):
        api_base = get_mediamtx_api_base()
        self.stdout.write(f"Waiting for MediaMTX at {api_base} before starting workers...")
        while True:
            try:
                resp = http_client.get(f"{api_base}/v3/config/global/get", timeout=3)
                if resp.status_code == 200:
                    self.stdout.write(self.style.SUCCESS("MediaMTX is reachable. Starting worker threads."))
                    return
            except Exception:
                pass
            time.sleep(5)

    def _wait_for_redis(self):
        cfg = resolve_backend_redis_settings()
        display = cfg.connection_display
        self.stdout.write(f"Waiting for Redis at {display} before starting workers...")

        while True:
            try:
                if cfg.url:
                    client = redis.from_url(cfg.url, decode_responses=True)
                else:
                    client = redis.Redis(
                        host=cfg.host,
                        port=cfg.port,
                        db=cfg.db,
                        password=cfg.password,
                        decode_responses=True,
                    )

                client.ping()
                info = client.info("server")
                version = str(info.get("redis_version", "unknown"))
                self.stdout.write(self.style.SUCCESS(f"Redis is reachable (version {version}). Starting worker threads."))
                return
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f"Redis not ready at {display}: {type(exc).__name__}. Retrying in 5s...")
                )
                time.sleep(5)
