from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tickets.models import Ticket, TicketComment, TicketEvent
from . import services


def make_user(username, role):
    return User.objects.create_user(username=username, password="Clave-segura-123", role=role, email=f"{username}@example.com", email_verified=True)


class PrimeraRespuestaTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", User.Role.ADMIN)
        self.mod = make_user("mod", User.Role.MODERADOR)
        self.cliente = make_user("cliente", User.Role.CLIENTE)
        self.base = timezone.now() - timedelta(days=2)

    def ticket(self):
        ticket = Ticket.objects.create(client=self.cliente, title="Falla", description="x")
        Ticket.objects.filter(pk=ticket.pk).update(created_at=self.base)
        return ticket

    def comentario(self, ticket, autor, horas):
        c = TicketComment.objects.create(ticket=ticket, author=autor, text="Hola")
        TicketComment.objects.filter(pk=c.pk).update(created_at=self.base + timedelta(hours=horas))

    def evento(self, ticket, actor, kind, horas):
        e = TicketEvent.objects.create(ticket=ticket, actor=actor, kind=kind)
        TicketEvent.objects.filter(pk=e.pk).update(created_at=self.base + timedelta(hours=horas))

    def medir(self):
        return services.summary()["avg_first_response"], services.summary()["first_response_count"]

    def test_sin_tickets_o_sin_respuestas_no_hay_dato(self):
        self.assertEqual(self.medir(), (None, 0))
        self.ticket()
        self.assertEqual(self.medir(), (None, 0))

    def test_el_primer_comentario_del_equipo_marca_la_respuesta(self):
        ticket = self.ticket()
        self.comentario(ticket, self.mod, 2)
        self.comentario(ticket, self.mod, 9)  # los siguientes no cambian la primera respuesta
        self.assertEqual(self.medir(), ("2,0 h", 1))

    def test_un_comentario_del_cliente_no_cuenta(self):
        ticket = self.ticket()
        self.comentario(ticket, self.cliente, 1)
        self.assertEqual(self.medir(), (None, 0))

    def test_cuenta_lo_que_ocurra_primero_entre_comentario_y_asignacion(self):
        ticket = self.ticket()
        self.comentario(ticket, self.mod, 5)
        self.evento(ticket, self.mod, TicketEvent.Kind.ASIGNADO, 1)
        self.assertEqual(self.medir(), ("1,0 h", 1))

    def test_la_creacion_la_calificacion_y_los_cambios_internos_no_cuentan(self):
        ticket = self.ticket()
        self.evento(ticket, self.cliente, TicketEvent.Kind.CREADO, 0)
        self.evento(ticket, self.mod, TicketEvent.Kind.PRIORIDAD, 1)   # triage interno: el cliente no lo ve
        self.evento(ticket, self.mod, TicketEvent.Kind.CATEGORIA, 1)
        self.evento(ticket, None, TicketEvent.Kind.ESTADO, 1)          # sin autor (sistema)
        self.assertEqual(self.medir(), (None, 0))

    def test_promedia_solo_los_tickets_respondidos(self):
        a, b, sin_responder = self.ticket(), self.ticket(), self.ticket()
        self.comentario(a, self.mod, 2)
        self.evento(b, self.mod, TicketEvent.Kind.ASIGNADO, 4)
        self.assertEqual(self.medir(), ("3,0 h", 2))

    def test_el_dashboard_muestra_el_indicador(self):
        ticket = self.ticket()
        self.comentario(ticket, self.mod, 3)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("stats:dashboard"))
        self.assertContains(resp, "primera respuesta")
        self.assertEqual(resp.context["stats"]["avg_first_response"], "3,0 h")
