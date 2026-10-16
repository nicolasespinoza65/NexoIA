from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse


class MonitoreoTests(TestCase):
    def test_el_endpoint_de_salud_responde_ok_sin_pedir_sesion(self):
        resp = self.client.get(reverse("health"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok", "database": True, "cache": True})

    def test_si_la_base_de_datos_falla_responde_503(self):
        with patch("nexoia_site.views.connection.cursor", side_effect=Exception("sin conexión")):
            resp = self.client.get(reverse("health"))
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["status"], "error")
        self.assertFalse(resp.json()["database"])

    @override_settings(ENVIRONMENT_LABEL="pruebas")
    def test_en_el_ambiente_de_pruebas_se_muestra_un_aviso(self):
        self.assertContains(self.client.get(reverse("home")), "Ambiente de pruebas")

    def test_en_produccion_no_hay_aviso(self):
        self.assertNotContains(self.client.get(reverse("home")), "env-banner")


class WhatsappTests(TestCase):
    def test_sin_numero_configurado_no_hay_boton(self):
        self.assertNotContains(self.client.get(reverse("home")), "wa-float")

    @override_settings(COMPANY={"name": "SSDP", "phone": "", "whatsapp": "+56 9 1234 5678", "email": "", "hours": "", "area": "", "address": ""})
    def test_con_numero_configurado_aparece_para_visitantes(self):
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "https://wa.me/56912345678")
        self.assertContains(resp, "wa-float")
