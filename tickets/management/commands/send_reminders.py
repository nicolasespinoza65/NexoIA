"""Recordatorios automáticos. Programar una vez al día (por ejemplo a las 8:00) con cron:

    0 8 * * * cd /ruta/al/proyecto && venv/bin/python manage.py send_reminders

1. Recordatorio de visitas: avisa al cliente y al trabajador de las visitas de hoy y de mañana
   (una sola vez por visita; si se reprograma, se vuelve a avisar).
2. Resumen diario: un correo a cada moderador y administrador con los tickets que llevan más de
   STALE_TICKET_HOURS horas sin asignar y las visitas de los próximos dos días."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from notifications.services import notify_user, send_email
from tickets.models import Ticket
from tickets.services import ACTIVE_STATUSES


class Command(BaseCommand):
    help = "Envía los recordatorios de visitas y el resumen diario de tickets sin atender"

    def handle(self, *args, **options):
        now = timezone.now()
        # Hasta el final de mañana (hora local): cada visita se recuerda el día anterior o el mismo día
        end_of_tomorrow = (timezone.localtime(now) + timedelta(days=1)).replace(hour=23, minute=59, second=59)
        visits = list(Ticket.objects.filter(
            visit_at__gt=now, visit_at__lte=end_of_tomorrow, visit_reminded=False, status__in=ACTIVE_STATUSES,
        ).select_related("client", "worker"))

        for ticket in visits:
            when = timezone.localtime(ticket.visit_at)
            day = "hoy" if when.date() == timezone.localdate() else "mañana"
            message = f"Recordatorio: visita {day} a las {when:%H:%M} en el ticket #{ticket.id}"
            link = reverse("tickets:detail", args=[ticket.id])
            notify_user(ticket.client, message, link=link)
            if ticket.worker:
                notify_user(ticket.worker, message, link=link)
            ticket.visit_reminded = True
            ticket.save(update_fields=["visit_reminded"])

        stale = list(Ticket.objects.filter(
            status=Ticket.Status.ABIERTO, created_at__lt=now - timedelta(hours=settings.STALE_TICKET_HOURS),
        ).select_related("client").order_by("created_at"))
        upcoming = list(Ticket.objects.filter(
            visit_at__gt=now, visit_at__lte=now + timedelta(days=2), status__in=ACTIVE_STATUSES,
        ).order_by("visit_at"))

        digests = 0
        if stale or upcoming:
            site = settings.SITE_URL.rstrip("/")
            lines = [f"Resumen del {timezone.localdate():%d/%m/%Y}", ""]
            if stale:
                lines.append(f"Tickets sin asignar hace más de {settings.STALE_TICKET_HOURS} horas ({len(stale)}):")
                for t in stale[:15]:
                    hours = int((now - t.created_at).total_seconds() // 3600)
                    lines.append(f"- #{t.id} {t.title} ({hours} h) {site}{reverse('tickets:detail', args=[t.id])}")
                if len(stale) > 15:
                    lines.append(f"... y {len(stale) - 15} más.")
                lines.append("")
            if upcoming:
                lines.append(f"Visitas de los próximos 2 días ({len(upcoming)}):")
                for t in upcoming[:15]:
                    lines.append(f"- {timezone.localtime(t.visit_at):%d/%m %H:%M} · #{t.id} {t.title} · {t.address or 'sin dirección'}")
            body = "\n".join(lines) + "\n\nSoluciones SSDP Servicios Integrales SpA"
            subject = f"Soluciones SSDP: {len(stale)} tickets sin atender, {len(upcoming)} visitas próximas"
            for user in User.objects.filter(role__in=[User.Role.MODERADOR, User.Role.ADMIN], is_active=True):
                send_email(user.email, subject, body)
                digests += 1

        self.stdout.write(self.style.SUCCESS(
            f"Recordatorios de visita: {len(visits)}. Resúmenes enviados: {digests}."
        ))
