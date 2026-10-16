import json
import re

from django.test import TestCase
from django.urls import reverse

from .models import FaqEntry


def faq(title, answer="Respuesta.", **extra):
    return FaqEntry.objects.create(title=title, keywords=title.lower(), answer=answer, **extra)


class FaqEnPortadaTests(TestCase):
    def home(self):
        return self.client.get(reverse("home"))

    def test_la_portada_muestra_las_respuestas_activas(self):
        faq("¿Atienden fines de semana?", "Sí, con coordinación previa.")
        resp = self.home()
        self.assertContains(resp, "Preguntas frecuentes")
        self.assertContains(resp, "¿Atienden fines de semana?")
        self.assertContains(resp, "Sí, con coordinación previa.")

    def test_las_inactivas_no_se_publican(self):
        faq("Visible")
        faq("Borrador interno", "No publicar", active=False)
        resp = self.home()
        self.assertContains(resp, "Visible")
        self.assertNotContains(resp, "Borrador interno")
        self.assertNotContains(resp, "No publicar")

    def test_sin_respuestas_no_aparece_la_seccion_ni_los_datos_estructurados(self):
        resp = self.home()
        self.assertNotContains(resp, "faq-list")
        self.assertNotContains(resp, "application/ld+json")

    def test_las_sugeridas_van_primero(self):
        faq("A segunda")
        faq("Z primera", suggested=True)
        titles = [f["title"] for f in self.home().context["faqs"]]
        self.assertEqual(titles, ["Z primera", "A segunda"])

    def test_datos_estructurados_para_buscadores(self):
        faq("¿Cuánto demora una visita?", "Entre 24 y 48 horas hábiles.")
        html = self.home().content.decode()
        raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
        data = json.loads(raw)
        self.assertEqual(data["@type"], "FAQPage")
        question = data["mainEntity"][0]
        self.assertEqual(question["name"], "¿Cuánto demora una visita?")
        self.assertEqual(question["acceptedAnswer"]["text"], "Entre 24 y 48 horas hábiles.")

    def test_un_texto_con_codigo_no_rompe_la_pagina(self):
        faq("Trampa <b>x</b>", "</script><script>alert(1)</script> & más")
        html = self.home().content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<b>x</b>", html)
        raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
        self.assertEqual(json.loads(raw)["mainEntity"][0]["acceptedAnswer"]["text"], "</script><script>alert(1)</script> & más")
