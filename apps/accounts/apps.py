"""People: staff profiles, roles, duty boards."""
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "02 · People & Roles"

    def ready(self):  # pragma: no cover - import side effect
        from . import signals  # noqa: F401
