"""Keep a StaffProfile in lockstep with every User row."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import StaffProfile

ROLE_TO_PERMS = {
    "owner": ["menu.write", "stock.write", "orders.write", "prices.write", "vault.read"],
    "manager": ["menu.write", "stock.write", "orders.write", "prices.write", "vault.read"],
    "chef": ["orders.write"],
    "sous": ["orders.write", "stock.write"],
    "waiter": ["orders.write"],
    "cashier": ["orders.write"],
    "barista": ["orders.write"],
}


@receiver(post_save, sender=User, dispatch_uid="accounts.ensure_profile")
def ensure_profile(sender, instance: User, created: bool, **kwargs):
    profile, made = StaffProfile.objects.get_or_create(
        user=instance,
        defaults={
            "display_name": (instance.get_full_name() or instance.username).title(),
            "role": "manager" if (instance.is_superuser or instance.is_staff) else "waiter",
        },
    )
    if made or not profile.permissions:
        role = profile.role
        profile.permissions = ROLE_TO_PERMS.get(role, ["orders.write"])
        profile.save(update_fields=["permissions", "updated_at"])

