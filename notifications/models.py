from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Notificación interna dirigida a un usuario."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    message = models.CharField(max_length=255)
    link = models.CharField(max_length=200, blank=True)  # a dónde lleva la notificación (p. ej. el ticket)
    seen = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
