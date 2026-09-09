from django.contrib import admin

from .models import StaffProfile


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("badge", "role", "station", "is_on_duty", "tables_owned", "phone", "created_at")
    list_filter = ("role", "is_on_duty", "station")
    search_fields = ("display_name", "user__username", "handle")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)

    @admin.display(description="Team member")
    def badge(self, obj):
        return f"{obj.initials}  {obj.display_name}"

    def get_fieldsets(self, request, obj=None):
        return (
            (None, {"fields": ("user", "display_name", "handle", "role", "accent")}),
            ("Floor", {"fields": ("station", "is_on_duty", "clocked_in_at", "tables_owned", "pin")}),
            ("Access", {"fields": ("permissions",), "description": "Leave empty to use role defaults."}),
            ("Notes", {"fields": ("phone", "notes", "created_at", "updated_at"), "classes": ("collapse",)}),
        )
