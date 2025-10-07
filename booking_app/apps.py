from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class BookingAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'booking_app'

    def ready(self):
        import booking_app.signals

    def ready(self):
        # This code runs once when the Django server starts.
        # We only perform this strict check in production (when DEBUG=False).
        if not settings.DEBUG:
            # We import here to avoid issues during startup.
            from .utils.licensing_client import is_license_valid

            if not is_license_valid():
                raise ImproperlyConfigured(
                    "License validation failed. The application cannot start."
                )