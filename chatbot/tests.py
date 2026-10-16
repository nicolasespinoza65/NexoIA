import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import AuditLog, User
from notifications.models import Notification
from tickets.models import Ticket
from .models import ChatMessage, FaqEntry


def make_user(username, role, **extra):
    extra.setdefault("email", f"{username}@example.com")
    extra.setdefault("email_verified", True)
    return User.objects.create_user(username=username, password="Clave-segura-123", role=role, **extra)


class ChatbotTests(TestCase):
    def setUp(self):
        self.cliente = make_user("cliente", User.Role.CLIENTE)
        self.url = reverse("chatbot:send")

    def enviar(self, texto):
        return self.client.post(self.url, data=json.dumps({"message": texto}), content_type="application/json")

    def test_pregunta_frecuente_se_responde_sin_crear_ticket(self):
        self.client.force_login(self.cliente)
        with patch("chatbot.services._call_model", return_value=None):
            data = self.enviar("¿Cómo creo un ticket?").json()
        self.assertIn("Nuevo ticket", data["answer"])
        self.assertIsNone(data["ticket_id"])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_consulta_que_la_ia_no_resuelve_crea_ticket_clasificado(self):
        self.client.force_login(self.cliente)
        with patch("chatbot.services._call_model", return_value=None):
            data = self.enviar("Necesito una cotización para mi taller").json()
        ticket = Ticket.objects.get()
        self.assertEqual(data["ticket_id"], ticket.id)
        self.assertEqual(ticket.source, "IA")
        self.assertEqual(ticket.category, "COTIZACION")

    def test_mensaje_vacio_responde_error_en_json(self):
        self.client.force_login(self.cliente)
        resp = self.enviar("   ")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_historial_incluye_preguntas_sugeridas(self):
        self.client.force_login(self.cliente)
        data = self.client.get(reverse("chatbot:history")).json()
        self.assertIn("suggestions", data)
        self.assertGreaterEqual(len(data["suggestions"]), 3)

    def test_visitante_sin_sesion_no_puede_enviar(self):
        resp = self.enviar("Hola")
        self.assertEqual(resp.status_code, 302)  # lo manda a iniciar sesión

    def test_el_personal_no_usa_el_chat(self):
        self.client.force_login(make_user("mod", User.Role.MODERADOR))
        self.assertEqual(self.enviar("Hola").status_code, 403)

    def test_preguntas_basicas_se_responden_sin_ticket(self):
        self.client.force_login(self.cliente)
        casos = {
            "Hola": "asistente virtual",
            "Muchas gracias": "De nada",
            "Chao": "Hasta luego",
            "¿Quién eres?": "asistente virtual",
            "¿En qué me puedes ayudar?": "Puedo ayudarte",
            "¿Cómo veo el estado de mi ticket?": "Mis tickets",
            "¿Qué categorías hay?": "reclamo",
            "¿Cuánto se demora un trabajo?": "no comprometemos fechas",
            "Tengo una emergencia": "Bomberos",
        }
        with patch("chatbot.services._call_model", return_value=None):
            for pregunta, esperado in casos.items():
                data = self.enviar(pregunta).json()
                self.assertIn(esperado, data["answer"], pregunta)
                self.assertIsNone(data["ticket_id"], pregunta)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_un_saludo_con_una_necesidad_real_no_se_traga_el_caso(self):
        self.client.force_login(self.cliente)
        with patch("chatbot.services._call_model", return_value=None):
            data = self.enviar("Hola, necesito cotizar un tablero nuevo").json()
        self.assertIsNotNone(data["ticket_id"])

    # ---- protección del gasto de IA
    def test_sin_correo_confirmado_no_se_usa_la_ia_ni_se_crean_tickets(self):
        self.client.force_login(make_user("nuevo", User.Role.CLIENTE, email_verified=False))
        with patch("chatbot.services._call_model") as modelo:
            data = self.enviar("Necesito una cotización para mi taller").json()
            basica = self.enviar("¿Cómo creo un ticket?").json()
        modelo.assert_not_called()
        self.assertIn("confirma tu correo", data["answer"])
        self.assertIsNone(data["ticket_id"])
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertIn("Nuevo ticket", basica["answer"])  # las preguntas básicas siguen funcionando

    @override_settings(CHAT_MAX_PER_HOUR=2)
    def test_hay_un_tope_de_mensajes_por_hora(self):
        for _ in range(2):
            ChatMessage.objects.create(client=self.cliente, question="p", answer="r")
        self.client.force_login(self.cliente)
        with patch("chatbot.services._call_model") as modelo:
            data = self.enviar("Necesito una cotización para mi taller").json()
        modelo.assert_not_called()
        self.assertIn("límite", data["answer"])
        self.assertEqual(Ticket.objects.count(), 0)


    # ---- temas ajenos a la empresa
    def test_sin_ia_un_tema_ajeno_se_rechaza_sin_crear_ticket(self):
        self.client.force_login(self.cliente)
        with patch("chatbot.services.ANTHROPIC_API_KEY", ""):
            data = self.enviar("¿Cuál es la capital de Francia?").json()
        self.assertIn("No puedo ayudarte con eso", data["answer"])
        self.assertIsNone(data["ticket_id"])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_sin_ia_una_consulta_del_rubro_sigue_creando_ticket(self):
        self.client.force_login(self.cliente)
        with patch("chatbot.services.ANTHROPIC_API_KEY", ""):
            data = self.enviar("Se me cortó la luz en la cocina").json()
        self.assertIsNotNone(data["ticket_id"])

    def test_con_ia_el_marcador_fuera_de_tema_rechaza_aunque_venga_con_texto_antes(self):
        self.client.force_login(self.cliente)
        with patch("chatbot.services.ANTHROPIC_API_KEY", "clave"), \
                patch("chatbot.services._call_model", return_value="Lo siento. [FUERA_DE_TEMA]"):
            data = self.enviar("¿Quién ganó el mundial?").json()
        self.assertIn("No puedo ayudarte con eso", data["answer"])
        self.assertNotIn("FUERA_DE_TEMA", data["answer"])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_una_cuenta_matematica_no_crea_ticket(self):
        self.client.force_login(self.cliente)
        with patch("chatbot.services.ANTHROPIC_API_KEY", ""):
            data = self.enviar("1+1").json()
        self.assertIn("No puedo ayudarte con eso", data["answer"])
        self.assertIsNone(data["ticket_id"])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_con_ia_si_el_modelo_deriva_un_tema_ajeno_tampoco_se_crea_ticket(self):
        self.client.force_login(self.cliente)
        for respuesta in ("[DERIVAR]", None):  # el modelo deriva o se cae/tarda demasiado
            with patch("chatbot.services.ANTHROPIC_API_KEY", "clave"), \
                    patch("chatbot.services._call_model", return_value=respuesta):
                data = self.enviar("1+1").json()
            self.assertIn("No puedo ayudarte con eso", data["answer"])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_con_ia_una_consulta_del_rubro_que_el_modelo_deriva_si_crea_ticket(self):
        self.client.force_login(self.cliente)
        with patch("chatbot.services.ANTHROPIC_API_KEY", "clave"), \
                patch("chatbot.services._call_model", return_value="[DERIVAR]"):
            data = self.enviar("Necesito una cotización para mi taller").json()
        self.assertIsNotNone(data["ticket_id"])

    def test_la_charla_de_cortesia_no_se_toma_por_tema_ajeno(self):
        from chatbot import services
        for texto in ("no, gracias, eso es todo", "sí por favor", "ok", "Se me quemó un enchufe", "necesito ayuda",
                      "+56 9 1234 5678", "👍"):
            self.assertFalse(services._is_off_topic(texto), texto)
        for texto in ("1+1", "2 x 3", "¿cuánto es 5 por 5?", "cuéntame un chiste", "capital de Chile"):
            self.assertTrue(services._is_off_topic(texto), texto)


