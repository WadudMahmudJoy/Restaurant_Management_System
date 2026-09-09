"""
Menu intelligence — the brain behind the "add a dish" form.

The promise we make to the admin:

  * type a name, a price and a stock number — nothing else is mandatory;
  * if the dish (or a near-twin of it) was photographed once, the photo comes
    back by itself — from the twin dish, or from the shared library;
  * if the dish already exists we never silently duplicate it: we offer a
    restock + price change instead;
  * price falls back to that dish's last price, else the chapter median;
  * stock falls back to the dish's par level, else the venue default.

Everything here is pure, deterministic and unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.core.models import ActivityLog, Restaurant

from .models import Category, Item, Photo, normalize


@dataclass
class Suggestion:
    """Everything the UI needs to pre-fill a form the admin didn't have to type."""

    normalized: str = ""
    status: str = "fresh"  # fresh | similar | twin
    twin: dict | None = None
    donor: dict | None = None  # closest existing dish whose photo can be inherited
    match_score: int = 0
    photo: dict | None = None
    photo_basis: str = ""
    library_hits: list[dict] = field(default_factory=list)
    price: str | None = None
    price_basis: str = ""
    stock: int = 0
    stock_basis: str = ""
    restock: dict | None = None
    chapter: dict | None = None
    station: str = "saute"
    prep_minutes: int = 14
    flags: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "normalized": self.normalized,
            "status": self.status,
            "twin": self.twin,
            "donor": self.donor,
            "match_score": self.match_score,
            "photo": self.photo,
            "photo_basis": self.photo_basis,
            "library_hits": self.library_hits,
            "price": self.price,
            "price_basis": self.price_basis,
            "stock": self.stock,
            "stock_basis": self.stock_basis,
            "restock": self.restock,
            "chapter": self.chapter,
            "station": self.station,
            "prep_minutes": self.prep_minutes,
            "flags": self.flags,
        }


def photo_payload(photo: Photo | None, *, basis: str = "", donor_name: str = "") -> dict | None:
    if photo is None or not photo.file:
        return None
    return {
        "id": photo.pk,
        "label": photo.label,
        "url": photo.file.url,
        "width": photo.width,
        "height": photo.height,
        "kb": photo.kb,
        "reuse": photo.reuse_count,
        "basis": basis,
        "donor": donor_name,
    }


def item_payload(item: Item) -> dict:
    return {
        "id": item.pk,
        "name": item.name,
        "subtitle": item.subtitle,
        "category": item.category_id,
        "category_name": item.category.name,
        "accent": item.category.accent,
        "price": str(item.price),
        "cost": str(item.cost) if item.cost is not None else None,
        "compare_price": str(item.compare_price) if item.compare_price is not None else None,
        "stock": item.stock,
        "par_level": item.par_level,
        "low_stock_threshold": item.low_stock_threshold,
        "unit": item.unit,
        "station": item.station,
        "prep_minutes": item.prep_minutes,
        "is_available": item.is_available,
        "is_veg": item.is_veg,
        "is_vegan": item.is_vegan,
        "is_signature": item.is_signature,
        "heat": item.heat,
        "calories": item.calories,
        "description": item.description,
        "allergens": item.allergens,
        "pairs_with": item.pairs_with,
        "tags": item.tags,
        "photo": photo_payload(item.photo),
        "photo_source": item.photo_source,
        "photo_note": item.photo_note,
        "stock_state": item.stock_state,
        "stock_label": item.stock_label,
        "needs_restock": item.needs_restock,
        "margin_pct": item.margin_pct,
        "sold_total": item.sold_total,
        "turn_label": item.turn_label,
        "sell_through_pct": item.sell_through_pct,
        "price_history": [
            {"price": str(pc.new_price), "when": pc.created_at.isoformat(), "delta": pc.delta_pct}
            for pc in item.price_history.all()[:6]
        ],
    }


def _tokens(text: str) -> set[str]:
    return {t for t in normalize(text).split() if len(t) > 2}


def similarity(left: str, right: str) -> int:
    """0–100 Jaccard-ish score with a bonus for a shared first token."""
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 92 if normalize(left) == normalize(right) else 0
    score = len(a & b) / len(a | b)
    if a and b and next(iter(a)) == next(iter(b)):
        score += 0.18
    return int(min(100, round(score * 100)))


