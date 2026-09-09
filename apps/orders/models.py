"""
Service models.

orders_table          the floor plan (with x/y so the dashboard can render it in 3D)
orders_order          a ticket: guest, channel, money, lifecycle
orders_orderline      one dish on that ticket, priced at the moment it was fired
orders_payment        money received (supports split payments + tips)
orders_guestnote      flavour feedback, rating and allergen callouts

Money is *snapshotted* on the line, so editing a price never rewrites history.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.menu.models import Item
from apps.accounts.models import StaffProfile

CENT = Decimal("0.01")
ZERO = Decimal("0")


class TableQuerySet(models.QuerySet):
    def occupied(self):
        return self.filter(status="occupied")

    def free(self):
        return self.filter(status="free")


class Table(TimeStampedModel):
    ZONES = [("main", "Main room"), ("terrace", "Terrace"), ("bar", "Bar"), ("private", "Private")]
    STATES = [("free", "Free"), ("seated", "Seated"), ("ordered", "Ordered"), ("running", "Running"),
              ("dessert", "Dessert"), ("settling", "Settling"), ("clearing", "Clearing")]

    label = models.CharField(max_length=12, unique=True, help_text="T-01")
    seats = models.PositiveSmallIntegerField(default=2)
    zone = models.CharField(max_length=8, choices=ZONES, default="main")
    status = models.CharField(max_length=9, choices=STATES, default="free", db_index=True)
    x = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO, help_text="Floor coordinate (metres).")
    y = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)
    rotation = models.PositiveSmallIntegerField(default=0, help_text="Degrees, used by the 3D floor.")
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=120, blank=True)

    objects = TableQuerySet.as_manager()

    class Meta:
        verbose_name = "table"
        verbose_name_plural = "floor plan"
        ordering = ["zone", "label"]
        constraints = [models.CheckConstraint(condition=models.Q(seats__gte=1), name="table_has_seats")]
        indexes = [models.Index(fields=["zone", "status"], name="idx_table_zone_state")]

    def __str__(self) -> str:
        return f"{self.label} · {self.get_status_display()}"

    @property
    def live_order(self):
        return self.orders.exclude(status__in=Order.CLOSED_STATES).order_by("-created_at").first()

    @property
    def tone(self) -> str:
        return {"free": "idle", "seated": "info", "ordered": "warn", "running": "hot",
                "dessert": "info", "settling": "warn", "clearing": "bad"}[self.status]


class OrderQuerySet(models.QuerySet):
    def open(self):
        return self.exclude(status__in=Order.CLOSED_STATES)

    def for_day(self, day):
        start = timezone.localtime(day).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.filter(created_at__gte=start, created_at__lt=start + timedelta(days=1))

    def with_totals(self):
        return self.prefetch_related("lines__item").select_related("table", "guest_user")


class Order(TimeStampedModel):
    """A live ticket."""

    NEW, FIRE, READY, SERVED, PAID, CANCELLED = "new", "fire", "ready", "served", "paid", "cancelled"
    STATUSES = [
        (NEW, "Order in"),
        (FIRE, "Firing"),
        (READY, "Ready"),
        (SERVED, "Served"),
        (PAID, "Paid"),
        (CANCELLED, "Cancelled"),
    ]
    CLOSED_STATES = {PAID, CANCELLED}
    CHANNELS = [("dinein", "Dine-in"), ("takeaway", "Takeaway"), ("delivery", "Delivery"),
                ("pickup", "Pickup"), ("web", "Web order")]
    PRIORITIES = [("normal", "Normal"), ("rush", "Rush"), ("vip", "VIP")]

    number = models.CharField(max_length=16, unique=True, blank=True, editable=False, db_index=True)
    status = models.CharField(max_length=9, choices=STATUSES, default=NEW, db_index=True)
    channel = models.CharField(max_length=9, choices=CHANNELS, default="dinein", db_index=True)
    priority = models.CharField(max_length=6, choices=PRIORITIES, default="normal")

    table = models.ForeignKey(Table, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    guest_name = models.CharField(max_length=80, blank=True, default="Guest")
    guest_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="orders")
    party_size = models.PositiveSmallIntegerField(default=2)
    waiter = models.ForeignKey(StaffProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    chef = models.ForeignKey(StaffProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO, editable=False)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    tax_total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO, editable=False)
    service_total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO, editable=False)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO, editable=False)

    note = models.CharField(max_length=220, blank=True)
    fired_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    served_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    objects = OrderQuerySet.as_manager()

    class Meta:
        verbose_name = "ticket"
        verbose_name_plural = "tickets"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="idx_order_status_time"),
            models.Index(fields=["channel", "status"], name="idx_order_channel_state"),
        ]

    def __str__(self) -> str:
        return f"{self.number} · {self.guest_name}"

    def save(self, *args, **kwargs):
        new = self.pk is None
        super().save(*args, **kwargs)
        if new and not self.number:
            self.number = f"LM-{self.pk:04d}"
            super().save(update_fields=["number"])

    # ── money ────────────────────────────────────────────────────────────
    def recompute(self, *, save: bool = True) -> Decimal:
        from apps.core.models import Restaurant

        venue = Restaurant.load()
        subtotal = sum((line.line_total for line in self.lines.all()), ZERO).quantize(CENT)
        self.subtotal = subtotal
        self.service_total = (subtotal * venue.service_percent / 100).quantize(CENT)
        taxable = max(ZERO, subtotal - self.discount)
        self.tax_total = (taxable * venue.tax_percent / 100).quantize(CENT)
        self.total = (taxable + self.service_total + self.tax_total).quantize(CENT)
        if save:
            self.save(update_fields=["subtotal", "service_total", "tax_total", "total", "updated_at"])
        return self.total

    @property
    def item_count(self) -> int:
        return sum(line.quantity for line in self.lines.all())

    @property
    def average_ticket_seconds(self) -> int:  # kept for analytics parity
        return self.age_seconds

    @property
    def age_seconds(self) -> int:
        end = self.closed_at or timezone.now()
        return max(0, int((end - self.created_at).total_seconds()))

    @property
    def age_label(self) -> str:
        secs = self.age_seconds
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m"
        return f"{mins // 60}h {mins % 60:02d}m"

    @property
    def is_late(self) -> bool:
        if self.status in self.CLOSED_STATES or self.status == self.SERVED:
            return False
        from apps.core.models import Restaurant

        return self.age_seconds > max(60, Restaurant.load().kitchen_lane_minutes * 60)

    @property
    def tone(self) -> str:
        return {self.NEW: "info", self.FIRE: "hot", self.READY: "good",
                self.SERVED: "idle", self.PAID: "good", self.CANCELLED: "bad"}[self.status]

    @property
    def progress_pct(self) -> int:
        return {self.NEW: 15, self.FIRE: 45, self.READY: 72,
                self.SERVED: 88, self.PAID: 100, self.CANCELLED: 100}[self.status]

    # ── lifecycle ────────────────────────────────────────────────────────
    @transaction.atomic
    def advance(self, *, actor=None) -> str:
        """Move one step along the service rail, with side effects in the right order."""
        now = timezone.now()
        if self.status == self.NEW:
            self.status = self.FIRE
            self.fired_at = now
            self.lines.update(state="cooking", fired_at=now)
            if self.table_id:
                self.table.status = "running"
                self.table.save(update_fields=["status", "updated_at"])
        elif self.status == self.FIRE:
            self.status = self.READY
            self.ready_at = now
            self.lines.update(state="ready", ready_at=now)
            if self.table_id:
                self.table.status = "dessert"
                self.table.save(update_fields=["status", "updated_at"])
        elif self.status == self.READY:
            self.status = self.SERVED
            self.served_at = now
            self.lines.update(state="served")
            if self.table_id:
                self.table.status = "settling"
                self.table.save(update_fields=["status", "updated_at"])
        elif self.status == self.SERVED:
            return self.settle(actor=actor)
        self.save()
        return self.status

    @transaction.atomic
    def settle(self, *, method: str = "card", actor=None, tip: Decimal = ZERO) -> str:
        """Close the ticket: take payment, drain stock through the ledger, free the table."""
        if self.status == self.PAID:
            return self.status
        self.recompute(save=False)
        self.status = self.PAID
        self.paid_at = self.closed_at = timezone.now()
        self.save(update_fields=["status", "paid_at", "closed_at", "subtotal", "tax_total",
                                 "service_total", "total", "updated_at"])
        # Payment is credited to a StaffProfile; callers may hand us the User.
        payer = actor if isinstance(actor, StaffProfile) else getattr(actor, "profile", None)
        Payment.objects.create(order=self, method=method, amount=self.total, tip=tip, received_by=payer)
        for line in self.lines.select_related("item"):
            if line.item_id:
                line.item.consume(line.quantity, actor=actor, reason="sale", reference=self.number)
        if self.table_id:
            self.table.status = "clearing"
            self.table.save(update_fields=["status", "updated_at"])
        return self.status

    @transaction.atomic
    def cancel(self, *, actor=None, reason: str = "") -> str:
        self.status = self.CANCELLED
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at", "updated_at"])
        self.lines.update(state="cancelled")
        if self.table_id and not self.table.orders.exclude(status=self.CANCELLED).exists():
            self.table.status = "clearing"
            self.table.save(update_fields=["status", "updated_at"])
        return self.status

    @transaction.atomic
    def add_item(self, item: Item, quantity: int = 1, *, notes: str = "", course: int = 1):
        line = OrderLine.objects.create(
            order=self, item=item, name_at_order=item.name, quantity=max(1, int(quantity)),
            unit_price=item.price, notes=notes[:180], course=course,
        )
        self.recompute()
        return line


class OrderLine(TimeStampedModel):
    STATES = [("queued", "Queued"), ("cooking", "Cooking"), ("ready", "Ready"),
              ("served", "Served"), ("cancelled", "Cancelled")]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.SET_NULL, related_name="order_lines")
    name_at_order = models.CharField(max_length=90)
    quantity = models.PositiveSmallIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    state = models.CharField(max_length=9, choices=STATES, default="queued", db_index=True)
    course = models.PositiveSmallIntegerField(default=1, help_text="1 starter · 2 main · 3 sweet")
    notes = models.CharField(max_length=180, blank=True)
    is_comp = models.BooleanField(default=False)
    fired_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "ticket line"
        verbose_name_plural = "ticket lines"
        ordering = ["course", "position", "id"]

    def __str__(self) -> str:
        return f"{self.quantity}× {self.name_at_order}"

    @property
    def line_total(self) -> Decimal:
        if self.is_comp:
            return ZERO
        return (self.unit_price * self.quantity).quantize(CENT)

    @property
    def tone(self) -> str:
        return {"queued": "idle", "cooking": "hot", "ready": "good", "served": "info", "cancelled": "bad"}[self.state]


class Payment(TimeStampedModel):
    METHODS = [("card", "Card"), ("cash", "Cash"), ("qr", "QR / wallet"), ("comp", "Comp"), ("split", "Split")]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=5, choices=METHODS, default="card")
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    tip = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    reference = models.CharField(max_length=40, blank=True)
    received_by = models.ForeignKey(StaffProfile, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="payments")

    class Meta:
        verbose_name = "payment"
        verbose_name_plural = "payments"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_method_display()} {self.amount} · {self.order_id}"

    @property
    def grand(self) -> Decimal:
        return (self.amount + self.tip).quantize(CENT)


class GuestNote(TimeStampedModel):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="feedback")
    rating = models.PositiveSmallIntegerField(default=5)
    message = models.TextField(blank=True, max_length=400)
    flags = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "guest note"
        verbose_name_plural = "guest notes"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{'★' * self.rating} on {self.order.number}"