class ChatVisitanteTests(TestCase):
    """El chat sin cuenta responde solo lo básico: no usa la IA, no guarda nada y no crea tickets."""

    def setUp(self):
        cache.clear()

    def enviar(self, texto):
        return self.client.post(reverse("chatbot:visitor"), data=json.dumps({"message": texto}), content_type="application/json")

    def test_visitante_recibe_respuestas_basicas_sin_cuenta(self):
        data = self.enviar("¿Qué servicios ofrecen?").json()
        self.assertIn("instalaciones", data["answer"])
        self.assertFalse(data["needs_account"])
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_si_la_respuesta_habla_de_tickets_aclara_que_necesita_cuenta(self):
        data = self.enviar("¿Cómo creo un ticket?").json()
        self.assertIn("cuenta de cliente", data["answer"])

    def test_visitante_con_un_caso_real_debe_ingresar_y_no_se_crea_nada(self):
        data = self.enviar("Se me quemó un enchufe").json()
        self.assertTrue(data["needs_account"])
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_visitante_nunca_activa_la_ia(self):
        with patch("chatbot.services._call_model") as modelo:
            self.enviar("Se me quemó un enchufe")
            self.enviar("Necesito una cotización")
        modelo.assert_not_called()

    def test_visitante_con_tema_ajeno_no_recibe_la_invitacion_a_registrarse(self):
        data = self.enviar("¿Cuál es la capital de Francia?").json()
        self.assertIn("No puedo ayudarte con eso", data["answer"])
        self.assertFalse(data["needs_account"])

    def test_sugerencias_para_visitantes_no_incluyen_el_estado_del_ticket(self):
        data = self.client.get(reverse("chatbot:visitor")).json()
        self.assertGreaterEqual(len(data["suggestions"]), 3)
        self.assertFalse(any("estado de mi ticket" in s for s in data["suggestions"]))

    def test_mensaje_vacio_o_invalido(self):
        self.assertEqual(self.enviar("   ").status_code, 400)
        resp = self.client.post(reverse("chatbot:visitor"), data="no es json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    @override_settings(VISITOR_CHAT_MAX_PER_10MIN=2)
    def test_el_visitante_tiene_un_tope_de_mensajes(self):
        self.assertEqual(self.enviar("hola").status_code, 200)
        self.assertEqual(self.enviar("hola").status_code, 200)
        resp = self.enviar("hola")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("error", resp.json())


class RespuestasEditablesTests(TestCase):
    """El administrador crea respuestas fijas desde el panel, sin tocar el código."""

    def setUp(self):
        cache.clear()
        self.admin = make_user("admin", User.Role.ADMIN)
        self.cliente = make_user("cliente", User.Role.CLIENTE)
        FaqEntry.objects.create(
            title="¿Hacen visitas a domicilio?", keywords="visita, a domicilio",
            answer="Sí, visitamos tu domicilio previa coordinación.", suggested=True,
        )

    def enviar(self, texto):
        self.client.force_login(self.cliente)
        with patch("chatbot.services._call_model", return_value=None):
            return self.client.post(reverse("chatbot:send"), data=json.dumps({"message": texto}), content_type="application/json").json()

    def test_se_activa_por_palabra_clave_y_por_el_titulo_exacto(self):
        self.assertIn("visitamos tu domicilio", self.enviar("¿Van a domicilio a revisar el medidor?")["answer"])
        self.assertIn("visitamos tu domicilio", self.enviar("¿Hacen visitas a domicilio?")["answer"])
        self.assertEqual(Ticket.objects.count(), 0)

    def test_una_respuesta_inactiva_no_se_usa(self):
        FaqEntry.objects.update(active=False)
        self.assertIsNotNone(self.enviar("¿Van a domicilio?")["ticket_id"])

    def test_las_respuestas_sugeridas_aparecen_como_pregunta_rapida(self):
        self.client.force_login(self.cliente)
        suggestions = self.client.get(reverse("chatbot:history")).json()["suggestions"]
        self.assertIn("¿Hacen visitas a domicilio?", suggestions)

    def test_el_visitante_tambien_recibe_las_respuestas_del_administrador(self):
        resp = self.client.post(reverse("chatbot:visitor"), data=json.dumps({"message": "¿van a domicilio?"}), content_type="application/json")
        self.assertIn("visitamos tu domicilio", resp.json()["answer"])

    def test_el_admin_crea_edita_y_elimina_respuestas(self):
        FaqEntry.objects.all().delete()
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("chatbot:faq_list"), {
            "title": "Horario", "keywords": "horario, atienden", "answer": "De lunes a viernes", "active": "on",
        })
        self.assertRedirects(resp, reverse("chatbot:faq_list"))
        entry = FaqEntry.objects.get()

        self.client.post(reverse("chatbot:faq_edit", args=[entry.id]), {
            "title": "Horario", "keywords": "horario", "answer": "Nuevo texto", "active": "on",
        })
        entry.refresh_from_db()
        self.assertEqual(entry.answer, "Nuevo texto")

        self.client.post(reverse("chatbot:faq_delete", args=[entry.id]))
        self.assertEqual(FaqEntry.objects.count(), 0)

    def test_las_palabras_clave_deben_tener_al_menos_tres_letras(self):
        FaqEntry.objects.all().delete()
        self.client.force_login(self.admin)
        self.client.post(reverse("chatbot:faq_list"), {"title": "X", "keywords": "ab, c", "answer": "Y", "active": "on"})
        self.assertEqual(FaqEntry.objects.count(), 0)

    def test_solo_el_administrador_gestiona_las_respuestas(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(reverse("chatbot:faq_list")).status_code, 403)
        entry = FaqEntry.objects.get()
        self.assertEqual(self.client.post(reverse("chatbot:faq_delete", args=[entry.id])).status_code, 403)
        self.assertEqual(FaqEntry.objects.count(), 1)