def library_matches(key: str, *, limit: int = 4) -> list[Photo]:
    """Photos whose label/tags rhyme with the typed name — used by ‘pick a look’."""
    words = [w for w in key.split() if len(w) > 2]
    if not words:
        return []
    clause = Q()
    for word in words:
        clause |= Q(label__icontains=word) | Q(tags__icontains=word) | Q(notes__icontains=word)
    return list(Photo.objects.filter(clause).order_by("-created_at")[:limit])


def build_suggestion(*, name: str, category_id: int | None = None,
                     price: str | None = None, exclude_pk: int | None = None) -> Suggestion:
    venue = Restaurant.load()
    key = normalize(name)
    out = Suggestion(normalized=key)
    if not key:
        out.flags.append("type at least a dish name")
        return out

    queryset = Item.objects.select_related("category", "photo").exclude(pk=exclude_pk)
    twin = queryset.filter(match_key=key).first()
    if twin is None and category_id:
        twin = queryset.filter(match_key=key, category_id=category_id).first()

    candidates = list(queryset.values("pk", "name", "match_key", "category_id"))
    best_score, best_id = 0, None
    for row in candidates:
        score = similarity(key, row["name"])
        if category_id and row["category_id"] == category_id:
            score += 8
        if score > best_score:
            best_score, best_id = score, row["pk"]

    donor = None
    if best_id and best_score >= 42:
        donor = Item.objects.select_related("category", "photo").get(pk=best_id)
        out.donor = item_payload(donor)
        out.match_score = min(100, best_score)

    out.flags.extend(_name_flags(key, category_id=category_id, twin=twin, donor=donor))

    # ── photo resolution: twin → donor → library ─────────────────────────
    if twin and twin.photo_id:
        out.photo = photo_payload(twin.photo, basis="twin", donor_name=twin.name)
        out.photo_basis = f"Re-using the photo already on “{twin.name}” — nothing to upload."
    elif donor and donor.photo_id:
        out.photo = photo_payload(donor.photo, basis="donor", donor_name=donor.name)
        out.photo_basis = f"Closest match on file is “{donor.name}” — one click to borrow its photo."
    hits = library_matches(key)
    if out.photo is None and hits:
        out.photo = photo_payload(hits[0], basis="library")
        out.photo_basis = "Matched against your photo library — hit use if it looks right."
    out.library_hits = [photo_payload(p) or {} for p in hits]
    out.library_hits = [h for h in out.library_hits if h]

    # ── money ────────────────────────────────────────────────────────────
    if price not in (None, ""):
        out.price = str(price)
        out.price_basis = "your input"
    elif twin:
        out.price = str(twin.price)
        out.price_basis = f"last price on “{twin.name}”"
    else:
        peers = list(queryset.filter(category_id=category_id).values_list("price", flat=True)) if category_id else []
        if len(peers) >= 3:
            out.price = str(Decimal(median(peers)).quantize(Decimal("0.01")))
            out.price_basis = "chapter median"
        else:
            out.price = "18.00"
            out.price_basis = "house default"

    # ── stock ────────────────────────────────────────────────────────────
    if twin:
        out.stock = twin.needs_restock or twin.par_level
        out.stock_basis = f"back to par ({twin.par_level}) — you have {twin.stock} left"
        out.restock = {
            "current": twin.stock,
            "par": twin.par_level,
            "needed": twin.needs_restock,
            "turn_per_day": twin.turn_label,
            "sold_total": twin.sold_total,
        }
        out.status = "twin"
    else:
        out.stock = int(venue.low_stock_default) * 4 or 24
        out.stock_basis = "opening par for a new dish"
        out.status = "similar" if out.photo or out.donor else "fresh"

    if twin:
        out.chapter = {"id": twin.category_id, "name": twin.category.name, "accent": twin.category.accent}
        out.station = twin.station
        out.prep_minutes = twin.prep_minutes
    elif category_id:
        chapter = Category.objects.filter(pk=category_id).first()
        if chapter:
            out.chapter = {"id": chapter.pk, "name": chapter.name, "accent": chapter.accent}
    return out


