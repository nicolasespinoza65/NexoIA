import io
import json
import re
import tempfile
import time
import zipfile
from unittest.mock import patch

from django.core import mail, signing
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from chatbot.models import ChatMessage
from notifications.models import Notification
from tickets.models import Ticket
from . import services, totp
from .forms import FORM_TS_SALT
from .models import AuditLog, User, WorkPhoto

PASSWORD = "Clave-segura-123"


def make_user(username, role, **extra):
    extra.setdefault("email", f"{username}@example.com")
    extra.setdefault("email_verified", True)
    return User.objects.create_user(username=username, password=PASSWORD, role=role, **extra)


@override_settings(REGISTER_MIN_SECONDS=0)
class RegistroTests(TestCase):
    def setUp(self):
        cache.clear()

    DATA = {
        "first_name": "Ana", "email": "ana@example.com", "username": "ana",
        "password1": PASSWORD, "password2": PASSWORD, "accept_terms": "on",
    }

    def test_registro_crea_un_cliente_con_sesion_y_pide_confirmar_el_correo(self):
        resp = self.client.post(reverse("register"), self.DATA)
        self.assertRedirects(resp, reverse("tickets:create"))
        user = User.objects.get(username="ana")
        self.assertEqual(user.role, User.Role.CLIENTE)
        self.assertFalse(user.email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/cuentas/verificar/", mail.outbox[0].body)

    def test_hay_que_aceptar_los_terminos(self):
        data = {k: v for k, v in self.DATA.items() if k != "accept_terms"}
        resp = self.client.post(reverse("register"), data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_un_correo_no_puede_registrarse_dos_veces(self):
        make_user("existente", User.Role.CLIENTE, email="ana@example.com")
        resp = self.client.post(reverse("register"), self.DATA)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.count(), 1)


class VerificacionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user("ana", User.Role.CLIENTE, email_verified=False)

    def test_el_enlace_valido_confirma_el_correo(self):
        resp = self.client.get(reverse("accounts:verify", args=[services.make_token(self.user)]))
        self.assertRedirects(resp, reverse("home"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)

    def test_un_enlace_alterado_se_rechaza(self):
        token = services.make_token(self.user) + "x"
        self.client.get(reverse("accounts:verify", args=[token]))
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_un_enlace_antiguo_no_sirve_si_cambio_el_correo(self):
        token = services.make_token(self.user)
        self.user.email = "otro@example.com"
        self.user.save()
        self.client.get(reverse("accounts:verify", args=[token]))
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_reenviar_el_correo_tiene_un_limite_de_uno_por_minuto(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:resend_verification"))
        self.client.post(reverse("accounts:resend_verification"))
        self.assertEqual(len(mail.outbox), 1)

    def test_reenviar_nunca_redirige_a_sitios_externos(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("accounts:resend_verification"), {"next": "https://malo.example/"})
        self.assertEqual(resp["Location"], reverse("accounts:profile"))


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        make_user("cliente", User.Role.CLIENTE)

    def intentar(self, password):
        return self.client.post(reverse("login"), {"username": "cliente", "password": password})

    def test_se_bloquea_tras_varios_intentos_fallidos_incluso_con_la_clave_correcta(self):
        for _ in range(5):
            self.assertEqual(self.intentar("mala").status_code, 200)
        self.assertEqual(self.intentar(PASSWORD).status_code, 429)

    def test_un_ingreso_correcto_reinicia_el_contador(self):
        for _ in range(3):
            self.intentar("mala")
        self.assertEqual(self.intentar(PASSWORD).status_code, 302)
        self.client.logout()
        for _ in range(3):
            self.assertEqual(self.intentar("mala").status_code, 200)

    def test_el_bloqueo_es_por_usuario(self):
        make_user("otro", User.Role.CLIENTE)
        for _ in range(5):
            self.intentar("mala")
        resp = self.client.post(reverse("login"), {"username": "otro", "password": PASSWORD})
        self.assertEqual(resp.status_code, 302)


class ContrasenaTests(TestCase):
    def test_recuperar_la_contrasena_por_correo(self):
        user = make_user("cliente", User.Role.CLIENTE)
        resp = self.client.post(reverse("accounts:password_reset"), {"email": user.email})
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

        match = re.search(r"https?://\S+(/cuentas/clave/restablecer/\S+)", mail.outbox[0].body)
        self.assertIsNotNone(match)
        resp = self.client.get(match.group(1), follow=True)
        nueva = "Otra-clave-segura-456"
        resp = self.client.post(resp.redirect_chain[-1][0], {"new_password1": nueva, "new_password2": nueva})
        self.assertRedirects(resp, reverse("accounts:password_reset_complete"))
        self.assertTrue(self.client.login(username="cliente", password=nueva))

    def test_un_correo_desconocido_no_envia_nada_ni_revela_si_existe(self):
        resp = self.client.post(reverse("accounts:password_reset"), {"email": "nadie@example.com"})
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_cambiar_la_contrasena_estando_dentro(self):
        make_user("cliente", User.Role.CLIENTE)
        self.client.login(username="cliente", password=PASSWORD)
        nueva = "Otra-clave-segura-456"
        resp = self.client.post(reverse("accounts:password_change"), {
            "old_password": PASSWORD, "new_password1": nueva, "new_password2": nueva,
        })
        self.assertRedirects(resp, reverse("accounts:password_change_done"))


class PerfilTests(TestCase):
    def setUp(self):
        self.user = make_user("cliente", User.Role.CLIENTE)
        self.client.force_login(self.user)

    def test_guarda_telefono_y_direccion(self):
        self.client.post(reverse("accounts:profile"), {
            "first_name": "Ana", "phone": "+56 9 1234 5678", "address": "Calle 1 Norte 123, Talca",
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "+56 9 1234 5678")
        self.assertEqual(self.user.address, "Calle 1 Norte 123, Talca")

    def test_rechaza_un_telefono_invalido(self):
        self.client.post(reverse("accounts:profile"), {"first_name": "Ana", "phone": "abc", "address": ""})
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "")


class AccesoTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", User.Role.ADMIN)
        self.cliente = make_user("cliente", User.Role.CLIENTE)

    def test_inicio_es_publico(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Servicios eléctricos en Talca")

    def test_paginas_legales_son_publicas(self):
        self.assertContains(self.client.get(reverse("privacy")), "Política de privacidad")
        self.assertContains(self.client.get(reverse("terms")), "Términos de uso")

    def test_cliente_no_ve_indicadores_y_ve_la_pagina_403_propia(self):
        self.client.force_login(self.cliente)
        resp = self.client.get(reverse("stats:dashboard"))
        self.assertContains(resp, "No tienes acceso a esta página", status_code=403)

    def test_pagina_404_propia(self):
        resp = self.client.get("/esta-pagina-no-existe/")
        self.assertContains(resp, "No encontramos esa página", status_code=404)

    def test_admin_ve_indicadores_aunque_no_haya_datos(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("stats:dashboard")).status_code, 200)

    def test_admin_ve_indicadores_con_tickets_cerrados(self):
        Ticket.objects.create(
            client=self.cliente, title="Falla", description="No hay luz",
            status=Ticket.Status.CERRADO, closed_at=timezone.now(),
        )
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("stats:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Tiempo medio de resolución")

    def test_activar_o_desactivar_usuarios_requiere_post(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("accounts:toggle_active", args=[self.cliente.id]))
        self.assertEqual(resp.status_code, 405)

    def test_admin_desactiva_a_un_cliente_pero_no_a_si_mismo(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:toggle_active", args=[self.cliente.id]))
        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.is_active)

        self.client.post(reverse("accounts:toggle_active", args=[self.admin.id]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_el_usuario_creado_por_el_admin_queda_con_el_correo_confirmado(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:users"), {
            "first_name": "Marta", "email": "marta@example.com", "username": "marta", "role": "MODERADOR",
            "password1": PASSWORD, "password2": PASSWORD,
        })
        self.assertTrue(User.objects.get(username="marta").email_verified)


# ---------------------------------------------------------------- defensas contra bots en el registro

class AntiBotTests(TestCase):
    DATA = {
        "first_name": "Ana", "email": "ana@example.com", "username": "ana",
        "password1": PASSWORD, "password2": PASSWORD, "accept_terms": "on",
    }

    def setUp(self):
        cache.clear()

    def antiguo(self, segundos=10):
        return signing.dumps(time.time() - segundos, salt=FORM_TS_SALT)

    def test_el_campo_senuelo_lleno_delata_a_un_bot(self):
        with override_settings(REGISTER_MIN_SECONDS=0):
            self.client.post(reverse("register"), {**self.DATA, "website": "http://spam.example"})
        self.assertEqual(User.objects.count(), 0)

    def test_un_formulario_enviado_al_instante_se_rechaza(self):
        self.client.get(reverse("register"))
        resp = self.client.post(reverse("register"), {**self.DATA, "form_ts": signing.dumps(time.time(), salt=FORM_TS_SALT)})
        self.assertContains(resp, "demasiado rápido")
        self.assertEqual(User.objects.count(), 0)

    def test_un_formulario_sin_cronometro_se_rechaza(self):
        resp = self.client.post(reverse("register"), self.DATA)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_un_formulario_enviado_con_calma_se_acepta(self):
        resp = self.client.post(reverse("register"), {**self.DATA, "form_ts": self.antiguo()})
        self.assertRedirects(resp, reverse("tickets:create"))

    def test_el_formulario_incluye_el_senuelo_y_el_cronometro_sin_mostrarlos(self):
        resp = self.client.get(reverse("register"))
        self.assertContains(resp, 'name="form_ts"')
        self.assertContains(resp, 'class="hp"')

    @override_settings(REGISTER_MIN_SECONDS=0, REGISTER_MAX_PER_HOUR=1)
    def test_hay_un_tope_de_cuentas_nuevas_por_direccion(self):
        self.client.post(reverse("register"), self.DATA)
        self.client.logout()
        otro = {**self.DATA, "email": "b@example.com", "username": "bea"}
        resp = self.client.post(reverse("register"), otro)
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(User.objects.count(), 1)

    @override_settings(REGISTER_MIN_SECONDS=0, TURNSTILE_SECRET_KEY="secreta", TURNSTILE_SITE_KEY="publica")
    def test_con_captcha_configurado_se_exige_y_se_verifica(self):
        with patch("accounts.captcha.verify", return_value=False):
            self.client.post(reverse("register"), self.DATA)
        self.assertEqual(User.objects.count(), 0)
        with patch("accounts.captcha.verify", return_value=True):
            self.client.post(reverse("register"), self.DATA)
        self.assertEqual(User.objects.count(), 1)
        self.assertContains(self.client.get(reverse("register")), "cf-turnstile")


# ---------------------------------------------------------------- verificación en dos pasos

def code_for(secret):
    return totp._code_for_step(secret, totp.current_step())


class TotpTests(SimpleTestCase):
    def test_vectores_oficiales_del_rfc_6238(self):
        import base64
        secret = base64.b32encode(b"12345678901234567890").decode()
        for segundos, esperado in {59: "94287082", 1111111109: "07081804", 1234567890: "89005924"}.items():
            self.assertEqual(totp._code_for_step(secret, segundos // 30, digits=8), esperado)

    def test_acepta_el_codigo_vigente_y_rechaza_reutilizarlo_o_inventarlo(self):
        secret = totp.generate_secret()
        step = totp.verify(secret, code_for(secret))
        self.assertIsNotNone(step)
        self.assertIsNone(totp.verify(secret, code_for(secret), last_step=step))
        self.assertIsNone(totp.verify(secret, "abc123"))
        self.assertIsNone(totp.verify(secret, ""))


class DosPasosTests(TestCase):
    def setUp(self):
        cache.clear()
        self.secret = totp.generate_secret()
        self.user = make_user("mod", User.Role.MODERADOR, totp_secret=self.secret, totp_enabled=True)

    def clave(self):
        return self.client.post(reverse("login"), {"username": "mod", "password": PASSWORD})

    def test_la_clave_sola_no_basta_para_entrar(self):
        self.assertRedirects(self.clave(), reverse("accounts:two_factor"))
        self.assertEqual(self.client.get(reverse("tickets:list")).status_code, 302)  # sigue sin sesión

    def test_con_el_codigo_correcto_se_inicia_sesion(self):
        self.clave()
        resp = self.client.post(reverse("accounts:two_factor"), {"code": code_for(self.secret)})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.get(reverse("tickets:list")).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action="LOGIN", target="mod").exists())

    def test_un_codigo_incorrecto_no_deja_entrar(self):
        self.clave()
        resp = self.client.post(reverse("accounts:two_factor"), {"code": "000000"})
        self.assertContains(resp, "no es correcto")
        self.assertEqual(self.client.get(reverse("tickets:list")).status_code, 302)

    def test_un_codigo_usado_no_sirve_otra_vez(self):
        self.clave()
        codigo = code_for(self.secret)
        self.client.post(reverse("accounts:two_factor"), {"code": codigo})
        self.client.logout()
        self.clave()
        resp = self.client.post(reverse("accounts:two_factor"), {"code": codigo})
        self.assertContains(resp, "ya fue usado")

    def test_tras_cinco_codigos_malos_se_bloquea(self):
        self.clave()
        for _ in range(5):
            self.client.post(reverse("accounts:two_factor"), {"code": "000000"})
        resp = self.client.post(reverse("accounts:two_factor"), {"code": code_for(self.secret)})
        self.assertEqual(resp.status_code, 429)

    def test_sin_haber_puesto_la_clave_no_se_puede_ver_el_segundo_paso(self):
        self.assertRedirects(self.client.get(reverse("accounts:two_factor")), reverse("login"))

    def test_activar_la_verificacion_desde_el_perfil(self):
        nuevo = make_user("admin", User.Role.ADMIN)
        self.client.force_login(nuevo)
        self.client.get(reverse("accounts:two_factor_setup"))
        secreto = self.client.session["totp_setup_secret"]
        resp = self.client.post(reverse("accounts:two_factor_setup"), {"code": code_for(secreto)})
        self.assertRedirects(resp, reverse("accounts:profile"))
        nuevo.refresh_from_db()
        self.assertTrue(nuevo.totp_enabled)
        self.assertEqual(nuevo.totp_secret, secreto)
        self.assertTrue(AuditLog.objects.filter(action="DOS_PASOS_ON").exists())

    def test_con_un_codigo_malo_no_se_activa(self):
        nuevo = make_user("admin", User.Role.ADMIN)
        self.client.force_login(nuevo)
        self.client.get(reverse("accounts:two_factor_setup"))
        self.client.post(reverse("accounts:two_factor_setup"), {"code": "000000"})
        nuevo.refresh_from_db()
        self.assertFalse(nuevo.totp_enabled)

    def test_quitar_la_verificacion_pide_la_contrasena(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:two_factor_disable"), {"password": "incorrecta"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.totp_enabled)
        self.client.post(reverse("accounts:two_factor_disable"), {"password": PASSWORD})
        self.user.refresh_from_db()
        self.assertFalse(self.user.totp_enabled)

    @override_settings(REQUIRE_2FA_STAFF=True)
    def test_si_es_obligatoria_el_personal_no_puede_quitarla(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:two_factor_disable"), {"password": PASSWORD})
        self.user.refresh_from_db()
        self.assertTrue(self.user.totp_enabled)

    @override_settings(REQUIRE_2FA_STAFF=True)
    def test_si_es_obligatoria_se_redirige_al_personal_sin_ella_pero_no_a_los_clientes(self):
        sin = make_user("mod2", User.Role.MODERADOR)
        self.client.force_login(sin)
        self.assertRedirects(self.client.get(reverse("tickets:list")), reverse("accounts:two_factor_setup"))
        self.client.force_login(make_user("cliente", User.Role.CLIENTE))
        self.assertEqual(self.client.get(reverse("tickets:list")).status_code, 200)

    def test_el_administrador_restablece_la_verificacion_de_otro(self):
        self.client.force_login(make_user("admin", User.Role.ADMIN))
        self.client.post(reverse("accounts:reset_two_factor", args=[self.user.id]))
        self.user.refresh_from_db()
        self.assertFalse(self.user.totp_enabled)
        self.assertEqual(self.user.totp_secret, "")

    def test_un_no_administrador_no_puede_restablecer(self):
        self.client.force_login(make_user("cliente", User.Role.CLIENTE))
        self.assertEqual(self.client.post(reverse("accounts:reset_two_factor", args=[self.user.id])).status_code, 403)


# ---------------------------------------------------------------- derechos del titular de los datos

def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    return buffer.getvalue()


MEDIA_ACCOUNTS = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA_ACCOUNTS)
class DerechosTests(TestCase):
    def setUp(self):
        cache.clear()
        self.mod = make_user("mod", User.Role.MODERADOR)
        self.cliente = make_user("cliente", User.Role.CLIENTE, phone="+56 9 1234 5678", address="Calle 1, Talca", first_name="Ana")
        self.otro = make_user("otro", User.Role.CLIENTE)
        self.ticket = Ticket.objects.create(
            client=self.cliente, title="Falla", description="No hay luz", phone="+56 9 1234 5678",
            address="Calle 1, Talca", image=ContentFile(png_bytes(), name="falla.png"),
        )
        Ticket.objects.create(client=self.otro, title="Ticket ajeno", description="secreto-del-otro")
        ChatMessage.objects.create(client=self.cliente, question="hola", answer="¡hola!")
        Notification.objects.create(user=self.cliente, message="aviso")
        self.client.force_login(self.cliente)

    def test_descargar_mis_datos_incluye_lo_propio_y_nada_ajeno(self):
        resp = self.client.post(reverse("accounts:export_data"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/zip")
        bundle = zipfile.ZipFile(io.BytesIO(resp.content))
        data = json.loads(bundle.read("datos.json"))
        self.assertEqual(data["perfil"]["telefono"], "+56 9 1234 5678")
        self.assertEqual([t["asunto"] for t in data["tickets"]], ["Falla"])
        self.assertEqual(len(data["conversaciones_con_el_asistente"]), 1)
        self.assertNotIn("secreto-del-otro", bundle.read("datos.json").decode())
        self.assertTrue(any(name.startswith("fotos/") for name in bundle.namelist()))
        self.assertTrue(AuditLog.objects.filter(action="DATOS_EXPORTADOS").exists())

    def test_descargar_los_datos_requiere_post_y_sesion(self):
        self.assertEqual(self.client.get(reverse("accounts:export_data")).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("accounts:export_data")).status_code, 302)

    def test_eliminar_la_cuenta_borra_los_datos_personales_y_cancela_lo_activo(self):
        ruta = self.ticket.image.path
        resp = self.client.post(reverse("accounts:delete_account"), {"password": PASSWORD, "confirm": "on"})
        self.assertRedirects(resp, reverse("home"))
        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.is_active)
        self.assertEqual(self.cliente.username, f"eliminado-{self.cliente.pk}")
        self.assertEqual((self.cliente.email, self.cliente.phone, self.cliente.address, self.cliente.first_name), ("", "", "", ""))
        self.ticket.refresh_from_db()
        self.assertEqual((self.ticket.phone, self.ticket.address, self.ticket.status), ("", "", "CANCELADO"))
        self.assertFalse(self.ticket.image)
        self.assertEqual(ChatMessage.objects.filter(client=self.cliente).count(), 0)
        self.assertEqual(Notification.objects.filter(user=self.cliente).count(), 0)
        self.assertFalse(self.client.login(username="cliente", password=PASSWORD))
        self.assertTrue(AuditLog.objects.filter(action="CUENTA_ELIMINADA").exists())
        import os
        self.assertFalse(os.path.exists(ruta))

    def test_con_la_contrasena_incorrecta_no_se_elimina(self):
        self.client.post(reverse("accounts:delete_account"), {"password": "mala", "confirm": "on"})
        self.cliente.refresh_from_db()
        self.assertTrue(self.cliente.is_active)

    def test_sin_marcar_la_confirmacion_no_se_elimina(self):
        self.client.post(reverse("accounts:delete_account"), {"password": PASSWORD})
        self.cliente.refresh_from_db()
        self.assertTrue(self.cliente.is_active)

    def test_el_personal_no_elimina_su_propia_cuenta(self):
        self.client.force_login(self.mod)
        resp = self.client.post(reverse("accounts:delete_account"), {"password": PASSWORD, "confirm": "on"})
        self.assertRedirects(resp, reverse("accounts:profile"))
        self.mod.refresh_from_db()
        self.assertTrue(self.mod.is_active)


# ---------------------------------------------------------------- auditoría

class AuditoriaTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin", User.Role.ADMIN)

    def test_crear_y_desactivar_usuarios_queda_registrado(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:users"), {
            "first_name": "Marta", "email": "marta@example.com", "username": "marta", "role": "MODERADOR",
            "password1": PASSWORD, "password2": PASSWORD,
        })
        marta = User.objects.get(username="marta")
        self.client.post(reverse("accounts:toggle_active", args=[marta.id]))
        acciones = list(AuditLog.objects.values_list("action", "target"))
        self.assertIn(("USUARIO_CREADO", "marta"), acciones)
        self.assertIn(("USUARIO_ESTADO", "marta"), acciones)
        self.assertEqual(AuditLog.objects.filter(action="USUARIO_CREADO").first().actor, self.admin)

    def test_el_bloqueo_por_intentos_fallidos_queda_registrado(self):
        make_user("cliente", User.Role.CLIENTE)
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "cliente", "password": "mala"})
        self.assertEqual(AuditLog.objects.filter(action="LOGIN_BLOQUEADO", target="cliente").count(), 1)

    def test_solo_el_administrador_ve_la_auditoria_y_se_puede_filtrar(self):
        AuditLog.objects.create(actor=self.admin, action="USUARIO_CREADO", target="a")
        AuditLog.objects.create(actor=self.admin, action="TICKET_ELIMINADO", target="b")
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("accounts:audit"))
        self.assertEqual(len(resp.context["page_obj"]), 2)
        resp = self.client.get(reverse("accounts:audit"), {"accion": "TICKET_ELIMINADO"})
        self.assertEqual(len(resp.context["page_obj"]), 1)
        self.client.force_login(make_user("cliente", User.Role.CLIENTE))
        self.assertEqual(self.client.get(reverse("accounts:audit")).status_code, 403)


class TrabajosPorSegmentoTests(SimpleTestCase):
    """Apartado "Trabajos por segmento" de la portada (accounts/works.py)."""

    def _photo(self, folder, name, size=(40, 30)):
        folder.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, "red").save(folder / name, "JPEG")

    def test_segmento_sin_fotos_no_se_muestra_salvo_el_marcado(self):
        from .works import load_segments
        with tempfile.TemporaryDirectory() as tmp:
            slugs = [s["slug"] for s in load_segments(tmp)]
        self.assertEqual(slugs, ["informes-certificaciones"])

    def test_fotos_ordenadas_con_texto_y_medidas(self):
        from pathlib import Path
        from .works import load_segments
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp) / "supermercado"
            self._photo(carpeta, "03-cielo-luminarias-estancas.jpg", (40, 60))
            self._photo(carpeta, "01-bodega-luminarias.jpg", (60, 40))
            self._photo(carpeta, "99-sin-texto.jpg")
            (carpeta / "notas.txt").write_text("no es una foto")
            seg = next(s for s in load_segments(tmp) if s["slug"] == "supermercado")
        self.assertEqual([p["path"].rsplit("/", 1)[1] for p in seg["photos"]],
                         ["01-bodega-luminarias.jpg", "03-cielo-luminarias-estancas.jpg", "99-sin-texto.jpg"])
        self.assertEqual(seg["photos"][0]["caption"], "Bodega con luminarias colgantes y bandejas portacables")
        self.assertEqual((seg["photos"][0]["width"], seg["photos"][0]["height"]), (60, 40))
        self.assertEqual(seg["photos"][2]["caption"], seg["title"])  # sin texto propio: usa el del segmento
        self.assertEqual(seg["note"], "Obra en proceso")

    def test_maximo_de_fotos_por_segmento(self):
        from pathlib import Path
        from .works import MAX_PHOTOS_PER_SEGMENT, load_segments
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(MAX_PHOTOS_PER_SEGMENT + 3):
                self._photo(Path(tmp) / "casa-habitacion", f"{i:02d}-foto.jpg")
            seg = next(s for s in load_segments(tmp) if s["slug"] == "casa-habitacion")
        self.assertEqual(len(seg["photos"]), MAX_PHOTOS_PER_SEGMENT)

    def test_foto_corrupta_no_rompe_la_portada(self):
        from pathlib import Path
        from .works import load_segments
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp) / "aire-acondicionado"
            carpeta.mkdir()
            (carpeta / "01-rota.jpg").write_bytes(b"no es una imagen")
            seg = next(s for s in load_segments(tmp) if s["slug"] == "aire-acondicionado")
        self.assertIsNone(seg["photos"][0]["width"])


