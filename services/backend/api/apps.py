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
            from api.views import reconcile_all_cameras_to_mediamtx, _get_mediamtx_api_base
            import requests as http_client
            logger = logging.getLogger(__name__)
            
            mediamtx_was_up = False
            while True:
                api_base = _get_mediamtx_api_base()
                try:
                    resp = http_client.get(f"{api_base}/v3/config/global/get", timeout=3)
                    if resp.status_code == 200:
                        if not mediamtx_was_up:
                            logger.info("MediaMTX detected! Starting full synchronization...")
                            summary = reconcile_all_cameras_to_mediamtx()
                            logger.info("MediaMTX reconciliation complete: %s", summary)
                            # Phase 1 WS1.2: Warm Redis route projections on startup
                            try:
                                from django.core.management import call_command
                                call_command("generate_route_projection")
                                logger.info("Redis route projections generated on startup.")
                            except Exception as route_exc:
                                logger.warning("Route projection generation failed: %s", route_exc)
                            mediamtx_was_up = True
                    else:
                        mediamtx_was_up = False
                except Exception:
                    if mediamtx_was_up:
                        logger.warning("MediaMTX connection lost. Waiting for recovery...")
                    mediamtx_was_up = False
                time.sleep(15)

        # Launch the non-blocking thread for MediaMTX path provisioning
        threading.Thread(target=auto_reconcile, daemon=True, name="MediaMtxAutoReconcile").start()
