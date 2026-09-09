"""
Menu models — the heart of the system.

Tables
------
menu_category     chapters of the printed menu (Starters, Grill, Bar, …)
menu_photo        *shared* photo library; a photo is stored once, re-used forever
menu_item         a dish: name · price · stock (+ plenty of smart metadata)
menu_pricechange  immutable price ledger, so a dish remembers what it cost
menu_stockmovement  stock ledger (IN/OUT/ADJUST) — the truth behind the numbers

The photo library is what makes the admin form smart: uploading a picture for
"Wild Mushroom Risotto" today means tomorrow's edit, tomorrow's re-add and next
season's relaunch all inherit it automatically.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files.images import get_image_dimensions
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core.models import TimeStampedModel

NON_ALNUM = re.compile(r"[^a-z0-9]+")
STOPWORDS = {"the", "a", "an", "of", "with", "and", "&", "dish", "plate", "classic", "house"}


def normalize(text: str) -> str:
    """'Wild Mushroom Risotto (v)' → 'wild mushroom risotto' — the match key."""
    cleaned = NON_ALNUM.sub(" ", (text or "").lower()).strip()
    tokens = [t for t in cleaned.split() if len(t) > 1 and t not in STOPWORDS]
    return " ".join(tokens) if tokens else cleaned.replace(" ", "")


class CategoryQuerySet(models.QuerySet):
    def live(self):
        return self.filter(is_active=True)

    def with_counts(self):
        return self.annotate(
            items_total=models.Count("items", distinct=True),
            items_available=models.Count("items", filter=models.Q(items__is_available=True), distinct=True),
        )


class Category(TimeStampedModel):
    """A chapter of the menu. Accent colour decorates both admin and guest UI."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True, blank=True)
    blurb = models.CharField(max_length=160, blank=True)
    accent = models.CharField(max_length=9, default="#D8B26A")
    icon = models.CharField(max_length=6, default="✦", help_text="One glyph — used as the chapter mark.")
    service_order = models.PositiveSmallIntegerField(default=50, db_index=True)
    is_active = models.BooleanField(default=True)

    objects = CategoryQuerySet.as_manager()

    class Meta:
        verbose_name = "menu chapter"
        verbose_name_plural = "menu chapters"
        ordering = ["service_order", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:70] or "chapter"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.icon}  {self.name}"

    @property
    def item_count(self) -> int:
        return self.items.count()


class PhotoQuerySet(models.QuerySet):
    def used(self):
        return self.filter(items__isnull=False).distinct()

    def unused(self):
        return self.filter(items__isnull=True)


class Photo(TimeStampedModel):
    """
    Shared photo library. Deduplicated by content checksum, so the same picture
    uploaded twice is stored once and re-linked — that is the whole trick behind
    "don't add the image again".
    """

    SOURCES = [("upload", "Uploaded"), ("seed", "Studio library"), ("scan", "Imported")]

    file = models.ImageField(upload_to="uploads/menu/%Y/%m/", width_field=None, height_field=None)
    label = models.CharField(max_length=90, blank=True, help_text="Shown in the library picker.")
    checksum = models.CharField(max_length=40, unique=True, editable=False, db_index=True)
    width = models.PositiveSmallIntegerField(default=0)
    height = models.PositiveSmallIntegerField(default=0)
    bytes = models.PositiveIntegerField(default=0, help_text="File size in bytes.")
    tags = models.JSONField(default=list, blank=True)
    notes = models.CharField(max_length=180, blank=True)
    source = models.CharField(max_length=6, choices=SOURCES, default="upload")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="photos"
    )

    objects = PhotoQuerySet.as_manager()

    class Meta:
        verbose_name = "photo"
        verbose_name_plural = "photo library"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.label or (self.file.name.rsplit("/", 1)[-1] if self.file else "untitled photo")

    # ── fingerprinting / dimensions ────────────────────────────────────
    @staticmethod
    def fingerprint(content) -> str:
        digest = hashlib.sha1()
        try:
            content.seek(0)
            for chunk in iter(lambda: content.read(65536), b""):
                digest.update(chunk)
            content.seek(0)
        except Exception:  # pragma: no cover - non-seekable stream
            digest.update(str(id(content)).encode())
        return digest.hexdigest()

    def refresh_dimensions(self):
        try:
            if self.file:
                self.bytes = self.file.size or 0
                width, height = get_image_dimensions(self.file)
                self.width, self.height = width or 0, height or 0
        except Exception:  # pragma: no cover - Pillow missing / unreadable file
            pass

    def save(self, *args, **kwargs):
        if not self.label and self.file:
            stem = self.file.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            self.label = slugify(stem).replace("-", " ").title()[:90]
        super().save(*args, **kwargs)

    @classmethod
    def find_or_create(cls, *, file=None, url: str = "", label: str = "", actor=None, tags=None, source="upload"):
        """
        Dedupe by checksum: if the exact picture already lives in the library we
        return that row instead of writing a second file. Callers get a photo and
        a boolean telling them it was inherited rather than newly stored.
        """
        if file is not None:
            checksum = cls.fingerprint(file)
            existing = cls.objects.filter(checksum=checksum).first()
            if existing:
                return existing, True
            photo = cls(file=file, label=label, checksum=checksum, uploaded_by=actor, source=source, tags=tags or [])
            photo.refresh_dimensions()
            photo.save()
            return photo, False
        if url:
            photo = cls.objects.filter(file=url).first()
            if photo:
                return photo, True
            photo = cls(file=url, label=label, checksum=hashlib.sha1(url.encode()).hexdigest(), source=source, tags=tags or [])
            photo.refresh_dimensions()
            photo.save()
            return photo, False
        raise ValueError("Photo.find_or_create needs either file or url")

    # ── usage bookkeeping ───────────────────────────────────────────────
    @property
    def reuse_count(self) -> int:
        return self.items.count()

    @property
    def is_shared(self) -> bool:
        return self.reuse_count > 1

    @property
    def kb(self) -> int:
        return int(self.bytes / 1024) if self.bytes else 0


