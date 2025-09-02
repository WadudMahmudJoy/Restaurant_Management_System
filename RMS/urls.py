from django.urls import path
from . import views

urlpatterns = [
    path('', views.homepage, name='homepage'),
    path('admin-login/', views.admin_login, name='admin_login'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    # Future: path('user/', views.user_home, name='user_home'),
]