def _name_flags(key: str, *, category_id: int | None, twin: Item | None, donor: Item | None) -> list[str]:
    flags: list[str] = []
    if twin:
        flags.append(f"“{twin.name}” is already on {twin.category.name} — we'll restock instead of duplicating")
    elif donor:
        flags.append(f"Closest dish on file: “{donor.name}” ({donor.category.name})")
    if twin and not twin.photo_id:
        flags.append("No photo on record yet — one upload now fixes it for every twin")
    elif (twin or donor) and (twin or donor).photo_id:
        flags.append("Photo inherited from the library — no upload needed")
    if category_id is None and not twin:
        flags.append("No chapter chosen — we'll file it under the most fitting one")
    return flags


@transaction.atomic
def quick_save(*, name: str, price: str | None, stock: str | None, category_id: int | None,
               actor=None, photo_file=None, photo_id: int | None = None, mode: str = "auto",
               subtitle: str = "", description: str = "", is_veg: bool = False,
               is_signature: bool = False, heat: int = 0, cost: str | None = None,
               prep_minutes: int | None = None, venue: Restaurant | None = None) -> dict:
    """
    One endpoint for create, restock-and-refresh and edit.

    ``mode``:
      auto     – twin exists → restock + reprice; otherwise create.
      restock  – force the update path (error when there is no twin).
      create   – force a new row (a suffix keeps the unique key happy).
    """
    venue = venue or Restaurant.load()
    errors: list[dict[str, str]] = []
    name = (name or "").strip()
    if len(name) < 2:
        errors.append({"field": "name", "message": "Give the dish a name (2+ characters)."})
    key = normalize(name)
    if not key and not errors:
        errors.append({"field": "name", "message": "That name has no letters to match on."})

    amount = _decimal(price, "price", errors, minimum=Decimal("0"))
    quantity = _integer(stock, "stock", errors, minimum=0)

    chapter = None
    if category_id:
        chapter = Category.objects.filter(pk=category_id).first()
        if chapter is None:
            errors.append({"field": "category", "message": "Unknown chapter."})
    if errors:
        return {"ok": False, "errors": errors}

    twin = Item.objects.select_related("category", "photo").filter(match_key=key).first()
    if chapter is None:
        chapter = _pick_chapter(name=name, twin=twin, venue=venue)

    photo = None
    photo_note = ""
    photo_source = "none"
    reused = False
    if photo_file:
        photo, reused = Photo.find_or_create(file=photo_file, label=name, actor=actor)
        photo_source = "library" if reused else "upload"
        photo_note = "Identical file already in the library — re-linked, not re-uploaded" if reused else "Uploaded now"
    elif photo_id:
        photo = Photo.objects.filter(pk=photo_id).first()
        if photo is None:
            errors.append({"field": "photo", "message": "That library photo no longer exists."})
            return {"ok": False, "errors": errors}
        photo_source, photo_note = "library", "Chosen from the shared library"
    elif twin and twin.photo_id:
        photo, photo_source = twin.photo, "inherited"
        photo_note = f"Re-used the photo already on “{twin.name}”"

    if mode == "restock" and twin is None:
        return {"ok": False, "errors": [{"field": "name", "message": "No existing dish to restock."}]}

    if twin and mode in ("auto", "restock"):
        return _apply_restock(
            twin=twin, photo=photo, photo_source=photo_source, photo_note=photo_note,
            amount=amount, quantity=quantity, actor=actor, subtitle=subtitle, description=description,
            cost=cost, is_veg=is_veg, is_signature=is_signature, heat=heat, venue=venue, reused=reused,
        )

    # ── create path ──────────────────────────────────────────────────────
    display_name = name
    if twin and mode == "create":  # unique (category, match_key) guard
        display_name = f"{name} · II"
    item = Item(
        name=display_name, category=chapter, price=amount, stock=0,
        subtitle=subtitle.strip()[:120], description=description.strip()[:400],
        photo=photo, photo_source=photo_source if photo else "none", photo_note=photo_note,
        is_veg=is_veg, is_signature=is_signature, heat=heat, cost=_decimal(cost, "cost", []),
        par_level=max(12, (quantity or 0) or venue.low_stock_default * 4),
        low_stock_threshold=venue.low_stock_default, added_by=actor,
    )
    try:
        item.save()
    except IntegrityError:
        item.name = f"{name} · {chapter.name}"
        item.save()
    if quantity:
        item.restock(quantity, actor=actor, reason="seed", note="opening balance")
    if amount and item.price_history.count() == 0:
        from .models import PriceChange

        PriceChange.objects.create(item=item, old_price=Decimal("0.00"), new_price=amount,
                                   reason="launch price", actor=actor)
    ActivityLog.record(
        f"New dish “{item.name}” — {venue.money(amount)}"
        + (f" · photo {('re-linked from library' if photo_source == 'library' else 'attached')}" if photo else " · no photo yet"),
        verb="created", actor=actor, obj=item, level="good", link=f"/studio/?item={item.pk}",
    )
    return {
        "ok": True,
        "action": "created",
        "item": item_payload(item),
        "notice": _create_notice(photo, reused, photo_source),
    }


