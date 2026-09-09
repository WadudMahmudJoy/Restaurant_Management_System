"""
Menu admin — deliberately decorated: colour chips, live stock bars, photo
thumbnails, grouped fieldsets and read-only ledgers. This is the same schema the
studio UI writes to, so both views stay honest.
"""
from __future__ import annotations

from django.contrib import admin
from django.db.models import Count, Sum
from django.utils.html import format_html

from .models import Category, Item, Photo, PriceChange, StockMovement


def _dot(color: str, text: str) -> str:
    return format_html(
        '<span style="display:inline-flex;align-items:center;gap:7px">'
        '<i style="width:9px;height:9px;border-radius:50%;display:inline-block;'
        'background:{0};box-shadow:0 0 0 3px {0}22"></i>{1}</span>',
        color, text,
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("swatch", "name", "icon", "items_count", "available_count", "service_order", "is_active")
    list_editable = ("service_order", "is_active")
    search_fields = ("name", "blurb")
    ordering = ("service_order",)
    list_display_links = ("swatch",)

    @admin.display(description="Chapter", ordering="name")
    def swatch(self, obj):
        return _dot(obj.accent, f"{obj.icon}  {obj.name}")

    @admin.display(description="Dishes", ordering="items__id")
    def items_count(self, obj):
        return obj.items.count()

    @admin.display(description="On menu")
    def available_count(self, obj):
        return obj.items.filter(is_available=True).count()


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("thumb", "label", "reuse_count", "format", "weight", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("label", "notes", "tags")
    readonly_fields = ("checksum", "width", "height", "bytes", "created_at", "updated_at", "items_using")

    @admin.display(description="")
    def thumb(self, obj):
        return format_html(
            '<img src="{}" style="width:56px;height:40px;object-fit:cover;border-radius:6px;'
            'box-shadow:0 2px 10px rgba(0,0,0,.35)"/>',
            obj.file.url if obj.file else "",
        )

    @admin.display(description="Re-used by")
    def reuse_count(self, obj):
        n = obj.items.count()
        tone = "#4ecb8f" if n > 1 else ("#D8B26A" if n == 1 else "#8b8f98")
        return _dot(tone, f"{n} dish{'es' if n != 1 else ''}")

    @admin.display(description="Format")
    def format(self, obj):
        return f"{obj.width}×{obj.height}" if obj.width else "—"

    @admin.display(description="Size")
    def weight(self, obj):
        return f"{obj.kb} KB"

    @admin.display(description="Linked dishes")
    def items_using(self, obj):
        return format_html(
            "<ul style='margin:0;padding-left:18px'>{}</ul>",
            format_html("".join(f"<li>{item.name}</li>" for item in obj.items.all()[:40])),
        )


class PriceChangeInline(admin.TabularInline):
    model = PriceChange
    extra = 0
    can_delete = False
    fields = ("old_price", "new_price", "delta", "reason", "actor", "created_at")
    readonly_fields = fields

    @admin.display(description="Δ")
    def delta(self, obj):
        return f"{obj.delta_pct:+d}%"

    def has_add_permission(self, request, obj=None):
        return False


class StockMovementInline(admin.TabularInline):
    model = StockMovement
    extra = 0
    can_delete = False
    fields = ("direction", "quantity", "balance_after", "reason", "reference", "actor", "created_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("dish", "chapter", "price_cell", "stock_bar", "photo_cell", "state", "station", "updated_at")
    list_filter = ("category", "is_available", "station", "is_veg", "is_signature", "heat")
    search_fields = ("name", "subtitle", "description", "match_key")
    autocomplete_fields = ("category", "photo")
    date_hierarchy = "created_at"
    actions = ("mark_available", "eighty_six", "restock_to_par")
    inlines = (PriceChangeInline, StockMovementInline)
    list_select_related = ("category", "photo")

    fieldsets = (
        ("Identity", {"fields": ("name", "category", "subtitle", "description")}),
        ("Money", {"fields": ("price", "compare_price", "cost", "margin_readout"),
                   "description": "Changing the price writes to the price ledger automatically."}),
        ("Stock", {"fields": ("stock", "par_level", "low_stock_threshold", "unit", "stock_readout")}),
        ("Photo", {"fields": ("photo", "photo_source", "photo_note", "photo_readout"),
                   "description": "Leave the photo alone — twins inherit it the moment one is set."}),
        ("Kitchen", {"fields": ("station", "prep_minutes", "calories", "protein_g", "allergens")}),
        ("Character", {"fields": ("is_veg", "is_vegan", "heat", "is_signature", "is_seasonal",
                                  "is_available", "tags", "pairs_with")}),
        ("Meta", {"fields": ("match_key", "added_by", "published_at", "sold_total", "last_sold_at",
                             "created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("match_key", "published_at", "sold_total", "last_sold_at", "created_at", "updated_at",
                       "margin_readout", "stock_readout", "photo_readout")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("category", "photo")

    @admin.display(description="Dish", ordering="name")
    def dish(self, obj):
        flags = []
        if obj.is_signature:
            flags.append("⭐")
        if obj.is_vegan:
            flags.append("🌱")
        elif obj.is_veg:
            flags.append("🥬")
        if obj.heat:
            flags.append("🌶" * obj.heat)
        return format_html(
            '<div style="font-weight:600">{}</div><div style="color:#7b8090;font-size:11px">{}</div>',
            " ".join(flags + [obj.name]), obj.subtitle or "—",
        )

    @admin.display(description="Chapter", ordering="category__name")
    def chapter(self, obj):
        return _dot(obj.category.accent, obj.category.name)

    @admin.display(description="Price", ordering="price")
    def price_cell(self, obj):
        if obj.is_discounted:
            return format_html(
                '<b>{}</b> <s style="color:#8b8f98;font-weight:400">{}</s>',
                obj.price, obj.compare_price,
            )
        return format_html("<b>{}</b>", obj.price)

    @admin.display(description="Stock", ordering="stock")
    def stock_bar(self, obj):
        colors = {"out": "#ff6b6b", "low": "#f2b544", "steady": "#D8B26A", "ample": "#4ecb8f"}
        color = colors[obj.stock_state]
        return format_html(
            '<div style="min-width:110px"><div style="font:600 12px ui-monospace,monospace">{} {}</div>'
            '<div style="height:4px;background:#22252c;border-radius:99px;overflow:hidden;margin-top:3px">'
            '<i style="display:block;height:100%;width:{}%;background:{};border-radius:99px"></i></div></div>',
            obj.stock, obj.unit, obj.stock_percent, color,
        )

    @admin.display(description="Photo")
    def photo_cell(self, obj):
        if not obj.photo_id:
            return _dot("#8b8f98", "none yet")
        mark = {"inherited": "inherited", "library": "library", "upload": "uploaded", "none": ""}[obj.photo_source]
        return format_html(
            '<img src="{}" style="width:44px;height:32px;object-fit:cover;border-radius:5px" title="{}"/>',
            obj.photo.file.url, mark,
        )

    @admin.display(description="State")
    def state(self, obj):
        tones = {"out": "#ff6b6b", "low": "#f2b544", "steady": "#D8B26A", "ample": "#4ecb8f"}
        return _dot(tones[obj.stock_state], obj.stock_label)

    @admin.display(description="Margin")
    def margin_readout(self, obj):
        if obj.margin is None:
            return "Add a cost to see margin."
        return f"{obj.margin} ({obj.margin_pct}%)"

    @admin.display(description="Stock readout")
    def stock_readout(self, obj):
        return format_html(
            "<span>{}</span> · par {} · {} turns/day · reorder at {}",
            obj.stock_label, obj.par_level, obj.turn_label, obj.low_stock_threshold,
        )

    @admin.display(description="Photo readout")
    def photo_readout(self, obj):
        if not obj.photo_id:
            return "No photo yet — add one and every twin dish inherits it."
        shared = obj.photo.items.exclude(pk=obj.pk).count()
        return f"{obj.photo.label} · re-used by {shared} other dish{'es' if shared != 1 else ''}"

    @admin.action(description="Put on the menu")
    def mark_available(self, request, queryset):
        updated = queryset.update(is_available=True)
        self.message_user(request, f"{updated} dish{'es' if updated != 1 else ''} are live again.")

    @admin.action(description="86 (hide from guests)")
    def eighty_six(self, request, queryset):
        updated = queryset.update(is_available=False)
        self.message_user(request, f"86'd {updated} dish{'es' if updated != 1 else ''}.")

    @admin.action(description="Restock to par level")
    def restock_to_par(self, request, queryset):
        moved = 0
        for item in queryset:
            needed = item.needs_restock
            if needed:
                item.restock(needed, actor=request.user, reason="count", note="admin bulk action")
                moved += 1
        self.message_user(request, f"Topped {moved} dish{'es' if moved != 1 else ''} back to par.")
