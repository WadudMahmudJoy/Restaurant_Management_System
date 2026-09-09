"""Template filters/tags for the RMS UI."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def money(value, symbol="$") -> str:
    """{{ order.total|money:'$' }} → $128.40 with a thin space thousands sep."""
    try:
        amount = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError):
        return str(value)
    sign = "−" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,.2f}"


@register.filter
def signed(value) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    return f"+{amount:g}" if amount > 0 else f"{amount:g}"


@register.filter
def initials(value: str) -> str:
    parts = [p for p in str(value or "").replace("_", " ").split() if p]
    if not parts:
        return "··"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


@register.filter
def json_script(value) -> str:
    """Serialize a context value into an inline <script type="application/json"> body.

    Views may hand us a plain object or an already-encoded string; both end up as
    valid, safely-escaped JSON text.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    return mark_safe(json.dumps(value, default=str).replace("</", "<\\/"))


@register.simple_tag(takes_context=True)
def nav_active(context, *names) -> str:
    current = context.request.path
    for name in names:
        if name != "/" and current.startswith(name):
            return "is-active"
        if name == "/" and current == "/":
            return "is-active"
    return ""


@register.filter
def stock_tone(state: str) -> str:
    return {"out": "bad", "low": "warn", "steady": "info", "ample": "good"}.get(state, "idle")


@register.simple_tag
def ring(percent, radius=30, stroke=5) -> str:
    """Small SVG progress ring used by KPI chips."""
    percent = max(0.0, min(100.0, float(percent or 0)))
    circ = 2 * 3.14159 * radius
    dash = circ * percent / 100
    return format_html(
        '<svg class="ring" viewBox="0 0 70 70" aria-hidden="true">'
        '<circle cx="35" cy="35" r="{r}" class="ring__track" stroke-width="{s}"/>'
        '<circle cx="35" cy="35" r="{r}" class="ring__value" stroke-width="{s}" '
        'stroke-dasharray="{d:.2f} {c:.2f}" transform="rotate(-90 35 35)"/></svg>',
        r=radius, s=stroke, d=dash, c=circ,
    )
