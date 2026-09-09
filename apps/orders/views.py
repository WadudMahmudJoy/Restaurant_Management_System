"""Service floor: ticket board, kitchen display, floor map, guest ordering."""
from __future__ import annotations

import json
import random
import string
from decimal import Decimal

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.analytics import floor_state, overview, ticket_payload
from apps.core.models import ActivityLog, Restaurant
from apps.menu.models import Item

from .models import GuestNote, Order, OrderLine, Payment, Table

ZERO = Decimal("0.00")


def _body(request) -> dict:
    try:
        return json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def _ok(**payload) -> JsonResponse:
    return JsonResponse({"ok": True, **payload}, json_dumps_params={"default": str})


def _fail(message: str, *, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def staff_only(view):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            if request.path.startswith("/api/"):
                return JsonResponse({"ok": False, "error": "Staff sign-in required."}, status=403)
            return redirect(f"/login/?next={request.path}")
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    return wrapper


# ── pages ────────────────────────────────────────────────────────────────
@staff_only
def board(request):
    return render(
        request,
        "dashboard/orders.html",
        {
            "statuses": [{"value": value, "label": label} for value, label in Order.STATUSES],
            "orders": [
                ticket_payload(order)
                for order in Order.objects.select_related("table", "waiter", "chef")
                .prefetch_related("lines__item__photo").order_by("-created_at")[:24]
            ],
            "floor": floor_state(),
        },
    )


@staff_only
def kitchen(request):
    live = (
        Order.objects.open()
        .select_related("table", "waiter", "chef")
        .prefetch_related("lines__item__photo")
        .order_by("created_at")[:40]
    )
    return render(
        request,
        "dashboard/kitchen.html",
        {
            "tickets": [ticket_payload(order) for order in live],
            "lane_minutes": Restaurant.load().kitchen_lane_minutes,
        },
    )


# ── API ──────────────────────────────────────────────────────────────────
@staff_only
@require_GET
def api_orders(request):
    status = request.GET.get("status", "open")
    query = Order.objects.select_related("table", "waiter", "chef").prefetch_related("lines__item__photo")
    if status == "open":
        query = query.open()
    elif status != "all":
        query = query.filter(status=status)
    orders = [ticket_payload(order) for order in query.order_by("created_at")[:40]]
    closed = Order.objects.filter(status=Order.PAID)
    return _ok(
        orders=orders,
        columns={
            "new": query.filter(status=Order.NEW).count(),
            "fire": query.filter(status=Order.FIRE).count(),
            "ready": query.filter(status=Order.READY).count(),
            "served": query.filter(status=Order.SERVED).count(),
        },
        totals={
            "paid_today": closed.filter(paid_at__date=timezone.localdate()).count(),
            "value_open": str(sum((order.total for order in query.open()), ZERO)),
        },
    )


@staff_only
@require_POST
def api_order_action(request):
    data = _body(request)
    order = get_object_or_404(
        Order.objects.select_related("table", "waiter", "chef").prefetch_related("lines__item__photo"),
        pk=data.get("id"),
    )
    action = data.get("action")
    if action == "advance":
        order.advance(actor=request.user)
        notice = f"{order.number} → {order.get_status_display().lower()}"
    elif action == "ready":
        while order.status in (Order.NEW, Order.FIRE):
            order.advance(actor=request.user)
        notice = f"{order.number} is ready for the pass"
    elif action == "settle":
        while order.status not in (Order.SERVED, Order.PAID):
            order.advance(actor=request.user)
        order.settle(method=data.get("method", "card"), actor=request.user)
        notice = f"{order.number} settled · {Restaurant.load().money(order.total)}"
    elif action == "cancel":
        order.cancel(actor=request.user, reason=data.get("note", ""))
        notice = f"{order.number} cancelled"
    elif action == "hold":
        order.priority = "rush" if order.priority != "rush" else "normal"
        order.save(update_fields=["priority", "updated_at"])
        notice = f"{order.number} marked {'rush' if order.priority == 'rush' else 'normal'}"
    elif action == "line":
        line = get_object_or_404(OrderLine, pk=data.get("line_id"), order=order)
        states = [state for state, _ in OrderLine.STATES]
        line.state = states[min(states.index(line.state) + 1, len(states) - 1)]
        if line.state == "ready":
            line.ready_at = timezone.now()
        line.save(update_fields=["state", "ready_at", "updated_at"])
        notice = f"{line.quantity}× {line.name_at_order} · {line.state}"
    else:
        return _fail(f"Unknown action “{action}”.")
    ActivityLog.record(notice, verb="served" if order.status == Order.SERVED else "updated",
                       actor=request.user, obj=order, table="orders_order",
                       level="good" if order.status != Order.CANCELLED else "bad")
    order = Order.objects.select_related("table", "waiter", "chef").prefetch_related("lines__item__photo").get(pk=order.pk)
    return _ok(order=ticket_payload(order), notice=notice, overview=overview())


@staff_only
@require_POST
def api_order_create(request):
    data = _body(request)
    lines = data.get("lines") or []
    if not lines:
        return _fail("Add at least one dish to the ticket.")
    with transaction.atomic():
        order = Order.objects.create(
            guest_name=(data.get("guest") or "Guest")[:80],
            channel=data.get("channel", "dinein") if data.get("channel") in dict(Order.CHANNELS) else "dinein",
            party_size=max(1, int(data.get("party") or 2)),
            table_id=data.get("table") or None,
            note=(data.get("note") or "")[:220],
        )
        for position, row in enumerate(lines[:20]):
            item = Item.objects.filter(pk=row.get("item")).first()
            if item is None:
                continue
            order.lines.create(
                item=item, name_at_order=item.name, quantity=max(1, int(row.get("quantity") or 1)),
                unit_price=item.price, position=position, notes=(row.get("notes") or "")[:180],
            )
        order.recompute()
        if order.table_id:
            Table.objects.filter(pk=order.table_id).update(status="ordered", updated_at=timezone.now())
    ActivityLog.record(f"Opened {order.number} for {order.guest_name} · {Restaurant.load().money(order.total)}",
                       verb="created", actor=request.user, obj=order, level="info", table="orders_order")
    return _ok(order=ticket_payload(order), notice=f"{order.number} fired to the kitchen.")


@staff_only
@require_POST
def api_table_update(request):
    data = _body(request)
    table = get_object_or_404(Table, pk=data.get("id"))
    status = data.get("status")
    valid = {value for value, _ in Table.STATES}
    if status not in valid:
        return _fail(f"Unknown table state “{status}”.")
    table.status = status
    table.save(update_fields=["status", "updated_at"])
    if status == "free":
        table.orders.filter(status__in=(Order.SERVED, Order.READY)).update(status=Order.PAID, paid_at=timezone.now(),
                                                                          closed_at=timezone.now())
    return _ok(floor=floor_state(), notice=f"{table.label} marked {table.get_status_display().lower()}.")


@require_GET
def api_floor(request):
    return _ok(floor=floor_state())


@require_POST
def api_guest_order(request):
    """
    Public endpoint used by the guest menu's ‘send to kitchen’ flow.
    Stock is checked before anything is written; each dish reserves what it takes.
    """
    data = _body(request)
    lines = data.get("lines") or []
    if not (1 <= len(lines) <= 12):
        return _fail("Pick between 1 and 12 dishes.")
    venue = Restaurant.load()
    payload, problems = [], []
    with transaction.atomic():
        order = Order.objects.create(
            guest_name=(data.get("guest") or "Web guest")[:80],
            channel="web",
            party_size=max(1, int(data.get("party") or 2)),
            note=(data.get("note") or "")[:220],
        )
        for position, row in enumerate(lines):
            item = Item.objects.select_for_update().filter(pk=row.get("item"), is_available=True).first()
            if item is None:
                problems.append("A dish is no longer on the menu.")
                break
            quantity = max(1, min(12, int(row.get("quantity") or 1)))
            if item.stock < quantity:
                problems.append(f"Only {item.stock} × {item.name} left.")
                break
            order.lines.create(item=item, name_at_order=item.name, quantity=quantity,
                               unit_price=item.price, position=position, notes=(row.get("notes") or "")[:180])
        if problems:
            order.delete()
            return _fail(" ".join(problems), status=409)
        order.recompute()
        for line in order.lines.select_related("item"):
            line.item.consume(line.quantity, reason="sale", reference=order.number)
    ActivityLog.record(f"Web order {order.number} from {order.guest_name}", verb="created",
                       obj=order, level="good", table="orders_order",
                       meta={"total": str(order.total)})
    return _ok(
        number=order.number,
        total=str(order.total),
        currency=venue.currency_symbol,
        notice=f"Ticket {order.number} is in. The pass will call it shortly.",
    )


@staff_only
@require_POST
def api_guest_note(request):
    data = _body(request)
    order = get_object_or_404(Order, pk=data.get("id"))
    GuestNote.objects.update_or_create(
        order=order,
        defaults={"rating": max(1, min(5, int(data.get("rating") or 5))),
                  "message": (data.get("message") or "")[:400], "flags": data.get("flags") or []},
    )
    return _ok(notice="Guest feedback saved on the ticket.")
