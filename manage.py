#!/usr/bin/env python
"""Django command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - helpful error only
        raise ImportError(
            "Couldn't import Django. Is it installed and on your PYTHONPATH? "
            "Try:  python -m venv .venv && .venv/bin/pip install -r requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
