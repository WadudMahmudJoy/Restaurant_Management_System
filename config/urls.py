"""URL configuration for the Restaurant Management System."""
from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core import branding

admin.site.site_header = f"{branding.ADMIN_HEADER} · Data Vault"
admin.site.site_title = "RMS Control"
admin.site.index_title = "Tables, rows and relationships"

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("", include("apps.menu.urls")),
    path("", include("apps.orders.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
