from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tickets.models import Ticket


def make_user(username, role):
    return User.objects.create_user(username=username, password="Clave-segura-123", role=role, email=f"{username}@example.com", email_verified=True)


class IndicadoresTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", User.Role.ADMIN)
        self.cliente = make_user("cliente", User.Role.CLIENTE)
        self.trabajador = make_user("trabajador", User.Role.TRABAJADOR)
        self.client.force_login(self.admin)

    def ticket(self, dias_atras=0, **extra):
        values = {"client": self.cliente, "title": "Falla", "description": "x"}
        values.update(extra)
        ticket = Ticket.objects.create(**values)
        if dias_atras:
            Ticket.objects.filter(pk=ticket.pk).update(created_at=timezone.now() - timedelta(days=dias_atras))
        return ticket

    def stats(self, **params):
        return self.client.get(reverse("stats:dashboard"), params).context["stats"]

    def test_filtro_por_fechas(self):
        self.ticket(dias_atras=10)
        self.ticket()
        desde = (timezone.localdate() - timedelta(days=3)).isoformat()
        self.assertEqual(self.stats()["total_tickets"], 2)
        self.assertEqual(self.stats(desde=desde)["total_tickets"], 1)

    def test_fechas_invalidas_se_ignoran(self):
        self.ticket()
        self.assertEqual(self.stats(desde="no-es-fecha", hasta="2026-99-99")["total_tickets"], 1)

    def test_tickets_sin_atender_hace_mas_de_24_horas(self):
        self.ticket(dias_atras=3)
        self.ticket()  # recién creado: no cuenta
        self.ticket(dias_atras=3, status=Ticket.Status.ASIGNADO)  # ya asignado: no cuenta
        stats = self.stats()
        self.assertEqual(stats["stale_count"], 1)
        self.assertGreaterEqual(stats["stale_tickets"][0]["hours"], 72)

    def test_carga_actual_por_trabajador(self):
        self.ticket(worker=self.trabajador, status=Ticket.Status.ASIGNADO)
        self.ticket(worker=self.trabajador, status=Ticket.Status.EN_PROCESO)
        self.ticket(worker=self.trabajador, status=Ticket.Status.CERRADO)
        carga = self.stats()["worker_load"][0]
        self.assertEqual((carga.active, carga.done), (2, 1))

    def test_satisfaccion_promedio_y_distribucion(self):
        self.ticket(status=Ticket.Status.CERRADO, rating=5)
        self.ticket(status=Ticket.Status.CERRADO, rating=4)
        self.ticket(status=Ticket.Status.CERRADO)  # sin calificar: no cuenta
        satisfaccion = self.stats()["satisfaction"]
        self.assertEqual(satisfaccion["average"], "4,5")
        self.assertEqual(satisfaccion["count"], 2)
        self.assertEqual(satisfaccion["distribution"][0]["count"], 1)  # 5 estrellas

    def test_volumen_semanal_tiene_ocho_semanas(self):
        self.ticket()
        semanas = self.stats()["weekly_volume"]
        self.assertEqual(len(semanas), 8)
        self.assertEqual(semanas[-1]["count"], 1)

    def test_el_estado_cancelado_aparece_en_el_desglose(self):
        self.ticket(status=Ticket.Status.CANCELADO)
        desglose = {fila["code"]: fila["count"] for fila in self.stats()["tickets_by_status"]}
        self.assertEqual(desglose["CANCELADO"], 1)
