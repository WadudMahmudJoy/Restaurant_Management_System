"""Decorated admin for the service loop — colour-coded states and live money."""
from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html

from .models import GuestNote, Order, OrderLine, Payment, Table


def _chip(color: str, text: str) -> str:
    return format_html(
        '<span style="display:inline-flex;align-items:center;gap:6px">'
        '<i style="width:8px;height:8px;border-radius:50%;background:{0};'
        'box-shadow:0 0 0 3px {0}22;display:inline-block"></i>{1}</span>',
        color, text,
    )


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("method", "amount", "tip", "reference", "received_by", "created_at")
    readonly_fields = ("created_at",)

    def has_add_permission(self, request, obj=None):
        return False


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0
    fields = ("quantity", "item", "name_at_order", "unit_price", "line_total", "course", "state", "notes")
    readonly_fields = ("line_total",)
    autocomplete_fields = ("item",)
    ordering = ("course", "position")

    @admin.display(description="Line total")
    def line_total(self, obj):
        return obj.line_total


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "state", "guest", "channel", "table", "items", "money", "age", "created_at")
    list_filter = ("status", "channel", "priority", "table__zone")
    search_fields = ("number", "guest_name", "note")
    date_hierarchy = "created_at"
    inlines = (OrderLineInline, PaymentInline)
    autocomplete_fields = ("table",)
    readonly_fields = ("number", "subtotal", "tax_total", "service_total", "age_label", "created_at", "updated_at")
    actions = ("settle_selected",)

    @admin.display(description="Ticket", ordering="guest_name")
    def guest(self, obj):
        return format_html(
            '<div style="font-weight:600">{}</div>'
            '<div style="color:#7b8090;font-size:11px">{} covers · table {}</div>',
            obj.guest_name, obj.party_size, obj.table.label if obj.table_id else "—",
        )

    @admin.display(description="State", ordering="status")
    def state(self, obj):
        tones = {"new": "#7aa2ff", "fire": "#ff9f45", "ready": "#4ecb8f", "served": "#D8B26A",
                 "paid": "#4ecb8f", "cancelled": "#ff6b6b"}
        return _chip(tones[obj.status], obj.get_status_display())

    @admin.display(description="Money", ordering="total")
    def money(self, obj):
        return format_html("<b>{}</b>", obj.total)

    @admin.display(description="In", ordering="created_at")
    def age(self, obj):
        tone = "#ff6b6b" if obj.is_late else "#9aa0ad"
        return format_html('<span style="color:{};font:600 12px ui-monospace,monospace">{}</span>', tone, obj.age_label)

    @admin.display(description="Dishes")
    def items(self, obj):
        return obj.item_count

    @admin.action(description="Settle (take payment, drain stock)")
    def settle_selected(self, request, queryset):
        count = 0
        for order in queryset:
            while order.status not in (Order.SERVED, Order.PAID):
                order.advance(actor=request.user)
            order.settle(actor=request.user)
            count += 1
        self.message_user(request, f"{count} ticket{'s' if count != 1 else ''} settled.")


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("label", "zone", "seats", "state", "position", "live", "is_active")
    list_filter = ("zone", "status", "is_active")
    list_editable = ("is_active",)
    search_fields = ("label", "note")

    @admin.display(description="State", ordering="status")
    def state(self, obj):
        tones = {"free": "#4ecb8f", "seated": "#7aa2ff", "ordered": "#ff9f45", "running": "#ff6b6b",
                 "dessert": "#D8B26A", "settling": "#D8B26A", "clearing": "#9aa0ad"}
        return _chip(tones[obj.status], obj.get_status_display())

    @admin.display(description="On the floor")
    def position(self, obj):
        return f"x {obj.x} · y {obj.y} · {obj.rotation}°"

    @admin.display(description="Ticket")
    def live(self, obj):
        order = obj.live_order
        return order.number if order else "—"


@admin.register(GuestNote)
class GuestNoteAdmin(admin.ModelAdmin):
    list_display = ("order", "stars", "message", "created_at")
    search_fields = ("message", "order__number")

    @admin.display(description="Rating")
    def stars(self, obj):
        return _chip("#D8B26A", "★" * obj.rating + "☆" * (5 - obj.rating))


@admin.register(OrderLine)
class OrderLineAdmin(admin.ModelAdmin):
    list_display = ("name_at_order", "quantity", "unit_price", "line_total", "state", "order")
    list_filter = ("state", "course")
    search_fields = ("name_at_order", "order__number")

    @admin.display(description="Total", ordering="unit_price")
    def line_total(self, obj):
        return obj.line_total


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order", "method", "amount", "tip", "grand", "received_by", "created_at")
    list_filter = ("method",)
    search_fields = ("order__number", "reference")

    @admin.display(description="With tip")
    def grand(self, obj):
        return obj.grand
