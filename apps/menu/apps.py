"""Menu domain: categories, dishes, the shared photo library, stock ledger."""
from django.apps import AppConfig


class MenuConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.menu"
    label = "menu"
    verbose_name = "01 · Menu & Stock"

    def ready(self):  # pragma: no cover - import side effect
        from . import signals  # noqa: F401
