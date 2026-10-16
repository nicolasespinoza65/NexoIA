from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Usuario del sistema. El rol determina qué panel y qué acciones están disponibles."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        MODERADOR = "MODERADOR", "Moderador"
        TRABAJADOR = "TRABAJADOR", "Trabajador"
        CLIENTE = "CLIENTE", "Cliente"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CLIENTE)
    # Datos de contacto: el equipo los necesita para coordinar la visita. Se piden al crear el primer ticket.
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=200, blank=True)
    # Un correo verificado evita cuentas con direcciones falsas; sin verificar no se puede usar el asistente con IA.
    email_verified = models.BooleanField(default=False)
    # Verificación en dos pasos (aplicación autenticadora). totp_last_step evita reutilizar un mismo código.
    totp_secret = models.CharField(max_length=64, blank=True)
    totp_enabled = models.BooleanField(default=False)
    totp_last_step = models.BigIntegerField(default=0)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"


class AuditLog(models.Model):
    """Registro de auditoría: quién hizo una acción importante, cuándo y desde qué dirección."""

    class Action(models.TextChoices):
        LOGIN = "LOGIN", "Inicio de sesión del personal"
        LOGIN_BLOQUEADO = "LOGIN_BLOQUEADO", "Cuenta bloqueada por intentos fallidos"
        USUARIO_CREADO = "USUARIO_CREADO", "Usuario creado"
        USUARIO_ESTADO = "USUARIO_ESTADO", "Usuario activado o desactivado"
        DOS_PASOS_ON = "DOS_PASOS_ON", "Verificación en dos pasos activada"
        DOS_PASOS_OFF = "DOS_PASOS_OFF", "Verificación en dos pasos quitada"
        TICKET_ELIMINADO = "TICKET_ELIMINADO", "Ticket eliminado"
        RESPUESTA_CREADA = "RESPUESTA_CREADA", "Respuesta del asistente creada"
        RESPUESTA_EDITADA = "RESPUESTA_EDITADA", "Respuesta del asistente editada"
        RESPUESTA_ELIMINADA = "RESPUESTA_ELIMINADA", "Respuesta del asistente eliminada"
        DATOS_EXPORTADOS = "DATOS_EXPORTADOS", "Datos personales descargados"
        CUENTA_ELIMINADA = "CUENTA_ELIMINADA", "Cuenta eliminada por su dueño"
        FOTO_SUBIDA = "FOTO_SUBIDA", "Foto de trabajos subida"
        FOTO_EDITADA = "FOTO_EDITADA", "Foto de trabajos editada"
        FOTO_ELIMINADA = "FOTO_ELIMINADA", "Foto de trabajos eliminada"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=30, choices=Action.choices)
    target = models.CharField(max_length=120, blank=True)
    detail = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


class WorkPhoto(models.Model):
    """Foto de un trabajo realizado que sube el personal (trabajadores, moderadores y administradores).

    Se muestra en la portada, dentro del segmento elegido, junto con las fotos que ya vienen incluidas en
    ``static/img/trabajos/``. A diferencia de las fotos de los tickets, estas son públicas: las ve cualquier
    visitante (vista ``accounts.views.work_photo``).
    """

    segment = models.CharField(max_length=60)  # slug de un segmento de accounts/works.py
    image = models.ImageField(upload_to="trabajos/%Y/%m/")
    width = models.PositiveIntegerField(null=True, blank=True)  # el navegador reserva el espacio antes de cargarla
    height = models.PositiveIntegerField(null=True, blank=True)
    caption = models.CharField(max_length=200, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"Foto #{self.pk} ({self.segment})"

    @property
    def orient(self):
        from .works import photo_orientation
        return photo_orientation(self.width, self.height)
