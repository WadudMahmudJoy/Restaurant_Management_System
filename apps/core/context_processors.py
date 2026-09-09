"""Template context every page needs: venue record, navigation state, live counters."""
from __future__ import annotations

from django.core.cache import cache

from .models import Restaurant


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
        "is_staff_view": getattr(getattr(request, "user", None), "is_staff", False),
    }
