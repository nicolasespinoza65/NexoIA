"""Borra datos que ya no hace falta conservar. Programar una vez al día con cron:

    30 3 * * * cd /ruta/al/proyecto && venv/bin/python manage.py purge_old_data

- Conversaciones con el asistente de más de CHAT_RETENTION_DAYS días (por defecto 180).
- Notificaciones ya leídas de más de NOTIFICATION_RETENTION_DAYS días (por defecto 90).
La política de privacidad del sitio indica este plazo: ajusta las variables al que defina la empresa."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from chatbot.models import ChatMessage
from notifications.models import Notification


class Command(BaseCommand):
    help = "Elimina conversaciones y notificaciones antiguas según los plazos de retención"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Solo muestra cuántos registros se borrarían")

    def handle(self, *args, **options):
        now = timezone.now()
        chats = ChatMessage.objects.filter(created_at__lt=now - timedelta(days=settings.CHAT_RETENTION_DAYS))
        notifications = Notification.objects.filter(
            seen=True, created_at__lt=now - timedelta(days=settings.NOTIFICATION_RETENTION_DAYS))
        counts = (chats.count(), notifications.count())
        if not options["dry_run"]:
            chats.delete()
            notifications.delete()
        verb = "Se borrarían" if options["dry_run"] else "Borrados"
        self.stdout.write(self.style.SUCCESS(
            f"{verb}: {counts[0]} conversaciones (más de {settings.CHAT_RETENTION_DAYS} días) y "
            f"{counts[1]} notificaciones leídas (más de {settings.NOTIFICATION_RETENTION_DAYS} días)."
        ))
