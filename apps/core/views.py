"""Public pages (landing, login) plus the dashboard shell and data vault."""
from __future__ import annotations

import json

from django.contrib.auth import authenticate, login, logout
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.analytics import overview
from apps.core.branding import VERSION
from apps.core.models import ActivityLog, Restaurant
from apps.menu.models import Category, Item, Photo, PriceChange, StockMovement
from apps.menu.views import item_payload
from apps.orders.models import GuestNote, Order, OrderLine, Payment, Table


def staff_only(view):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            if request.path.startswith("/api/"):
                return JsonResponse({"ok": False, "error": "Staff sign-in required."}, status=403)
            return redirect(f"/login/?next={request.path}")
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    return wrapper


#: A curated, honest view of the schema for the landing page's data section.
SCHEMA_DOC = [
    (Category, "menu_chapter", ["name", "accent", "service_order"]),
    (Photo, "menu_photo", ["file", "checksum", "reuse_count"]),
    (Item, "menu_dish", ["name", "price", "stock", "photo"]),
    (PriceChange, "menu_price_ledger", ["old_price", "new_price", "actor"]),
    (StockMovement, "menu_stock_ledger", ["direction", "quantity", "balance_after"]),
    (Table, "service_floor", ["label", "zone", "x / y", "status"]),
    (Order, "service_ticket", ["number", "status", "total", "table"]),
    (OrderLine, "service_line", ["item", "quantity", "unit_price"]),
    (Payment, "service_payment", ["method", "amount", "tip"]),
    (GuestNote, "service_feedback", ["rating", "message"]),
    (ActivityLog, "core_journal", ["verb", "message", "actor"]),
]


# ── public ───────────────────────────────────────────────────────────────
def home(request):
    """Landing page: WebGL hero fed by live menu data."""
    venue = Restaurant.load()
    featured = list(Item.objects.live().ready().order_by("-is_signature", "-sold_total")[:8])
    schema = [
        {"name": label, "rows": model.objects.count(),
         "columns": [{"name": col, "kind": _kind_label(model, col)} for col in columns]}
        for model, label, columns in SCHEMA_DOC
    ]
    context = {
        "venue": venue,
        "version": VERSION,
        "featured_items": featured,
        "featured": [
            {"name": item.name, "price": str(item.price), "photo": item.photo_url,
             "accent": item.category.accent, "chapter": item.category.name, "id": item.pk,
             "subtitle": item.subtitle, "stock": item.stock}
            for item in featured
        ],
        "schema": schema,
        "stats": {
            "dishes": Item.objects.filter(is_available=True).count(),
            "chapters": Category.objects.live().count(),
            "photos": Photo.objects.count(),
            "shared_photos": Photo.objects.exclude(items__isnull=True).count(),
            "tickets_today": Order.objects.filter(paid_at__date=timezone.localdate()).count(),
            "tables": Table.objects.filter(is_active=True).count(),
        },
    }
    return render(request, "public/home.html", context)


def _kind_label(model, column: str) -> str:
    field = None
    try:
        field = model._meta.get_field(column)
    except Exception:
        pass
    if field is None:
        return "computed"
    return getattr(field, "get_internal_type", lambda: "field")().replace("Field", "").lower()


def login_view(request):
    venue = Restaurant.load()
    error = None
    next_url = request.POST.get("next") or request.GET.get("next") or "/dashboard/"
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is None:
            error = "That username and password don't match a team record."
        elif not (user.is_staff or user.is_superuser):
            error = "This door is for team members. Guests can browse the menu instead."
        else:
            login(request, user)
            ActivityLog.record(f"{user.get_username()} signed in", verb="signed-in", actor=user, level="info")
            return redirect(next_url if next_url.startswith("/") else "/dashboard/")
    return render(request, "registration/login.html", {"error": error, "venue": venue, "next": next_url})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("/")


# ── staff ────────────────────────────────────────────────────────────────
@staff_only
def dashboard(request):
    return render(request, "dashboard/overview.html", {"version": VERSION})


@staff_only
def vault(request):
    """The data vault: a live, decorated view of the schema itself."""
    return render(request, "dashboard/vault.html", {"version": VERSION})