class PortadaSegmentosTests(TestCase):
    def test_portada_muestra_el_apartado_y_las_fotos_incluidas(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Trabajos por segmento")
        self.assertContains(resp, "Informes y certificaciones de verificación inicial")
        self.assertContains(resp, "Subestación con transformador de 500 kVA")
        self.assertContains(resp, "img/trabajos/subestacion-500kva/01-vista-general.jpg")


# ---------- Galería de trabajos: fotos que sube el personal ----------

def make_photo(name="obra.jpg", size=(80, 60), fmt="JPEG", with_exif=False):
    """Foto de prueba lista para subir. Con with_exif lleva un dato EXIF (como los que ponen los celulares)."""
    buffer = io.BytesIO()
    options = {}
    if with_exif and fmt == "JPEG":
        exif = Image.Exif()
        exif[0x010F] = "Marca de camara"
        options["exif"] = exif
    Image.new("RGB", size, "red").save(buffer, fmt, **options)
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{fmt.lower()}")


class GaleriaTrabajosTests(TestCase):
    def setUp(self):
        cache.clear()
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        media = override_settings(MEDIA_ROOT=self._media.name)
        media.enable()
        self.addCleanup(media.disable)
        self.url = reverse("accounts:gallery")
        self.worker = make_user("trabajador1", User.Role.TRABAJADOR)

    def upload(self, user, files=None, segment="supermercado", caption="Bodega terminada"):
        self.client.force_login(user)
        files = files if files is not None else [make_photo()]
        return self.client.post(self.url, {"segment": segment, "caption": caption, "images": files})

    def test_visitantes_y_clientes_no_pueden_usar_la_galeria(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)  # al inicio de sesión
        self.client.force_login(make_user("cliente", User.Role.CLIENTE))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        resp = self.client.post(self.url, {"segment": "supermercado", "images": [make_photo()]})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(WorkPhoto.objects.count(), 0)

    def test_trabajadores_moderadores_y_administradores_suben_varias_fotos(self):
        for role in (User.Role.TRABAJADOR, User.Role.MODERADOR, User.Role.ADMIN):
            user = make_user(f"staff-{role}", role)
            resp = self.upload(user, [make_photo("a.jpg"), make_photo("b.png", fmt="PNG")])
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(WorkPhoto.objects.filter(uploaded_by=user).count(), 2)
        self.assertEqual(WorkPhoto.objects.count(), 6)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.FOTO_SUBIDA).count(), 6)
        photo = WorkPhoto.objects.first()
        self.assertEqual((photo.segment, photo.caption), ("supermercado", "Bodega terminada"))
        self.assertTrue(photo.image.storage.exists(photo.image.name))
        self.assertEqual((photo.width, photo.height), (80, 60))

    def test_la_foto_se_guarda_sin_datos_exif(self):
        self.upload(self.worker, [make_photo(with_exif=True)])
        photo = WorkPhoto.objects.get()
        with Image.open(photo.image.path) as saved:
            self.assertEqual(len(saved.getexif()), 0)

    def test_rechaza_archivos_que_no_son_fotos_validas(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        falso = SimpleUploadedFile("virus.jpg", b"esto no es una imagen", content_type="image/jpeg")
        resp = self.upload(self.worker, [falso])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "no es una foto válida")
        resp = self.upload(self.worker, [make_photo("animada.gif", fmt="GIF")])
        self.assertContains(resp, "no es una foto válida")
        self.assertEqual(WorkPhoto.objects.count(), 0)

    def test_rechaza_segmento_inexistente_sin_fotos_y_demasiadas_fotos(self):
        self.assertIn("segment", self.upload(self.worker, segment="inventado").context["form"].errors)
        self.assertContains(self.upload(self.worker, files=[]), "Elige al menos una foto")
        muchas = [make_photo(f"f{i}.jpg") for i in range(11)]
        self.assertContains(self.upload(self.worker, files=muchas), "hasta 10 fotos")
        self.assertEqual(WorkPhoto.objects.count(), 0)

    @patch("accounts.forms.MAX_WORK_PHOTO_MB", 0)
    def test_rechaza_fotos_que_pesan_demasiado(self):
        resp = self.upload(self.worker, [make_photo()])
        self.assertContains(resp, "pesa más de 0 MB")
        self.assertEqual(WorkPhoto.objects.count(), 0)

    def test_la_portada_muestra_la_foto_subida_y_cualquiera_puede_verla(self):
        self.upload(self.worker, [make_photo()], segment="casa-habitacion", caption="Living con luces nuevas")
        photo = WorkPhoto.objects.get()
        self.client.logout()
        url = reverse("accounts:work_photo", args=[photo.pk])
        home = self.client.get(reverse("home"))
        self.assertContains(home, url)
        self.assertContains(home, "Living con luces nuevas")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/jpeg")
        self.assertIn("public", resp["Cache-Control"])
        self.assertTrue(b"".join(resp.streaming_content))
        self.assertEqual(self.client.get(reverse("accounts:work_photo", args=[9999])).status_code, 404)

    def test_la_portada_ofrece_subir_fotos_solo_al_personal(self):
        self.assertNotContains(self.client.get(reverse("home")), "Agregar o quitar fotos")
        self.client.force_login(make_user("cliente", User.Role.CLIENTE))
        self.assertNotContains(self.client.get(reverse("home")), "Agregar o quitar fotos")
        self.client.force_login(self.worker)
        self.assertContains(self.client.get(reverse("home")), "Agregar o quitar fotos")

    def test_el_menu_muestra_la_galeria_al_personal_y_no_al_cliente(self):
        self.client.force_login(self.worker)
        self.assertContains(self.client.get(reverse("tickets:list")), self.url)
        self.client.force_login(make_user("cliente", User.Role.CLIENTE))
        self.assertNotContains(self.client.get(reverse("tickets:list")), self.url)

    def test_un_trabajador_solo_edita_y_elimina_sus_fotos(self):
        self.upload(self.worker, [make_photo()])
        photo = WorkPhoto.objects.get()
        edit = reverse("accounts:gallery_edit", args=[photo.pk])
        delete = reverse("accounts:gallery_delete", args=[photo.pk])

        self.client.force_login(make_user("trabajador2", User.Role.TRABAJADOR))
        self.assertEqual(self.client.post(edit, {"segment": "supermercado", "caption": "x"}).status_code, 403)
        self.assertEqual(self.client.post(delete).status_code, 403)
        self.assertEqual(WorkPhoto.objects.count(), 1)

        self.client.force_login(self.worker)
        resp = self.client.post(edit, {"segment": "aire-acondicionado", "caption": "Unidad exterior"})
        self.assertEqual(resp.status_code, 302)
        photo.refresh_from_db()
        self.assertEqual((photo.segment, photo.caption), ("aire-acondicionado", "Unidad exterior"))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.FOTO_EDITADA).exists())

        path = photo.image.path
        self.client.post(delete)
        self.assertEqual(WorkPhoto.objects.count(), 0)
        import os
        self.assertFalse(os.path.exists(path))  # también se borra el archivo
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.FOTO_ELIMINADA).exists())

    def test_moderadores_y_administradores_eliminan_fotos_de_otros(self):
        for role in (User.Role.MODERADOR, User.Role.ADMIN):
            self.upload(self.worker, [make_photo()])
            photo = WorkPhoto.objects.get()
            self.client.force_login(make_user(f"jefe-{role}", role))
            self.assertEqual(self.client.post(reverse("accounts:gallery_delete", args=[photo.pk])).status_code, 302)
            self.assertEqual(WorkPhoto.objects.count(), 0)

    def test_eliminar_exige_post_y_no_redirige_fuera_del_sitio(self):
        self.upload(self.worker, [make_photo()])
        photo = WorkPhoto.objects.get()
        delete = reverse("accounts:gallery_delete", args=[photo.pk])
        self.assertEqual(self.client.get(delete).status_code, 405)
        resp = self.client.post(delete, {"next": "https://sitio-malo.example/"})
        self.assertRedirects(resp, self.url, fetch_redirect_response=False)

    def test_la_galeria_se_filtra_por_segmento(self):
        self.upload(self.worker, [make_photo()], segment="supermercado")
        self.upload(self.worker, [make_photo()], segment="casa-habitacion")
        resp = self.client.get(self.url, {"segmento": "casa-habitacion"})
        self.assertEqual(len(resp.context["page_obj"]), 1)
        self.assertEqual(self.client.get(self.url).context["total"], 2)


