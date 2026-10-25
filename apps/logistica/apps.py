from django.apps import AppConfig


class LogisticaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.logistica"
    verbose_name = "Logística y rutas"

    def ready(self):
        from . import signals  # noqa: F401
