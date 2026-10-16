from django.conf import settings
from django.db import models


class ChatMessage(models.Model):
    """Registro de cada interacción cliente-asistente IA."""

    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
    question = models.CharField(max_length=2000)
    answer = models.CharField(max_length=4000)
    resolved_by_ai = models.BooleanField(default=False)
    reviewed = models.BooleanField(default=False)  # el administrador ya revisó esta pregunta sin respuesta
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class FaqEntry(models.Model):
    """Respuesta fija que el administrador puede crear y editar sin tocar el código.
    Se activa cuando la pregunta contiene alguna de las palabras clave (o es idéntica al título)."""

    title = models.CharField(max_length=120)  # nombre de la respuesta; si es "sugerida", es el texto del botón rápido
    keywords = models.CharField(max_length=300)  # frases separadas por coma
    answer = models.TextField(max_length=1000)
    suggested = models.BooleanField(default=False)  # aparece como pregunta rápida en el chat
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title
