from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        # Import signals to register model signal handlers when app is ready
        import api.signals  # noqa: F401

        # NOTE: The MediaMTX auto-reconcile daemon thread has been removed.
        # Relay reconciliation is now handled by the dedicated reconciler
        # worker: `python manage.py run_relay_reconciler` (cloud) or
        # embedded in `python manage.py run_worker_node` (local dev).
