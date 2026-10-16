from django.urls import path
from . import views

app_name = "notifications"
urlpatterns = [
    path("", views.notification_list, name="list"),
    path("<int:pk>/abrir/", views.notification_open, name="open"),
    path("marcar-leidas/", views.mark_all_read, name="mark_read"),
    path("eliminar-leidas/", views.clear_read, name="clear_read"),
]
