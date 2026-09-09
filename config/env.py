"""Tiny environment helpers so settings.py stays declarative.

Names deliberately avoid shadowing builtins (``str``/``int``/``list``) inside
this module — that bug bites hard at import time.
"""
from __future__ import annotations

import os
from pathlib import Path


def string(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def number(name: str, default: int = 0) -> int:
    try:
        return int(str(os.environ.get(name) or default))
    except (TypeError, ValueError):
        return default


def items(name: str, default: tuple[str, ...] | list[str] | None = None) -> list[str]:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return list(default or [])
    return [piece.strip() for piece in value.split(",") if piece.strip()]


def path(name: str, default: Path | str) -> Path:
    return Path(os.environ.get(name) or str(default))