class AtencionHumanaTests(TestCase):
    """El botón «Hablar con una persona» crea un ticket con el contexto para que un moderador responda."""

    def setUp(self):
        self.cliente = make_user("cliente", User.Role.CLIENTE)
        self.mod = make_user("mod", User.Role.MODERADOR)
        self.url = reverse("chatbot:human")

    def test_crea_un_ticket_con_la_conversacion_y_avisa_a_los_moderadores(self):
        ChatMessage.objects.create(client=self.cliente, question="¿Cuánto cuesta un empalme?", answer="Lo revisa un moderador")
        self.client.force_login(self.cliente)
        data = self.client.post(self.url).json()
        ticket = Ticket.objects.get()
        self.assertEqual(data["ticket_id"], ticket.id)
        self.assertIn("Solicitud de atención de una persona", ticket.title)
        self.assertIn("¿Cuánto cuesta un empalme?", ticket.description)
        self.assertEqual(ticket.source, "IA")
        self.assertTrue(Notification.objects.filter(user=self.mod, message__contains="atención de una persona").exists())

    def test_no_duplica_la_solicitud_abierta(self):
        self.client.force_login(self.cliente)
        primero = self.client.post(self.url).json()
        segundo = self.client.post(self.url).json()
        self.assertEqual(primero["ticket_id"], segundo["ticket_id"])
        self.assertIn("Ya tienes una solicitud abierta", segundo["answer"])
        self.assertEqual(Ticket.objects.count(), 1)

    def test_solo_los_clientes_con_sesion_pueden_pedirlo(self):
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.client.force_login(self.mod)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_requiere_post(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(self.url).status_code, 405)


