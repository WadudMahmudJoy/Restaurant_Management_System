from django.urls import path
from . import views

urlpatterns = [
    path('', views.homepage, name='homepage'),
    # Future: path('admin-login/', views.admin_login, name='admin_login'),
    # Future: path('user/', views.user_home, name='user_home'),
]