class ItemQuerySet(models.QuerySet):
    def live(self):
        return self.filter(is_available=True, category__is_active=True)

    def with_photo(self):
        return self.filter(photo__isnull=False)

    def without_photo(self):
        return self.filter(photo__isnull=True)

    def out_of_stock(self):
        return self.filter(models.Q(stock=0) | models.Q(is_available=False, stock=0))

    def low_stock(self):
        return self.filter(stock__gt=0, stock__lte=models.F("low_stock_threshold"))

    def need_attention(self):
        return self.filter(models.Q(stock__lte=models.F("low_stock_threshold")) | models.Q(is_available=False))

    def searchable(self, term: str):
        term = (term or "").strip()
        if not term:
            return self
        key = normalize(term)
        from django.db.models import Q

        clause = Q(name__icontains=term) | Q(subtitle__icontains=term) | Q(description__icontains=term)
        if key:
            clause |= models.Q(match_key__icontains=key)
        for token in key.split():
            clause |= models.Q(match_key__icontains=token)
        return self.filter(clause)

    def ready(self):
        return self.select_related("category", "photo", "added_by")


class Item(TimeStampedModel):
    """A dish on the menu. Add it with three fields; the rest is inferred."""

    STOCK_STATES = [("out", "86 / sold out"), ("low", "low"), ("steady", "steady"), ("ample", "ample")]
    STATIONS = [("garde", "Garde manger"), ("saute", "Sauté"), ("grill", "Grill"), ("tandoor", "Tandoor"), ("pastry", "Pastry"), ("bar", "Bar")]
    PHOTO_SOURCES = [
        ("none", "No photo"),
        ("upload", "Uploaded now"),
        ("library", "Picked from library"),
        ("inherited", "Auto-inherited from a twin dish"),
    ]

    name = models.CharField(max_length=90, db_index=True)
    match_key = models.CharField(max_length=90, db_index=True, editable=False, help_text="Normalised name used for smart matching.")
    subtitle = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True, max_length=400)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    compare_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Was-price; drives the struck-through offer.")
    cost = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    stock = models.PositiveIntegerField(default=0)
    par_level = models.PositiveSmallIntegerField(default=24, help_text="Target level the smart restock nudges you to.")
    low_stock_threshold = models.PositiveSmallIntegerField(default=6)
    unit = models.CharField(max_length=12, default="portions")

    photo = models.ForeignKey(Photo, null=True, blank=True, on_delete=models.SET_NULL, related_name="items")
    photo_source = models.CharField(max_length=9, choices=PHOTO_SOURCES, default="none", editable=False)
    photo_note = models.CharField(max_length=140, blank=True, editable=False)

    station = models.CharField(max_length=8, choices=STATIONS, default="saute")
    prep_minutes = models.PositiveSmallIntegerField(default=14)
    calories = models.PositiveSmallIntegerField(null=True, blank=True)
    protein_g = models.PositiveSmallIntegerField(null=True, blank=True)

    is_veg = models.BooleanField("vegetarian", default=False)
    is_vegan = models.BooleanField(default=False)
    heat = models.PositiveSmallIntegerField(default=0, help_text="0–3 chilli marks.")
    is_signature = models.BooleanField("signature dish", default=False)
    is_seasonal = models.BooleanField(default=False)
    is_available = models.BooleanField("on the menu", default=True)
    allergens = models.JSONField(default=list, blank=True)
    pairs_with = models.JSONField(default=list, blank=True, help_text="Names of dishes that upsell well with this one.")
    tags = models.JSONField(default=list, blank=True)

    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="dishes_added"
    )
    published_at = models.DateTimeField(null=True, blank=True)
    sold_total = models.PositiveIntegerField(default=0, editable=False)
    last_sold_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = ItemQuerySet.as_manager()

    class Meta:
        verbose_name = "dish"
        verbose_name_plural = "dishes"
        ordering = ["category__service_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["category", "match_key"], name="uniq_dish_per_chapter"),
            models.CheckConstraint(condition=models.Q(price__gte=Decimal("0")), name="price_not_negative"),
        ]
        indexes = [
            models.Index(fields=["category", "is_available"], name="idx_dish_chapter_avail"),
            models.Index(fields=["-price"], name="idx_dish_price"),
            models.Index(fields=["-last_sold_at"], name="idx_dish_last_sold"),
        ]

    def __str__(self) -> str:
        return f"{self.name} · {self.price}"

    # ── keys ─────────────────────────────────────────────────────────────
    @property
    def slug(self) -> str:
        return slugify(self.name)[:70] or f"dish-{self.pk}"

    def save(self, *args, **kwargs):
        self.match_key = normalize(self.name) or self.name.lower()[:90]
        if self.price is None:
            self.price = Decimal("0")
        if self.is_available and not self.published_at:
            self.published_at = timezone.now()
        if self.photo_id and self.photo_source == "none":
            self.photo_source = "library"
        super().save(*args, **kwargs)

    # ── derived presentation ─────────────────────────────────────────────
    @property
    def stock_state(self) -> str:
        if not self.is_available or self.stock <= 0:
            return "out"
        if self.stock <= self.low_stock_threshold:
            return "low"
        if self.stock <= max(self.par_level, 1) * 0.6:
            return "steady"
        return "ample"

    @property
    def stock_label(self) -> str:
        return dict(self.STOCK_STATES).get(self.stock_state, "")

    @property
    def stock_percent(self) -> int:
        target = max(self.par_level or 1, self.low_stock_threshold or 1, 1)
        return max(0, min(100, round(self.stock * 100 / target)))

    @property
    def needs_restock(self) -> int:
        """How many portions to reach par — the number the admin form pre-fills."""
        return max(0, (self.par_level or 0) - self.stock)

    @property
    def margin(self):
        if self.cost in (None, Decimal("0")):
            return None
        return (self.price - self.cost).quantize(Decimal("0.01"))

    @property
    def margin_pct(self):
        if not self.cost or not self.price:
            return None
        return round(float((self.price - self.cost) / self.price) * 100)

    @property
    def is_discounted(self) -> bool:
        return bool(self.compare_price and self.compare_price > self.price)

    @property
    def photo_url(self) -> str:
        return self.photo.file.url if self.photo_id and self.photo else ""

    @property
    def heat_label(self) -> str:
        return "🌶" * int(self.heat or 0)

    @property
    def diet_label(self) -> str:
        if self.is_vegan:
            return "Vegan"
        if self.is_veg:
            return "Vegetarian"
        return ""

    @property
    def turn_label(self) -> str:
        """Sold per day over the last fortnight — the smart reorder signal."""
        since = timezone.now() - timedelta(days=14)
        sold = self.stock_moves.filter(direction="OUT", created_at__gte=since).aggregate(
            total=models.Sum("quantity")
        )["total"] or 0
        return round(sold / 14, 1)

    @property
    def sell_through_pct(self) -> int:
        target = max(self.par_level or 1, 1)
        return min(100, round(self.turn_label * 14 * 100 / target))

    # ── stock + price movements (ledger-backed) ──────────────────────────
    @transaction.atomic
    def restock(self, quantity: int, *, actor=None, reason: str = "restock", note: str = "") -> "StockMovement":
        quantity = max(0, int(quantity or 0))
        if quantity == 0:
            return None
        Item.objects.filter(pk=self.pk).update(stock=models.F("stock") + quantity)
        self.refresh_from_db(fields=["stock"])
        return StockMovement.objects.create(
            item=self, direction="IN", quantity=quantity, balance_after=self.stock,
            reason=reason, actor=actor, note=note[:180],
        )

    @transaction.atomic
    def consume(self, quantity: int, *, actor=None, reason: str = "sale", reference: str = "") -> "StockMovement":
        quantity = max(0, int(quantity or 0))
        if quantity == 0:
            return None
        Item.objects.filter(pk=self.pk).update(stock=models.F("stock") - quantity)
        self.refresh_from_db(fields=["stock"])
        self.last_sold_at = timezone.now()
        self.sold_total = (self.sold_total or 0) + quantity
        self.save(update_fields=["last_sold_at", "sold_total", "updated_at"])
        return StockMovement.objects.create(
            item=self, direction="OUT", quantity=quantity, balance_after=self.stock,
            reason=reason, reference=reference, actor=actor,
        )

    @transaction.atomic
    def set_price(self, new_price: Decimal, *, actor=None, reason: str = "adjustment"):
        old = self.price
        new_price = Decimal(str(new_price)).quantize(Decimal("0.01"))
        if old == new_price:
            return None
        PriceChange.objects.create(item=self, old_price=old, new_price=new_price, reason=reason, actor=actor)
        self.price = new_price
        self.save(update_fields=["price", "updated_at"])
        return new_price

    @transaction.atomic
    def eighty_six(self, *, actor=None, reason: str = "kitchen"):
        self.is_available = False
        self.save(update_fields=["is_available", "updated_at"])
        StockMovement.objects.create(
            item=self, direction="ADJUST", quantity=0, balance_after=self.stock,
            reason="86", actor=actor, note=reason[:180],
        )

    # ── smart lookup ─────────────────────────────────────────────────────
    @classmethod
    def find_twins(cls, name: str, *, category: "Category" | None = None, limit: int = 4):
        """Exact normalised twin first, then fuzzy siblings by shared tokens."""
        key = normalize(name)
        if not key:
            return cls.objects.none(), {}
        exact = cls.objects.filter(match_key=key)
        if category:
            exact = exact.filter(category=category)
        scored: list[tuple[int, int]] = []
        wanted = set(key.split())
        rows = list(cls.objects.only("pk", "name", "match_key").prefetch_related(None))
        for row in rows:
            have = set((row.match_key or "").split())
            if not have or not wanted:
                continue
            overlap = len(wanted & have) / max(len(wanted | have), 1)
            if overlap >= 0.34:
                scored.append((int(overlap * 100), row.pk))
        scored.sort(key=lambda pair: (-pair[0], -pair[1]))
        return exact, dict(scored[:limit])


