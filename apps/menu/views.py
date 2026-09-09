"""HTTP layer for the menu: pages + the JSON API the studio talks to."""
from __future__ import annotations

import json
from decimal import Decimal

from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import ActivityLog, Restaurant

from .intelligence import build_suggestion, item_payload, quick_save
from .models import Category, Item, Photo


# ── helpers ──────────────────────────────────────────────────────────────
def _body(request) -> dict:
    if request.content_type and "multipart/form-data" in request.content_type:
        data = {key: value for key, value in request.POST.items()}
        if request.FILES:
            data["_files"] = {key: request.FILES[key] for key in request.FILES}
        return data
    try:
        return json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def _ok(**payload) -> JsonResponse:
    return JsonResponse({"ok": True, **payload})


def _fail(message: str, *, field: str = "", status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message, "field": field, "errors": [
        {"field": field, "message": message}
    ]}, status=status)


def staff_only(view):
    """Small decorator so API responses stay JSON instead of a login redirect."""

    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            if request.path.startswith("/api/"):
                return JsonResponse({"ok": False, "error": "Sign in as staff to change the menu."}, status=403)
            return redirect(f"/login/?next={request.path}")
        return view(request, *args, **kwargs)

    wrapper.__name__ = view.__name__
    return wrapper


def _photo_payload(photo: Photo) -> dict:
    return {
        "id": photo.pk,
        "label": photo.label,
        "url": photo.file.url if photo.file else "",
        "width": photo.width,
        "height": photo.height,
        "kb": photo.kb,
        "reuse": photo.reuse_count,
        "shared": photo.is_shared,
        "tags": photo.tags or [],
        "notes": photo.notes,
        "source": photo.source,
        "added": photo.created_at.strftime("%d %b"),
        "checksum": photo.checksum,
    }


# ── pages ────────────────────────────────────────────────────────────────
def guest_menu(request):
    """Public 3D menu. Guests can browse and fire a web order."""
    venue = Restaurant.load()
    categories = list(Category.objects.live().with_counts())
    items = list(
        Item.objects.live().exclude(stock=0).ready()
        .order_by("category__service_order", "-is_signature", "name")
    )
    by_chapter: dict[int, list[dict]] = {}
    for item in items:
        by_chapter.setdefault(item.category_id, []).append(item_payload(item))
    chapters = [
        {
            "id": chapter.pk,
            "name": chapter.name,
            "slug": chapter.slug,
            "icon": chapter.icon,
            "accent": chapter.accent,
            "blurb": chapter.blurb,
            "items": by_chapter.get(chapter.pk, []),
        }
        for chapter in categories
        if by_chapter.get(chapter.pk)
    ]
    context = {
        "venue": venue,
        "chapters": chapters,
        "chapters_count": len(chapters),
        "dish_count": len(items),
    }
    return render(request, "public/menu.html", context)


@staff_only
def studio(request):
    """The admin surface: add / restock / reprice with the smart assist."""
    venue = Restaurant.load()
    items = list(Item.objects.ready().order_by("-updated_at")[:200])
    photos = [_photo_payload(photo) for photo in Photo.objects.all()[:120]]
    seed = {
        "categories": [
            {"id": c.pk, "name": c.name, "icon": c.icon, "accent": c.accent,
             "items": c.items.count(), "blurb": c.blurb}
            for c in Category.objects.live().with_counts()
        ],
        "items": [item_payload(item) for item in items],
        "photos": photos,
        "currency": venue.currency_symbol,
        "low_stock_default": venue.low_stock_default,
    }
    context = {
        "venue": venue,
        "seed": seed,
        "counts": {
            "total": Item.objects.count(),
            "live": Item.objects.filter(is_available=True).count(),
            "low": Item.objects.low_stock().count(),
            "no_photo": Item.objects.without_photo().count(),
            "photos": len(photos),
            "shared": sum(1 for photo in photos if photo["reuse"] > 1),
        },
    }
    return render(request, "dashboard/studio.html", context)


# ── API: reads ───────────────────────────────────────────────────────────
@require_GET
def api_items(request):
    view = request.GET.get("view", "all")
    query = Item.objects.ready()
    if term := request.GET.get("q", "").strip():
        query = query.searchable(term)
    if chapter := request.GET.get("category"):
        query = query.filter(category_id=chapter)
    if view == "low":
        query = query.low_stock()
    elif view == "out":
        query = query.filter(stock=0)
    elif view == "no-photo":
        query = query.without_photo()
    elif view == "hidden":
        query = query.filter(is_available=False)
    elif view == "featured":
        query = query.filter(is_signature=True)
    total = query.count()
    items = [item_payload(item) for item in query.order_by("-updated_at")[:120]]
    return _ok(items=items, total=total, counts={
        "all": Item.objects.count(),
        "live": Item.objects.filter(is_available=True).count(),
        "low": Item.objects.low_stock().count(),
        "out": Item.objects.filter(stock=0).count(),
        "no-photo": Item.objects.without_photo().count(),
        "hidden": Item.objects.filter(is_available=False).count(),
        "featured": Item.objects.filter(is_signature=True).count(),
    })