class PreguntasSinRespuestaTests(TestCase):
    """Reporte para el administrador: lo que el asistente no supo contestar, convertible en respuesta con un clic."""

    def setUp(self):
        self.admin = make_user("admin", User.Role.ADMIN)
        self.cliente = make_user("cliente", User.Role.CLIENTE)

    def pregunta(self, texto, veces=1, **extra):
        for _ in range(veces):
            ChatMessage.objects.create(client=self.cliente, question=texto, answer="derivado", **extra)

    def test_agrupa_ordena_por_frecuencia_y_sugiere_palabras_clave(self):
        self.pregunta("¿Instalan paneles solares?", veces=3)
        self.pregunta("¿instalan PANELES solares?")  # misma pregunta, otra escritura
        self.pregunta("¿Hacen domótica?", veces=2)
        self.client.force_login(self.admin)
        grupos = self.client.get(reverse("chatbot:unanswered")).context["groups"]
        self.assertEqual([g["count"] for g in grupos], [4, 2])
        self.assertIn("paneles", grupos[0]["keywords"])

    def test_no_muestra_lo_ya_respondido_ni_lo_resuelto_ni_lo_descartado(self):
        self.pregunta("¿Qué servicios ofrecen?")  # ya la cubre una respuesta del sistema
        self.pregunta("pregunta resuelta por la ia", resolved_by_ai=True)
        self.pregunta("pregunta ya revisada", reviewed=True)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("chatbot:unanswered")).context["groups"], [])

    def test_una_respuesta_nueva_hace_desaparecer_la_pregunta(self):
        self.pregunta("¿Instalan paneles solares?")
        FaqEntry.objects.create(title="Paneles", keywords="paneles solares", answer="Sí, instalamos paneles.")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("chatbot:unanswered")).context["groups"], [])

    def test_descartar_marca_como_revisadas_solo_esas_preguntas(self):
        self.pregunta("¿Hacen domótica?", veces=2)
        self.pregunta("¿Venden focos?")
        ids = ",".join(str(i) for i in ChatMessage.objects.filter(question__contains="domótica").values_list("id", flat=True))
        self.client.force_login(self.admin)
        self.client.post(reverse("chatbot:unanswered_dismiss"), {"ids": ids})
        self.assertEqual(ChatMessage.objects.filter(reviewed=True).count(), 2)
        self.assertEqual([g["question"] for g in self.client.get(reverse("chatbot:unanswered")).context["groups"]], ["¿Venden focos?"])

    def test_crear_respuesta_precarga_el_formulario(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("chatbot:faq_list"), {"title": "¿Hacen domótica?", "keywords": "domótica"})
        self.assertEqual(resp.context["form"].initial["title"], "¿Hacen domótica?")
        self.assertEqual(resp.context["form"].initial["keywords"], "domótica")

    def test_solo_el_administrador_lo_ve(self):
        self.client.force_login(self.cliente)
        self.assertEqual(self.client.get(reverse("chatbot:unanswered")).status_code, 403)
        self.assertEqual(self.client.post(reverse("chatbot:unanswered_dismiss"), {"ids": "1"}).status_code, 403)


class AuditoriaDeRespuestasTests(TestCase):
    def test_crear_editar_y_eliminar_respuestas_queda_registrado(self):
        self.client.force_login(make_user("admin", User.Role.ADMIN))
        self.client.post(reverse("chatbot:faq_list"), {"title": "Horario", "keywords": "horario", "answer": "L a V", "active": "on"})
        entry = FaqEntry.objects.get()
        self.client.post(reverse("chatbot:faq_edit", args=[entry.id]), {"title": "Horario", "keywords": "horario", "answer": "Nuevo", "active": "on"})
        self.client.post(reverse("chatbot:faq_delete", args=[entry.id]))
        acciones = list(AuditLog.objects.order_by("id").values_list("action", flat=True))
        self.assertEqual(acciones, ["RESPUESTA_CREADA", "RESPUESTA_EDITADA", "RESPUESTA_ELIMINADA"])
