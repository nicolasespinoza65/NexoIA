from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from . import services
from .models import Notification


def make_user(username, role=User.Role.CLIENTE, **extra):
    extra.setdefault("email", f"{username}@example.com")
    extra.setdefault("email_verified", True)
    return User.objects.create_user(username=username, password="Clave-segura-123", role=role, **extra)


class NotificacionesTests(TestCase):
    def setUp(self):
        self.user = make_user("cliente")

    def test_la_notificacion_guarda_el_enlace_y_el_correo_lo_incluye(self):
        services.notify_user(self.user, "Tu ticket cambió", link="/tickets/3/")
        self.assertEqual(Notification.objects.get().link, "/tickets/3/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/tickets/3/", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ["cliente@example.com"])

    def test_un_fallo_de_correo_no_rompe_la_operacion(self):
        with patch("notifications.services.send_mail", side_effect=Exception("servidor caído")):
            services.notify_user(self.user, "Aviso")
        self.assertEqual(Notification.objects.count(), 1)

    def test_sin_correo_registrado_solo_queda_la_notificacion(self):
        sin_correo = make_user("sincorreo", email="")
        services.notify_user(sin_correo, "Aviso")
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_la_lista_se_pagina_de_a_20(self):
        for i in range(25):
            Notification.objects.create(user=self.user, message=f"Aviso {i}")
        self.client.force_login(self.user)
        self.assertEqual(len(self.client.get(reverse("notifications:list")).context["page_obj"]), 20)
        self.assertEqual(len(self.client.get(reverse("notifications:list"), {"page": 2}).context["page_obj"]), 5)

    def test_eliminar_leidas_conserva_las_no_leidas_y_las_de_otros(self):
        otro = make_user("otro")
        Notification.objects.create(user=self.user, message="leída", seen=True)
        Notification.objects.create(user=self.user, message="nueva")
        Notification.objects.create(user=otro, message="de otro", seen=True)
        self.client.force_login(self.user)
        self.client.post(reverse("notifications:clear_read"))
        self.assertEqual(list(Notification.objects.filter(user=self.user).values_list("message", flat=True)), ["nueva"])
        self.assertEqual(Notification.objects.filter(user=otro).count(), 1)

    def test_marcar_leidas_y_acciones_solo_por_post(self):
        Notification.objects.create(user=self.user, message="nueva")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("notifications:mark_read")).status_code, 405)
        self.assertEqual(self.client.get(reverse("notifications:clear_read")).status_code, 405)
        self.client.post(reverse("notifications:mark_read"))
        self.assertTrue(Notification.objects.get().seen)