@staff_only
@require_GET
def api_vault_schema(request):
    from django.apps import apps as django_apps

    skip = {"contenttypes", "auth.permission", "admin.logentry", "sessions.session", "auth.user", "auth.group"}
    tables = []
    for model in django_apps.get_models():
        label = model._meta.label_lower
        if label.startswith("django_") or label in skip:
            continue
        fields = []
        for field in model._meta.get_fields():
            concrete = bool(getattr(field, "concrete", False))
            if not (concrete or field.one_to_many or getattr(field, "many_to_many", False)):
                continue
            internal = getattr(field, "get_internal_type", lambda: "")()
            if getattr(field, "primary_key", False):
                kind = "id"
            elif getattr(field, "one_to_one", False) and concrete:
                kind = "1:1"
            elif getattr(field, "many_to_one", False):
                kind = "FK"
            elif field.one_to_many:
                kind = "M2O"
            elif getattr(field, "many_to_many", False):
                kind = "M2M"
            elif field.name == "file":
                kind = "file"
            elif internal == "JSONField":
                kind = "json"
            elif internal == "BooleanField":
                kind = "bool"
            elif getattr(field, "decimal_places", None) is not None:
                kind = "money"
            elif internal in {"DateTimeField", "TimeField", "DateField"}:
                kind = "time"
            elif internal.endswith("IntegerField"):
                kind = "num"
            elif internal in {"CharField", "TextField", "SlugField"}:
                kind = "text"
            else:
                kind = "field"
            fields.append(
                {
                    "name": field.name,
                    "label": str(getattr(field, "verbose_name", field.name)).capitalize(),
                    "kind": kind,
                    "required": bool(getattr(field, "blank", True) is False),
                    "unique": bool(getattr(field, "unique", False)),
                    "related": field.related_model._meta.db_table if field.is_relation else "",
                    "help": str(getattr(field, "help_text", "") or ""),
                    "indexed": bool(getattr(field, "db_index", False)),
                }
            )
        tables.append(
            {
                "model": model.__name__,
                "label": str(model._meta.verbose_name).title(),
                "plural": str(model._meta.verbose_name_plural).title(),
                "table": model._meta.db_table,
                "app": model._meta.app_label,
                "rows": model.objects.count(),
                "doc": (model.__doc__ or "").strip().splitlines()[0] if model.__doc__ else "",
                "fields": fields,
                "indexes": [idx.name for idx in model._meta.indexes],
                "constraints": [c.name for c in model._meta.constraints],
            }
        )
    order = {"core": 0, "accounts": 1, "menu": 2, "orders": 3}
    tables.sort(key=lambda row: (order.get(row["app"], 9), row["model"]))
    return JsonResponse(
        {
            "ok": True,
            "tables": tables,
            "database": {
                "engine": "SQLite" if "sqlite" in connection.vendor else connection.vendor,
                "name": str(connection.settings_dict["NAME"]).split("/")[-1],
                "size_kb": _db_size_kb(),
                "pragma": _sqlite_pragmas(),
                "journal_rows": ActivityLog.objects.count(),
            },
        },
        json_dumps_params={"default": str},
    )


def _db_size_kb() -> int:
    from pathlib import Path

    from django.conf import settings

    path = Path(str(settings.DATABASES["default"]["NAME"]))
    return int(path.stat().st_size / 1024) if path.exists() else 0


def _sqlite_pragmas() -> dict:
    out = {}
    if "sqlite" not in connection.vendor:
        return out
    with connection.cursor() as cursor:
        for pragma in ("journal_mode", "foreign_keys", "synchronous", "page_size"):
            try:
                cursor.execute(f"PRAGMA {pragma};")
                row = cursor.fetchone()
                out[pragma] = row[0] if row else None
            except Exception:  # pragma: no cover
                out[pragma] = "n/a"
    return out


@staff_only
@require_GET
def api_dashboard(request):
    return JsonResponse(overview(), json_dumps_params={"default": str})


@require_GET
def api_health(request):
    venue = Restaurant.load()
    return JsonResponse(
        {
            "ok": True,
            "venue": venue.name,
            "open": venue.is_open_now,
            "hours": venue.hours_label,
            "dishes": Item.objects.filter(is_available=True).count(),
            "open_tickets": Order.objects.exclude(status__in=Order.CLOSED_STATES).count(),
            "version": VERSION,
        }
    )