class PriceChange(TimeStampedModel):
    """Append-only price ledger — lets the form remember what a dish cost."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="price_history")
    old_price = models.DecimalField(max_digits=8, decimal_places=2)
    new_price = models.DecimalField(max_digits=8, decimal_places=2)
    reason = models.CharField(max_length=24, default="adjustment")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = "price change"
        verbose_name_plural = "price ledger"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["item", "-created_at"], name="idx_price_item_time")]

    def __str__(self) -> str:
        return f"{self.item_id}: {self.old_price} → {self.new_price}"

    @property
    def delta_pct(self) -> int:
        if not self.old_price:
            return 0
        return round(float((self.new_price - self.old_price) / self.old_price) * 100)


class StockMovement(TimeStampedModel):
    """Every portion in or out, with the balance it produced — the audit spine."""

    DIRECTIONS = [("IN", "In"), ("OUT", "Out"), ("ADJUST", "Adjust")]
    REASONS = [
        ("sale", "Sold"),
        ("restock", "Restock"),
        ("waste", "Waste / spoil"),
        ("comp", "Comped"),
        ("count", "Stock count"),
        ("86", "86'd"),
        ("seed", "Opening balance"),
    ]

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="stock_moves")
    direction = models.CharField(max_length=6, choices=DIRECTIONS, default="IN", db_index=True)
    quantity = models.PositiveIntegerField(default=0)
    balance_after = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=8, choices=REASONS, default="restock")
    reference = models.CharField(max_length=24, blank=True, help_text="Order number, invoice, delivery slip…")
    note = models.CharField(max_length=180, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = "stock movement"
        verbose_name_plural = "stock ledger"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["item", "-created_at"], name="idx_stock_item_time"),
            models.Index(fields=["direction", "reason"], name="idx_stock_dir_reason"),
        ]

    def __str__(self) -> str:
        return f"{self.get_direction_display()} {self.quantity} · {self.item_id} → {self.balance_after}"

    @property
    def signed_quantity(self) -> int:
        if self.direction == "OUT":
            return -self.quantity
        return self.quantity
