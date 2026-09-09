"""Template context every page needs: venue record, navigation state, live counters."""
from __future__ import annotations

from django.core.cache import cache
from django.urls import NoReverseMatch, reverse

from .models import Restaurant

# The admin is mounted inside a namespace, so {% url %} there can only see
# "admin:*" names. Publishing the app's own routes in the context lets
# templates/admin/base_site.html hand people back to the app.
# (context key, namespaced url name) — every app here declares app_name, so the
# names are only reachable as "core:dashboard", "menu:studio", …
APP_LINKS = (
    ("home", "core:home"), ("menu", "menu:guest"), ("dashboard", "core:dashboard"),
    ("studio", "menu:studio"), ("board", "orders:board"), ("kitchen", "orders:kitchen"),
    ("vault", "core:vault"),
)


def app_links() -> dict[str, str]:
    links = {}
    for key, name in APP_LINKS:
        try:
            links[key] = reverse(name)
        except NoReverseMatch:      # pragma: no cover - during partial URLConf edits
            continue
    return links


def branding(request) -> dict:
    """Cheap: the Restaurant row is cached; nav badges refresh every 20s."""
    venue = Restaurant.load()
    badges = cache.get("rms:badges")
    if badges is None:
        badges = {"open_orders": 0, "low_stock": 0}
        try:
            from apps.menu.models import Item
            from apps.orders.models import Order

            badges = {
                "open_orders": Order.objects.exclude(status__in=Order.CLOSED_STATES).count(),
                "low_stock": Item.objects.low_stock().count(),
            }
            cache.set("rms:badges", badges, 20)
        except Exception:  # pragma: no cover - during migrations/first boot
            badges = {"open_orders": 0, "low_stock": 0}
    return {
        "venue": venue,
        "nav_badges": badges,
        "app_links": app_links(),
        "is_staff_view": getattr(getattr(request, "user", None), "is_staff", False),
    }
