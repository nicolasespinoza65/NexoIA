from django.urls import path
from . import views

app_name = "tickets"
urlpatterns = [
    path("", views.ticket_list, name="list"),
    path("nuevo/", views.ticket_create, name="create"),
    path("exportar/", views.ticket_export, name="export"),
    path("agenda/", views.agenda, name="agenda"),
    path("<int:pk>/", views.ticket_detail, name="detail"),
    path("<int:pk>/foto/", views.ticket_image, name="image"),
    path("<int:pk>/asignar/", views.ticket_assign, name="assign"),
    path("<int:pk>/categoria/", views.ticket_category, name="category"),
    path("<int:pk>/eliminar/", views.ticket_delete, name="delete"),
    path("<int:pk>/cancelar/", views.ticket_cancel, name="cancel"),
    path("<int:pk>/reabrir/", views.ticket_reopen, name="reopen"),
    path("<int:pk>/calificar/", views.ticket_rate, name="rate"),
    path("<int:pk>/prioridad/", views.ticket_priority, name="priority"),
    path("<int:pk>/cotizaciones/", views.ticket_quote_create, name="quote_create"),
    path("<int:pk>/cotizaciones/<int:quote_id>/responder/", views.ticket_quote_respond, name="quote_respond"),
    path("<int:pk>/visita/", views.ticket_visit, name="visit"),
    path("<int:pk>/fotos/", views.ticket_photo_upload, name="photo_upload"),
    path("<int:pk>/fotos/<int:photo_id>/", views.ticket_photo, name="photo"),
    path("<int:pk>/sugerir/", views.ticket_suggest, name="suggest"),
    path("<int:pk>/sugerir/descartar/", views.ticket_suggest_dismiss, name="suggest_dismiss"),
    path("<int:pk>/estado/<str:status>/", views.ticket_status, name="status"),
]