@require_GET
def api_suggest(request):
    suggestion = build_suggestion(
        name=request.GET.get("name", ""),
        category_id=int(cid) if (cid := request.GET.get("category", "")) and cid.isdigit() else None,
        price=request.GET.get("price") or None,
        exclude_pk=int(pk) if (pk := request.GET.get("exclude", "")) and pk.isdigit() else None,
    )
    return _ok(suggestion=suggestion.as_json())


@require_GET
def api_photos(request):
    return _ok(photos=[_photo_payload(photo) for photo in Photo.objects.all()[:300]])


# ── API: writes ──────────────────────────────────────────────────────────
@staff_only
@require_POST
def api_save(request):
    data = _body(request)
    files = data.pop("_files", {}) or {}
    result = quick_save(
        name=data.get("name", ""),
        price=data.get("price"),
        stock=data.get("stock"),
        category_id=data.get("category") or None,
        actor=request.user,
        photo_file=files.get("photo"),
        photo_id=int(data["photo_id"]) if str(data.get("photo_id", "")).isdigit() else None,
        mode=data.get("mode", "auto"),
        subtitle=data.get("subtitle", ""),
        description=data.get("description", ""),
        is_veg=bool(data.get("is_veg")) or data.get("is_veg") == "true",
        is_signature=bool(data.get("is_signature")) or data.get("is_signature") == "true",
        heat=int(data["heat"]) if str(data.get("heat", "")).lstrip("-").isdigit() else 0,
        cost=data.get("cost"),
        venue=Restaurant.load(),
    )
    if not result.get("ok"):
        first = (result.get("errors") or [{}])[0]
        return _fail(first.get("message", "Could not save."), field=first.get("field", ""))
    return _ok(**result)


@staff_only
@require_POST
def api_restock(request):
    data = _body(request)
    item = get_object_or_404(Item, pk=data.get("id"))
    quantity = int(data.get("quantity", 0) or 0)
    if quantity <= 0:
        return _fail("Enter how many portions to add.", field="quantity")
    item.restock(quantity, actor=request.user, reason=data.get("reason", "restock"), note=data.get("note", ""))
    ActivityLog.record(
        f"Restocked “{item.name}” +{quantity} → {item.stock} {item.unit}",
        verb="restocked", actor=request.user, obj=item, level="good", link="/studio/",
    )
    return _ok(item=item_payload(item), notice=f"+{quantity} {item.unit} on the shelf.")


@staff_only
@require_POST
def api_price(request):
    data = _body(request)
    item = get_object_or_404(Item, pk=data.get("id"))
    try:
        new = Decimal(str(data.get("price", "")))
    except Exception:
        return _fail("That price is not a number.", field="price")
    old = item.price
    item.set_price(new, actor=request.user, reason=data.get("reason", "manual"))
    ActivityLog.record(
        f"Repriced “{item.name}” {Restaurant.load().money(old)} → {Restaurant.load().money(new)}",
        verb="priced", actor=request.user, obj=item, level="info", link="/studio/",
    )
    return _ok(item=item_payload(item))


@staff_only
@require_POST
def api_toggle(request):
    data = _body(request)
    item = get_object_or_404(Item, pk=data.get("id"))
    item.is_available = not item.is_available
    item.save(update_fields=["is_available", "updated_at"])
    if not item.is_available:
        ActivityLog.record(f"86’d “{item.name}”", verb="eighty-sixed", actor=request.user,
                           obj=item, level="warn", link="/studio/")
    else:
        ActivityLog.record(f"Put “{item.name}” back on the menu", verb="updated", actor=request.user,
                           obj=item, level="good", link="/studio/")
    return _ok(item=item_payload(item))


@staff_only
@require_POST
def api_adjust(request):
    """Nudge stock either way — waste, miscount, correction. Writes the ledger."""
    data = _body(request)
    item = get_object_or_404(Item, pk=data.get("id"))
    try:
        quantity = int(data.get("quantity", 0) or 0)
    except (TypeError, ValueError):
        return _fail("Use a whole number.", field="quantity")
    if quantity > 0:
        item.restock(quantity, actor=request.user, reason=data.get("reason", "count"))
    elif quantity < 0:
        from .models import StockMovement

        new_stock = max(0, item.stock + quantity)
        item.stock = new_stock
        item.save(update_fields=["stock", "updated_at"])
        StockMovement.objects.create(
            item=item, direction="ADJUST", quantity=abs(quantity), balance_after=new_stock,
            reason=data.get("reason", "count"), actor=request.user, note=(data.get("note") or "")[:180],
        )
    else:
        return _fail("Nothing to adjust.", field="quantity")
    item.refresh_from_db()
    ActivityLog.record(
        f"Adjusted “{item.name}” {signed(quantity)} → {item.stock} {item.unit}",
        verb="restocked", actor=request.user, obj=item, level="info", link="/studio/",
    )
    return _ok(item=item_payload(item), notice=f"{item.name}: {item.stock} {item.unit} on the shelf.")


