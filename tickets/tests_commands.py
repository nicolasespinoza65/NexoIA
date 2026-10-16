from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from chatbot.models import ChatMessage
from notifications.models import Notification
from .models import Ticket


def make_user(username, role):
    return User.objects.create_user(username=username, password="Clave-segura-123", role=role,
                                    email=f"{username}@example.com", email_verified=True)


class RecordatoriosTests(TestCase):
    def setUp(self):
        self.cliente = make_user("cliente", User.Role.CLIENTE)
        self.trabajador = make_user("trabajador", User.Role.TRABAJADOR)
        self.mod = make_user("mod", User.Role.MODERADOR)

    def ejecutar(self):
        salida = StringIO()
        call_command("send_reminders", stdout=salida)
        return salida.getvalue()

    def ticket(self, **extra):
        values = {"client": self.cliente, "title": "Falla", "description": "x", "worker": self.trabajador,
                  "status": Ticket.Status.ASIGNADO}
        values.update(extra)
        return Ticket.objects.create(**values)

    def manana_al_mediodia(self):
        return (timezone.localtime() + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)

    def test_recuerda_la_visita_de_manana_una_sola_vez(self):
        ticket = self.ticket(visit_at=self.manana_al_mediodia())
        self.ejecutar()
        for usuario in (self.cliente, self.trabajador):
            self.assertTrue(Notification.objects.filter(user=usuario, message__contains="Recordatorio: visita mañana").exists())
        ticket.refresh_from_db()
        self.assertTrue(ticket.visit_reminded)
        antes = Notification.objects.count()
        self.ejecutar()
        self.assertEqual(Notification.objects.count(), antes)  # no se repite

    def test_no_recuerda_visitas_lejanas_ni_de_tickets_terminados(self):
        self.ticket(visit_at=timezone.now() + timedelta(days=5))
        self.ticket(visit_at=self.manana_al_mediodia(), status=Ticket.Status.CANCELADO)
        self.ejecutar()
        self.assertFalse(Notification.objects.filter(message__contains="Recordatorio").exists())

    def test_el_resumen_diario_llega_a_los_moderadores_con_los_tickets_sin_atender(self):
        viejo = self.ticket(status=Ticket.Status.ABIERTO, worker=None, title="Sin atender hace días")
        Ticket.objects.filter(pk=viejo.pk).update(created_at=timezone.now() - timedelta(days=3))
        self.ejecutar()
        resumen = [m for m in mail.outbox if m.to == ["mod@example.com"]]
        self.assertEqual(len(resumen), 1)
        self.assertIn("Sin atender hace días", resumen[0].body)
        self.assertIn("1 tickets sin atender", resumen[0].subject)

    def test_sin_novedades_no_se_envia_resumen(self):
        self.ejecutar()
        self.assertEqual([m for m in mail.outbox if m.to == ["mod@example.com"]], [])


class LimpiezaTests(TestCase):
    def setUp(self):
        self.cliente = make_user("cliente", User.Role.CLIENTE)

    def vieja(self, model, dias, **campos):
        objeto = model.objects.create(**campos)
        model.objects.filter(pk=objeto.pk).update(created_at=timezone.now() - timedelta(days=dias))
        return objeto

    def test_borra_las_conversaciones_y_notificaciones_leidas_antiguas(self):
        self.vieja(ChatMessage, 200, client=self.cliente, question="vieja", answer="x")
        reciente = ChatMessage.objects.create(client=self.cliente, question="reciente", answer="x")
        self.vieja(Notification, 100, user=self.cliente, message="leída vieja", seen=True)
        sin_leer = self.vieja(Notification, 100, user=self.cliente, message="sin leer vieja", seen=False)
        call_command("purge_old_data", stdout=StringIO())
        self.assertEqual(list(ChatMessage.objects.all()), [reciente])
        self.assertEqual(list(Notification.objects.all()), [sin_leer])  # una notificación sin leer no se borra

    def test_el_modo_de_prueba_no_borra_nada(self):
        self.vieja(ChatMessage, 200, client=self.cliente, question="vieja", answer="x")
        salida = StringIO()
        call_command("purge_old_data", "--dry-run", stdout=salida)
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertIn("Se borrarían: 1 conversaciones", salida.getvalue())