class FotosSubidasEnSegmentosTests(SimpleTestCase):
    """load_segments mezcla las fotos subidas con las incluidas en static/img/trabajos."""

    def _work(self, pk, segment, caption=""):
        from types import SimpleNamespace
        return SimpleNamespace(pk=pk, segment=segment, caption=caption, width=800, height=600)

    def test_las_subidas_van_primero_con_su_texto_o_el_titulo_del_segmento(self):
        from pathlib import Path
        from .works import load_segments
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp) / "supermercado"
            carpeta.mkdir()
            Image.new("RGB", (40, 30), "red").save(carpeta / "01-incluida.jpg", "JPEG")
            seg = next(s for s in load_segments(tmp, [self._work(7, "supermercado", "Nueva bodega"),
                                                       self._work(5, "supermercado")])
                       if s["slug"] == "supermercado")
        self.assertEqual([p["uploaded"] for p in seg["photos"]], [True, True, False])
        self.assertEqual(seg["photos"][0]["caption"], "Nueva bodega")
        self.assertEqual(seg["photos"][1]["caption"], seg["title"])
        self.assertEqual(seg["photos"][0]["url"], reverse("accounts:work_photo", args=[7]))
        self.assertTrue(seg["photos"][2]["url"].endswith("img/trabajos/supermercado/01-incluida.jpg"))

    def test_un_segmento_sin_fotos_incluidas_aparece_si_tiene_subidas(self):
        from .works import load_segments
        with tempfile.TemporaryDirectory() as tmp:
            slugs = [s["slug"] for s in load_segments(tmp, [self._work(1, "casa-habitacion")])]
        self.assertEqual(slugs, ["casa-habitacion", "informes-certificaciones"])

    def test_segmento_desconocido_se_ignora_y_hay_un_maximo_de_subidas(self):
        from .works import MAX_UPLOADED_PER_SEGMENT, load_segments
        works = [self._work(i, "supermercado") for i in range(MAX_UPLOADED_PER_SEGMENT + 5)]
        works.append(self._work(999, "ya-no-existe"))
        with tempfile.TemporaryDirectory() as tmp:
            segments = load_segments(tmp, works)
        self.assertEqual([s["slug"] for s in segments], ["supermercado", "informes-certificaciones"])
        self.assertEqual(len(segments[0]["photos"]), MAX_UPLOADED_PER_SEGMENT)

    def test_la_portada_usa_solo_fotos_incluidas(self):
        from .works import hero_photos
        segments = [
            {"title": "A", "photos": [{"uploaded": True, "url": "/u/1"}, {"uploaded": False, "url": "/s/1"}]},
            {"title": "B", "photos": [{"uploaded": True, "url": "/u/2"}]},
            {"title": "C", "photos": [{"uploaded": False, "url": "/s/3"}]},
        ]
        self.assertEqual([p["url"] for p in hero_photos(segments)], ["/s/1", "/s/3"])