def signed(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


@staff_only
@require_POST
def api_delete(request):
    data = _body(request)
    item = get_object_or_404(Item, pk=data.get("id"))
    name, chapter = item.name, item.category.name
    if item.order_lines.exists():
        item.is_available = False
        item.save(update_fields=["is_available", "updated_at"])
        ActivityLog.record(f"Hid “{name}” — sold history kept", verb="eighty-sixed", actor=request.user,
                           obj=item, level="warn")
        return _ok(notice="That dish has sales history, so it was 86'd instead of deleted.", archived=True)
    item.delete()
    ActivityLog.record(f"Deleted “{name}” from {chapter}", verb="deleted", actor=request.user, level="bad")
    return _ok(notice=f"“{name}” removed.")


@staff_only
@require_POST
def api_photo_attach(request):
    """One click: borrow a photo from the library (or a twin dish) for a dish."""
    data = _body(request)
    item = get_object_or_404(Item, pk=data.get("item"))
    photo = None
    basis = "library"
    if photo_id := data.get("photo_id"):
        photo = Photo.objects.filter(pk=photo_id).first()
    elif twin_id := data.get("from_item"):
        twin = Item.objects.filter(pk=twin_id).select_related("photo").first()
        photo = twin.photo if twin else None
        basis = "inherited"
        if twin:
            item.photo_note = f"Re-used from “{twin.name}”"
    if photo is None:
        return _fail("That photo is no longer in the library.", field="photo_id")
    item.photo = photo
    item.photo_source = basis
    item.save(update_fields=["photo", "photo_source", "photo_note", "updated_at"])
    ActivityLog.record(f"Attached “{photo.label}” to “{item.name}”", verb="imaged", actor=request.user,
                       obj=item, level="good", link="/studio/")
    twins = Item.objects.filter(match_key=item.match_key).exclude(pk=item.pk).count()
    return _ok(
        item=item_payload(item),
        notice=f"Photo attached. {f'{twins} twin dish(es) inherit it automatically.' if twins else 'Future twins inherit it automatically.'}",
    )


@staff_only
@require_POST
def api_photo_upload(request):
    files = _body(request).get("_files", {}) or {}
    file = files.get("photo") or files.get("file")
    if not file:
        return _fail("No file received.", field="photo")
    if file.size > 8 * 1024 * 1024:
        return _fail("Keep photos under 8 MB.", field="photo")
    photo, reused = Photo.find_or_create(
        file=file, label=request.POST.get("label", "") or file.name.rsplit(".", 1)[0],
        actor=request.user, source="upload",
    )
    return _ok(
        photo=_photo_payload(photo),
        reused=reused,
        notice="That exact photo was already in the library — re-linked, nothing re-uploaded."
        if reused
        else "Stored once in the library, ready for every twin dish.",
    )


@staff_only
@require_POST
def api_photo_delete(request):
    data = _body(request)
    photo = get_object_or_404(Photo, pk=data.get("id"))
    label = photo.label
    photo.delete()
    ActivityLog.record(f"Removed “{label}” from the library", verb="deleted", actor=request.user, level="bad")
    return _ok(notice=f"“{label}” deleted — dishes stayed on the menu, just unphotographed.")


@staff_only
@require_GET
def api_item_detail(request, pk: int):
    item = get_object_or_404(Item.objects.ready().prefetch_related("price_history__actor"), pk=pk)
    payload = item_payload(item)
    payload["ledger"] = [
        {"direction": move.get_direction_display(), "quantity": move.quantity, "balance": move.balance_after,
         "reason": move.reason, "who": move.actor.username if move.actor_id else "system",
         "when": move.created_at.strftime("%d %b · %H:%M"), "reference": move.reference}
        for move in item.stock_moves.all()[:12]
    ]
    return _ok(item=payload)


def api_public_menu(request):
    """Used by the landing page's live strip and the guest menu filter bar."""
    chapters = [
        {"id": c.pk, "name": c.name, "icon": c.icon, "accent": c.accent}
        for c in Category.objects.live().with_counts()
        if c.items_available
    ]
    return _ok(chapters=chapters)
