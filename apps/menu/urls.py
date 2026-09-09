from django.urls import path

from . import views

app_name = "menu"

urlpatterns = [
    path("menu/", views.guest_menu, name="guest"),
    path("studio/", views.studio, name="studio"),
    path("api/menu/items/", views.api_items, name="api_items"),
    path("api/menu/items/<int:pk>/", views.api_item_detail, name="api_item"),
    path("api/menu/suggest/", views.api_suggest, name="api_suggest"),
    path("api/menu/save/", views.api_save, name="api_save"),
    path("api/menu/restock/", views.api_restock, name="api_restock"),
    path("api/menu/adjust/", views.api_adjust, name="api_adjust"),
    path("api/menu/price/", views.api_price, name="api_price"),
    path("api/menu/toggle/", views.api_toggle, name="api_toggle"),
    path("api/menu/delete/", views.api_delete, name="api_delete"),
    path("api/menu/photos/", views.api_photos, name="api_photos"),
    path("api/menu/photos/upload/", views.api_photo_upload, name="api_photo_upload"),
    path("api/menu/photos/attach/", views.api_photo_attach, name="api_photo_attach"),
    path("api/menu/photos/delete/", views.api_photo_delete, name="api_photo_delete"),
    path("api/menu/chapters/", views.api_public_menu, name="api_chapters"),
]
