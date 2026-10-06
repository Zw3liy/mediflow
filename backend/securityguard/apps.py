from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from .production import configuration_errors


class SecurityGuardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "securityguard"

    def ready(self):
        if settings.PRODUCTION_MODE:
            failures = configuration_errors(settings)
            if failures:
                raise ImproperlyConfigured("Production configuration rejected:\n- " + "\n- ".join(failures))
