"""Admin branding + a tidy, grouped index page for the data vault."""
from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ActivityLog, Restaurant


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("name", "currency_code", "tax_percent", "service_percent", "hours_label", "is_open_override")
    fieldsets = (
        (None, {"fields": ("name", "tagline", "address", "phone", "email")}),
        ("Brand", {"fields": ("accent", "accent_soft"), "description": "Drives every accent in the UI."}),
        ("Money", {"fields": ("currency_symbol", "currency_code", "tax_percent", "service_percent")}),
        ("Service", {
            "fields": ("service_style", "opens_at", "closes_at", "days_open", "is_open_override"),
            "description": "Hours drive the “open now” light across the app.",
        }),
        ("Operations", {"fields": ("kitchen_lane_minutes", "low_stock_default", "receipt_footer")}),
    )


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("moment", "actor", "verb", "message", "table", "level")
    list_filter = ("verb", "level", "table")
    search_fields = ("message", "actor__username")
    date_hierarchy = "moment"
    readonly_fields = tuple(f.name for f in ActivityLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
