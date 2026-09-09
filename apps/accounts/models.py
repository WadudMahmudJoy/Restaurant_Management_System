"""
accounts_staffprofile — one row per human on the floor.

Django's stock ``User`` keeps authentication; this table keeps everything a
restaurant actually cares about: role, duty status, station, service pin and a
personal accent colour that decorates the dashboard's live tiles.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimeStampedModel


class StaffProfile(TimeStampedModel):
    ROLES = [
        ("owner", "Owner"),
        ("manager", "Manager"),
        ("chef", "Chef"),
        ("sous", "Sous chef"),
        ("waiter", "Server"),
        ("cashier", "Cashier"),
        ("barista", "Barista"),
    ]
    PERMISSIONS = [
        ("menu.write", "Edit the menu"),
        ("stock.write", "Move stock"),
        ("orders.write", "Run orders"),
        ("prices.write", "Change prices"),
        ("vault.read", "Open the data vault"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=80)
    handle = models.SlugField(max_length=40, unique=True, blank=True)
    role = models.CharField(max_length=8, choices=ROLES, default="waiter", db_index=True)
    permissions = models.JSONField(default=list, blank=True)
    phone = models.CharField(max_length=24, blank=True)
    pin = models.CharField(max_length=6, blank=True, help_text="4–6 digit floor/kiosk code.")
    accent = models.CharField(max_length=9, default="#D8B26A")
    is_on_duty = models.BooleanField(default=False)
    clocked_in_at = models.DateTimeField(null=True, blank=True)
    station = models.CharField(max_length=24, blank=True)
    tables_owned = models.PositiveSmallIntegerField(default=0)
    notes = models.CharField(max_length=180, blank=True)

    class Meta:
        verbose_name = "team member"
        verbose_name_plural = "team"
        ordering = ["role", "display_name"]
        indexes = [models.Index(fields=["role", "is_on_duty"], name="idx_staff_role_duty")]

    def __str__(self) -> str:
        return f"{self.display_name} · {self.get_role_display()}"

    def save(self, *args, **kwargs):
        if not self.display_name:
            u = self.user
            self.display_name = (u.get_full_name() or u.get_username()).title()
        if not self.handle:
            self.handle = slugify(self.display_name).replace("-", ".")[:40] or f"user-{self.pk or self.user_id}"
        super().save(*args, **kwargs)

    # ── helpers ──────────────────────────────────────────────────────────
    @property
    def initials(self) -> str:
        """Avatar letters. One word → first two letters, so avatars stay square-ish."""
        parts = [p for p in self.display_name.split() if p]
        if not parts:
            return "··"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    @property
    def can_manage_menu(self) -> bool:
        return self.role in {"owner", "manager"} or "menu.write" in (self.permissions or [])

    @property
    def duty_label(self) -> str:
        return "On floor" if self.is_on_duty else "Off duty"

    @classmethod
    def on_duty(cls):
        return cls.objects.filter(is_on_duty=True)
