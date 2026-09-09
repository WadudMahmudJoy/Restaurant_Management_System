"""
Core platform models.

``TimeStampedModel`` is the shared audit spine every table mixes in.
``Restaurant`` is a gracefully-declared singleton holding live venue config so
the UI never hard-codes currency, tax or brand colours.
``ActivityLog`` is an append-only ledger powering the dashboard feed.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Every table gets created/updated bookkeeping and a sortable key."""

    created_at = models.DateTimeField("created", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("updated", auto_now=True)

    class Meta:
        abstract = True
        get_latest_by = "created_at"


class Restaurant(TimeStampedModel):
    """Singleton venue record: brand, money, service rules, opening hours."""

    SERVICE_STYLES = [
        ("table", "Table service"),
        ("counter", "Counter / bar"),
        ("mixed", "Mixed floor"),
    ]

    name = models.CharField(max_length=90, default="Lumière")
    tagline = models.CharField(max_length=160, blank=True, default="Fire, salt & patience.")
    accent = models.CharField(max_length=9, default="#D8B26A", help_text="Brand gold as hex.")
    accent_soft = models.CharField(max_length=9, default="#F0DCB0")
    currency_symbol = models.CharField(max_length=4, default="$")
    currency_code = models.CharField(max_length=3, default="USD")
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("7.50"))
    service_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10.00"))
    service_style = models.CharField(max_length=12, choices=SERVICE_STYLES, default="mixed")
    address = models.CharField(max_length=200, blank=True, default="14 Harbor Lane, Riverside District")
    phone = models.CharField(max_length=32, blank=True, default="+1 202 555 0142")
    email = models.EmailField(blank=True, default="hello@lumiere.dining")
    opens_at = models.TimeField(default=timezone.datetime.strptime("11:30", "%H:%M").time())
    closes_at = models.TimeField(default=timezone.datetime.strptime("23:30", "%H:%M").time())
    days_open = models.JSONField(default=list, blank=True, help_text="0=Mon … 6=Sun")
    kitchen_lane_minutes = models.PositiveSmallIntegerField(default=16)
    low_stock_default = models.PositiveSmallIntegerField(default=6)
    receipt_footer = models.CharField(max_length=160, blank=True, default="Thank you — see you tomorrow.")
    is_open_override = models.BooleanField("force open", default=False)

    class Meta:
        verbose_name = "Restaurant"
        verbose_name_plural = "Restaurant profile"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name

    # ── singleton accessors ────────────────────────────────────────────
    @classmethod
    def load(cls) -> "Restaurant":
        """Fetch (or lazily create) the one venue row, cached for the request."""
        key = "rms:restaurant"
        row = cache.get(key)
        if row is None:
            row, _ = cls.objects.get_or_create(pk=1)
            cache.set(key, row, 300)
        return row

    def save(self, *args, **kwargs):
        self.pk = self.pk or 1
        super().save(*args, **kwargs)
        cache.delete("rms:restaurant")

    # ── derived ────────────────────────────────────────────────────────
    @property
    def is_open_now(self) -> bool:
        if self.is_open_override:
            return True
        now = timezone.localtime()
        if self.days_open and now.weekday() not in self.days_open:
            return False
        return self.opens_at <= now.time() <= self.closes_at

    @property
    def hours_label(self) -> str:
        fmt = "%-I:%M %p"
        try:
            return f"{self.opens_at.strftime(fmt).lstrip('0')} – {self.closes_at.strftime(fmt).lstrip('0')}"
        except ValueError:  # pragma: no cover
            return f"{self.opens_at} – {self.closes_at}"

    def money(self, amount) -> str:
        amount = Decimal(str(amount or 0))
        sign = "−" if amount < 0 else ""
        return f"{sign}{self.currency_symbol}{abs(amount):,.2f}"


class ActivityLog(models.Model):
    """Append-only journal of everything the system did for a human."""

    VERBS = [
        ("created", "created"),
        ("updated", "updated"),
        ("deleted", "deleted"),
        ("restocked", "restocked"),
        ("priced", "repriced"),
        ("served", "served"),
        ("paid", "paid"),
        ("cancelled", "cancelled"),
        ("eighty-sixed", "86'd"),
        ("imaged", "photographed"),
        ("signed-in", "signed in"),
    ]
    LEVELS = [("info", "info"), ("good", "good"), ("warn", "warn"), ("bad", "bad")]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="activities"
    )
    verb = models.CharField(max_length=14, choices=VERBS, default="updated", db_index=True)
    table = models.CharField(max_length=40, blank=True, db_index=True, help_text="Logical table, e.g. menu_item")
    object_id = models.CharField(max_length=24, blank=True)
    message = models.CharField(max_length=220)
    link = models.CharField(max_length=200, blank=True)
    level = models.CharField(max_length=5, choices=LEVELS, default="info")
    meta = models.JSONField(default=dict, blank=True)
    moment = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "activity entry"
        verbose_name_plural = "activity ledger"
        ordering = ["-moment"]
        indexes = [models.Index(fields=["table", "object_id"], name="idx_activity_target")]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.actor or 'system'} {self.verb} · {self.message}"

    @classmethod
    def record(cls, message, *, verb="updated", actor=None, obj=None, level="info", link="", table="", meta=None):
        """Best-effort journal write — never breaks the request it decorates."""
        try:
            if isinstance(actor, int) or (isinstance(actor, str) and actor.isdigit()):
                actor_row: object | None = User.objects.filter(pk=actor).first()
            else:
                actor_row = actor if isinstance(actor, User) else getattr(actor, "user", None) or actor
            return cls.objects.create(
                actor=actor_row if isinstance(actor_row, User) else None,
                verb=verb,
                table=table or (obj._meta.label_lower if obj is not None else ""),
                object_id=str(getattr(obj, "pk", "") or ""),
                message=message[:220],
                link=link,
                level=level,
                meta=meta or {},
            )
        except Exception:  # pragma: no cover - defensive
            return None
