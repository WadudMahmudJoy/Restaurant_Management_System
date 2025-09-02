from django.urls import path
from . import views

urlpatterns = [
    path('', views.homepage, name='homepage'),
    path('rms-admin/login/', views.admin_login, name='admin_login'),
    path('rms-admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('rms-admin/register/', views.admin_register, name='admin_register'),
    path('user/', views.user_home, name='user_home'),
]
