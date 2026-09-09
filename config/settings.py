"""
Restaurant Management System — Django settings.

Design notes
------------
* Configuration is environment driven (see ``config/env.py``) so the same
  settings module works for local dev, the preview sandbox and a real deploy.
* SQLite runs in WAL mode with foreign keys enforced — cheap, dependable and
  honest for a single-node restaurant install.
* Static/media are wired for the dev server; swap in WhiteNoise/S3 by editing
  ``STORAGES``/``DEFAULT_FILE_STORAGE`` when you deploy.
"""
from __future__ import annotations

from pathlib import Path

from . import env

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Core ─────────────────────────────────────────────────────────────────
SECRET_KEY = env.string("SECRET_KEY", "rms-dev-only-key-do-not-use-in-prod-0x9f3a21c7")
DEBUG = env.flag("DEBUG", True)
ALLOWED_HOSTS = env.items("ALLOWED_HOSTS", ["*"] if DEBUG else [])

# ── Applications ─────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.humanize",
    "django.contrib.staticfiles",
    # Local
    "apps.core",
    "apps.accounts",
    "apps.menu",
    "apps.orders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestTimingMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.branding",
            ],
            "builtins": [
                "django.templatetags.static",
                "apps.core.templatetags.rms_extras",
            ],
        },
    },
]

# ── Database ─────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env.path("DB_PATH", BASE_DIR / "db.sqlite3"),
        "ATOMIC_REQUESTS": False,
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "timeout": 5000,
            "init_command": (
                "PRAGMA journal_mode=WAL; "
                "PRAGMA foreign_keys=ON; "
                "PRAGMA synchronous=NORMAL;"
            )
            if not env.flag("TESTING", False)
            else "",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Auth ─────────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"

# ── Security (dev-friendly; tightened by env in production) ──────────────
CSRF_TRUSTED_ORIGINS = env.items(
    "CSRF_TRUSTED_ORIGINS",
    ["http://localhost:8000", "http://127.0.0.1:8000", "https://*.e2b.app"],
)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env.flag("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env.flag("CSRF_COOKIE_SECURE", not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_CROSS_ORIGIN_OPENER_POLICY = None

# ── I18n ─────────────────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = env.string("TIME_ZONE", "Asia/Dhaka")
USE_I18N = True
USE_TZ = True

# ── Static & media ───────────────────────────────────────────────────────
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

FILE_UPLOAD_PERMISSIONS = 0o644

# ── Caching / sessions ───────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "rms",
    }
}

# ── Email ────────────────────────────────────────────────────────────────
EMAIL_BACKEND = env.string("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = "Restaurant RMS <rms@restaurant.local>"

# ── Logging ──────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{asctime}] {levelname:<7} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": env.string("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "apps": {"handlers": ["console"], "level": "DEBUG" if DEBUG else "INFO", "propagate": False},
    },
}

# ── Restaurant domain knobs (defaults; overridden by the Restaurant row) ──
RMS = {
    "brand": env.string("RMS_BRAND", "Lumière"),
    "currency_code": "USD",
    "currency_symbol": "$",
    "tax_percent": 7.5,
    "service_percent": 10.0,
    "low_stock_default": 6,
    "prep_station_count": 4,
}

MESSAGE_TAGS = {
    40: "error",     # ERROR
    30: "warning",   # WARNING
    25: "notice",    # INFO
    20: "notice",    # SUCCESS
}
