"""Orders, tickets, floor plan and payments — the service loop."""
from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"
    label = "orders"
    verbose_name = "03 · Service & Floor"
