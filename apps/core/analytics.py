"""
Dashboard analytics.

Every number on the UI comes from here so the front end never invents a metric.
Queries stay set-based (annotate/aggregate) — no N+1 loops over orders.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, DecimalField, F, Q, Sum
from django.db.models.functions import Coalesce, ExtractHour, TruncDate
from django.utils import timezone

from apps.menu.models import Category, Item, Photo, StockMovement
from apps.orders.models import Order, OrderLine, Table

from .models import ActivityLog, Restaurant

ZERO = Decimal("0.00")
MONEY = DecimalField(max_digits=12, decimal_places=2)


def _day(offset: int = 0):
    today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return today + timedelta(days=offset)


def _paid_in(start, end):
    return Order.objects.filter(status=Order.PAID, paid_at__gte=start, paid_at__lt=end)


def revenue_series(days: int = 14) -> list[dict]:
    start = _day(-(days - 1))
    rows = (
        _paid_in(start, _day(1))
        .annotate(day=TruncDate("paid_at"))
        .values("day")
        .annotate(total=Sum("total", output_field=MONEY), tickets=Count("id"))
        .order_by("day")
    )
    by_day = {row["day"]: row for row in rows if row["day"]}
    out = []
    for index in range(days):
        day = (start + timedelta(days=index)).date()
        row = by_day.get(day)
        out.append(
            {
                "date": day.isoformat(),
                "label": day.strftime("%a"),
                "day": day.day,
                "revenue": float(row["total"]) if row else 0.0,
                "tickets": int(row["tickets"]) if row else 0,
            }
        )
    return out


def hourly_today() -> list[dict]:
    start, end = _day(0), _day(1)
    rows = (
        _paid_in(start, end)
        .annotate(hour=ExtractHour("paid_at", tzinfo=timezone.get_current_timezone()))
        .values("hour")
        .annotate(total=Sum("total", output_field=MONEY), tickets=Count("id"))
    )
    lookup = {int(row["hour"]): row for row in rows if row["hour"] is not None}
    return [
        {
            "hour": hour,
            "revenue": float(lookup[hour]["total"]) if hour in lookup else 0.0,
            "tickets": int(lookup[hour]["tickets"]) if hour in lookup else 0,
        }
        for hour in range(11, 24)
    ]


def category_mix(days: int = 14) -> list[dict]:
    start = _day(-(days - 1))
    totals: dict[str, dict] = {}
    for name, accent, icon, qty, money in (
        OrderLine.objects.filter(order__status=Order.PAID, order__paid_at__gte=start)
        .values_list(
            "item__category__name", "item__category__accent", "item__category__icon",
            "quantity", F("unit_price") * F("quantity"),
        )
    ):
        if not name:
            continue
        bucket = totals.setdefault(name, {"name": name, "accent": accent or "#D8B26A",
                                         "icon": icon or "✦", "revenue": 0.0, "portions": 0})
        bucket["revenue"] += float(money or 0)
        bucket["portions"] += int(qty or 0)
    out = sorted(totals.values(), key=lambda row: -row["revenue"])
    for row in out:
        row["revenue"] = round(row["revenue"], 2)
    return out


def top_dishes(days: int = 14, limit: int = 6) -> list[dict]:
    start = _day(-(days - 1))
    rows = (
        OrderLine.objects.filter(order__status=Order.PAID, order__paid_at__gte=start, item__isnull=False)
        .values("item_id", "item__name", "item__category__name", "item__category__accent", "item__photo__file")
        .annotate(
            portions=Sum("quantity"),
            revenue=Sum(F("unit_price") * F("quantity"), output_field=MONEY),
            tickets=Count("order_id", distinct=True),
        )
        .order_by("-portions")[:limit]
    )
    out = []
    for row in rows:
        photo = f"media/{row['item__photo__file']}" if row.get("item__photo__file") else ""
        out.append(
            {
                "id": row["item_id"],
                "name": row["item__name"],
                "category": row["item__category__name"],
                "accent": row["item__category__accent"] or "#D8B26A",
                "portions": row["portions"],
                "revenue": float(row["revenue"] or 0),
                "tickets": row["tickets"],
                "photo": "/" + photo if photo else "",
            }
        )
    return out


def stock_watch(limit: int = 6) -> dict:
    items = Item.objects.select_related("category").order_by("stock", "-par_level")
    low = [
        {
            "id": item.pk, "name": item.name, "stock": item.stock, "par": item.par_level,
            "state": item.stock_state, "label": item.stock_label, "accent": item.category.accent,
            "category": item.category.name, "needed": item.needs_restock, "unit": item.unit,
            "photo": item.photo_url, "price": str(item.price),
        }
        for item in items.filter(stock__lte=F("low_stock_threshold"))[:limit]
    ]
    sold = StockMovement.objects.filter(direction="OUT", created_at__gte=_day(0)).aggregate(
        total=Sum("quantity")
    )["total"] or 0
    return {
        "low": low,
        "sold_today": sold,
        "without_photo": Item.objects.without_photo().count(),
        "eighty_sixed": Item.objects.filter(is_available=False).count(),
        "healthy": Item.objects.exclude(stock__lte=F("low_stock_threshold")).count(),
    }


def floor_state() -> list[dict]:
    tables = list(Table.objects.filter(is_active=True).order_by("zone", "label"))
    # one query for every live ticket, mapped by table — no N+1 per table
    live_by_table: dict[int, Order] = {}
    for order in Order.objects.open().order_by("created_at"):
        if order.table_id:
            live_by_table[order.table_id] = order
    out = []
    for table in tables:
        order = live_by_table.get(table.pk)
        out.append(
            {
                "id": table.pk,
                "label": table.label,
                "seats": table.seats,
                "zone": table.zone,
                "status": table.status,
                "tone": table.tone,
                "x": float(table.x),
                "y": float(table.y),
                "rotation": table.rotation,
                "note": table.note,
                "order": None
                if order is None
                else {
                    "id": order.pk,
                    "number": order.number,
                    "status": order.status,
                    "age": order.age_label,
                    "total": str(order.total),
                    "late": order.is_late,
                },
            }
        )
    return out


def overview() -> dict:
    venue = Restaurant.load()
    start, end = _day(0), _day(1)
    y_start = _day(-1)

    today = _paid_in(start, end).aggregate(
        revenue=Coalesce(Sum("total", output_field=MONEY), ZERO, output_field=MONEY),
        tickets=Count("id"),
        covers=Coalesce(Sum("party_size"), 0),
        avg=Coalesce(Avg("total", output_field=MONEY), ZERO, output_field=MONEY),
    )
    yesterday = _paid_in(y_start, start).aggregate(
        revenue=Coalesce(Sum("total", output_field=MONEY), ZERO, output_field=MONEY), tickets=Count("id")
    )

    def pct(now, prev):
        now, prev = float(now or 0), float(prev or 0)
        if prev <= 0:
            return 100 if now > 0 else 0
        return round((now - prev) / prev * 100)

    open_tickets = list(
        Order.objects.open().select_related("table").prefetch_related("lines").order_by("created_at")
    )
    late = [order for order in open_tickets if order.is_late]
    running_value = sum(float(order.total or 0) for order in open_tickets)
    items = Item.objects.all()
    metrics = {
        "revenue": float(today["revenue"]),
        "revenue_delta": pct(today["revenue"], yesterday["revenue"]),
        "tickets": today["tickets"],
        "tickets_delta": pct(today["tickets"], yesterday["tickets"]),
        "covers": today["covers"],
        "avg_ticket": float(today["avg"]),
        "avg_delta": pct(today["avg"], yesterday["revenue"] / max(yesterday["tickets"], 1) if yesterday["tickets"] else 0),
        "open_tickets": len(open_tickets),
        "late_tickets": len(late),
        "running_value": round(running_value, 2),
        "dishes": items.count(),
        "dishes_live": items.filter(is_available=True).count(),
        "dishes_no_photo": items.filter(photo__isnull=True).count(),
        "photos": Photo.objects.count(),
        "shared_photos": Photo.objects.exclude(items__isnull=True).values("id").annotate(uses=Count("items")).filter(uses__gt=1).count(),
        "categories": Category.objects.count(),
        "tables_total": Table.objects.filter(is_active=True).count(),
        "tables_seated": Table.objects.exclude(status__in=("free", "clearing")).count(),
        "kitchen_minutes": venue.kitchen_lane_minutes,
        "hours": venue.hours_label,
        "is_open": venue.is_open_now,
        "currency": venue.currency_symbol,
    }
    return {
        "metrics": metrics,
        "series": revenue_series(14),
        "hourly": hourly_today(),
        "mix": category_mix(14),
        "top": top_dishes(14, 6),
        "stock": stock_watch(6),
        "floor": floor_state(),
        "tickets": [ticket_payload(order) for order in open_tickets[:8]],
        "activity": [
            {
                "id": row.pk,
                "verb": row.verb,
                "message": row.message,
                "level": row.level,
                "actor": (row.actor.get_full_name() or row.actor.username) if row.actor else "system",
                "ago": _ago(row.moment),
                "link": row.link,
            }
            for row in ActivityLog.objects.select_related("actor")[:9]
        ],
        "generated_at": timezone.now().isoformat(),
    }


def ticket_payload(order: Order, *, lines: bool = True) -> dict:
    return {
        "id": order.pk,
        "number": order.number,
        "status": order.status,
        "status_label": order.get_status_display(),
        "channel": order.channel,
        "channel_label": order.get_channel_display(),
        "guest": order.guest_name,
        "party": order.party_size,
        "table": order.table.label if order.table_id else None,
        "table_id": order.table_id,
        "waiter": order.waiter.display_name if order.waiter_id else None,
        "chef": order.chef.display_name if order.chef_id else None,
        "note": order.note,
        "priority": order.priority,
        "subtotal": str(order.subtotal),
        "tax": str(order.tax_total),
        "service": str(order.service_total),
        "discount": str(order.discount),
        "total": str(order.total),
        "items": order.item_count,
        "age": order.age_label,
        "age_seconds": order.age_seconds,
        "late": order.is_late,
        "tone": order.tone,
        "progress": order.progress_pct,
        "opened": _ago(order.created_at),
        "lines": [
            {
                "id": line.pk,
                "name": line.name_at_order,
                "quantity": line.quantity,
                "unit_price": str(line.unit_price),
                "line_total": str(line.line_total),
                "state": line.state,
                "tone": line.tone,
                "notes": line.notes,
                "course": line.course,
                "is_comp": line.is_comp,
                "photo": line.item.photo_url if line.item_id and line.item else "",
            }
            for line in (order.lines.select_related("item__photo") if lines else [])
        ]
        if lines
        else [],
    }


def _ago(moment) -> str:
    delta = timezone.now() - moment
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h {mins % 60}m ago"
    days = hours // 24
    return "yesterday" if days == 1 else f"{days}d ago"
