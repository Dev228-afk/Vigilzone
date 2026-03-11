from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        # Import signals to register model signal handlers when app is ready
        import api.signals  # noqa: F401

        # Start background snapshot cache (only in the main process, not migrations)
        import sys
        if "runserver" in sys.argv or "gunicorn" in sys.argv[0:1] or "uvicorn" in sys.argv[0:1]:
            from api.snapshot_cache import start_snapshot_worker
            start_snapshot_worker()
