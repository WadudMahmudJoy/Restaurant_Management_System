from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("orders/", views.board, name="board"),
    path("kitchen/", views.kitchen, name="kitchen"),
    path("api/orders/", views.api_orders, name="api_orders"),
    path("api/orders/action/", views.api_order_action, name="api_action"),
    path("api/orders/create/", views.api_order_create, name="api_create"),
    path("api/orders/note/", views.api_guest_note, name="api_note"),
    path("api/floor/", views.api_floor, name="api_floor"),
    path("api/floor/table/", views.api_table_update, name="api_table"),
    path("api/guest/order/", views.api_guest_order, name="api_guest"),
]
