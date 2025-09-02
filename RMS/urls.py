from django.urls import path
from . import views

urlpatterns = [
    path('', views.homepage, name='homepage'),
    path('super-admin/login/', views.super_admin_login, name='super_admin_login'),
    path('rms-admin/login/', views.admin_login, name='admin_login'),
    path('rms-admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('super-admin/dashboard/', views.super_admin_dashboard, name='super_admin_dashboard'),
    path('user/', views.user_home, name='user_home'),
]
