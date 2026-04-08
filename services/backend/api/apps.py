from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        # Import signals to register model signal handlers when app is ready
        import api.signals  # noqa: F401
        
        import os
        import threading
        import time
        import logging
        from django.conf import settings
        
        # Avoid running multiple times in hot-reload or sub-processes
        if os.environ.get("RUN_MAIN", None) != "true" and settings.DEBUG:
            return

        def auto_reconcile():
            try:
                time.sleep(3)  # wait for db/mediamtx
                from api.views import reconcile_all_cameras_to_mediamtx
                logger = logging.getLogger(__name__)
                logger.info("Starting background auto-reconciliation to MediaMTX...")
                summary = reconcile_all_cameras_to_mediamtx()
                logger.info("Background MediaMTX reconcile complete: %s", summary)
            except Exception as e:
                logging.getLogger(__name__).warning("Failed to auto-reconcile MediaMTX streams on startup: %s", e)

        # Launch the non-blocking thread for MediaMTX path provisioning
        threading.Thread(target=auto_reconcile, daemon=True, name="MediaMtxAutoReconcile").start()
