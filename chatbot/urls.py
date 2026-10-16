from django.urls import path
from . import views

app_name = "chatbot"
urlpatterns = [
    path("", views.chat, name="chat"),  # redirige al inicio (el chat ahora es flotante)
    path("historial/", views.history, name="history"),
    path("enviar/", views.send, name="send"),
    path("visitante/", views.visitor, name="visitor"),  # público: preguntas básicas sin cuenta
    path("persona/", views.human, name="human"),
    path("sin-respuesta/", views.unanswered, name="unanswered"),
    path("sin-respuesta/descartar/", views.unanswered_dismiss, name="unanswered_dismiss"),
    path("respuestas/", views.faq_list, name="faq_list"),
    path("respuestas/<int:pk>/editar/", views.faq_edit, name="faq_edit"),
    path("respuestas/<int:pk>/eliminar/", views.faq_delete, name="faq_delete"),
]