def _create_notice(photo, reused: bool, source: str) -> str:
    if photo is None:
        return "Saved. Add a photo any time — future re-adds will inherit it automatically."
    if reused:
        return "Saved. That photo was already in your library, so it was re-linked instead of re-uploaded."
    if source == "inherited":
        return "Saved — the photo was pulled from an existing twin dish for you."
    return "Saved. Photo stored in the shared library; any future twin dish will inherit it."


def _apply_restock(*, twin: Item, photo, photo_source: str, photo_note: str, amount, quantity,
                   actor, subtitle: str, description: str, cost, is_veg: bool, is_signature: bool,
                   heat: int, venue: Restaurant, reused: bool) -> dict:
    before = twin.stock
    changed: list[str] = []
    if amount is not None and amount != twin.price:
        twin.set_price(amount, actor=actor, reason="menu update")
        changed.append(f"price → {venue.money(amount)}")
    if quantity:
        twin.restock(quantity, actor=actor, reason="restock", note="smart add")
        changed.append(f"stock {before} → {twin.stock}")
    if photo and twin.photo_id != photo.pk:
        twin.photo = photo
        twin.photo_source = photo_source or "library"
        twin.photo_note = photo_note
        twin.save(update_fields=["photo", "photo_source", "photo_note", "updated_at"])
        changed.append("photo updated")
    for attr, value in (("subtitle", subtitle), ("description", description),
                        ("is_veg", is_veg), ("is_signature", is_signature)):
        if value not in ("", None):
            setattr(twin, attr, value)
    if cost:
        twin.cost = _decimal(cost, "cost", [])
    if heat:
        twin.heat = heat
    twin.is_available = True
    twin.save()
    ActivityLog.record(
        f"Restocked “{twin.name}” (+{quantity or 0} {twin.unit})",
        verb="restocked" if quantity else "updated", actor=actor, obj=twin,
        level="good" if quantity else "info", link=f"/studio/?item={twin.pk}",
    )
    return {
        "ok": True,
        "action": "restocked",
        "item": item_payload(twin),
        "notice": "Twin dish found — updated in place instead of creating a duplicate."
        + (f" {' · '.join(changed)}." if changed else ""),
    }


def _decimal(raw, field: str, errors: list, *, minimum=None) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        errors.append({"field": field, "message": "Use a number like 18.50."})
        return None
    if minimum is not None and value < minimum:
        errors.append({"field": field, "message": f"Must be at least {minimum}."})
    return value


def _integer(raw, field: str, errors: list, *, minimum=None) -> int | None:
    if raw in (None, ""):
        return None
    try:
        value = int(float(str(raw)))
    except (TypeError, ValueError):
        errors.append({"field": field, "message": "Use a whole number."})
        return None
    if minimum is not None and value < minimum:
        errors.append({"field": field, "message": f"Must be {minimum} or more."})
        value = minimum
    return value


def _pick_chapter(*, name: str, twin: Item | None, venue: Restaurant) -> Category:
    if twin:
        return twin.category
    key = set(normalize(name).split())
    chapters = list(Category.objects.live())
    best, best_score = None, 0
    for chapter in chapters:
        score = len(key & _tokens(chapter.name)) * 3 + len(key & _tokens(chapter.blurb or ""))
        if score > best_score:
            best, best_score = chapter, score
    if best:
        return best
    return chapters[0] if chapters else Category.objects.create(name="Chef's picks", blurb="Everything new")
