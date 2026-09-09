from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("vault/", views.vault, name="vault"),
    path("api/overview/", views.api_dashboard, name="api_dashboard"),
    path("api/vault/", views.api_vault_schema, name="api_vault"),
    path("api/health/", views.api_health, name="api_health"),
]
