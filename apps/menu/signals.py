"""Menu signals: the automation that makes the admin form feel smart."""
from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from apps.core.models import ActivityLog

from .models import Item, Photo

log = logging.getLogger("apps.menu")


@receiver(post_save, sender=Item, dispatch_uid="menu.share_photo_with_twins")
def share_photo_with_twins(sender, instance: Item, created: bool, **kwargs):
    """
    One photo, every twin.

    If a dish is saved *with* a photo, any other dish carrying the same
    normalised name (same dish, new chapter, seasonal relaunch…) that has no
    photo yet inherits it instantly — no second upload, ever.
    """
    if not instance.photo_id or not instance.match_key:
        return
    twins = list(Item.objects.filter(match_key=instance.match_key, photo__isnull=True).exclude(pk=instance.pk))
    for twin in twins:
        twin.photo = instance.photo
        twin.photo_source = "inherited"
        twin.photo_note = f"Auto-shared from “{instance.name}”"
        twin.save(update_fields=["photo", "photo_source", "photo_note", "updated_at"])
    if twins and not created:
        ActivityLog.record(
            f"Reused the “{instance.name}” photo for {len(twins)} twin dish"
            f"{'es' if len(twins) > 1 else ''}",
            verb="imaged",
            obj=instance,
            level="good",
            table="menu_item",
            meta={"twins": [t.name for t in twins]},
        )


@receiver(post_save, sender=Item, dispatch_uid="menu.touch_photo_source")
def keep_publish_date(sender, instance: Item, created: bool, **kwargs):
    if created:
        ActivityLog.record(
            f"Added “{instance.name}” to {instance.category.name}",
            verb="created",
            obj=instance,
            actor=instance.added_by_id,
            level="good",
            table="menu_item",
        )


@receiver(pre_delete, sender=Photo, dispatch_uid="menu.detach_photo")
def clear_photo_pointer(sender, instance: Photo, **kwargs):
    """Items survive a deleted photo; they just go back to ‘no image yet’."""
    Item.objects.filter(photo=instance).update(photo=None, photo_source="none", photo_note="")
