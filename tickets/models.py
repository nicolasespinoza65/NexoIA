import re
from urllib.parse import quote_plus

from django.conf import settings
from django.db import models
from django.utils import timezone


class Ticket(models.Model):
    """Solicitud/consulta/reclamo. Nace del cliente directamente o del asistente IA (source)."""

    class Status(models.TextChoices):
        ABIERTO = "ABIERTO", "Abierto"
        ASIGNADO = "ASIGNADO", "Asignado"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        CERRADO = "CERRADO", "Cerrado"
        CANCELADO = "CANCELADO", "Cancelado"

    class Priority(models.TextChoices):
        ALTA = "ALTA", "Alta"
        MEDIA = "MEDIA", "Media"
        BAJA = "BAJA", "Baja"

    class Source(models.TextChoices):
        IA = "IA", "Asistente IA"
        CLIENTE = "CLIENTE", "Cliente"

    class Category(models.TextChoices):
        """Catálogo de tipos de solicitud. Permite a moderadores y administradores
        filtrar, ordenar el trabajo y medir qué piden más los clientes."""
        INSTALACION = "INSTALACION", "Instalación eléctrica"
        MANTENCION = "MANTENCION", "Mantención o reparación"
        COTIZACION = "COTIZACION", "Cotización"
        EMERGENCIA = "EMERGENCIA", "Emergencia"
        RECLAMO = "RECLAMO", "Reclamo"
        CONSULTA = "CONSULTA", "Consulta general"
        OTRO = "OTRO", "Otro"

    title = models.CharField(max_length=120)
    description = models.TextField(max_length=2000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ABIERTO)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIA)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.CLIENTE)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTRO)

    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tickets_as_client")
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets_as_worker")

    image = models.ImageField(upload_to="tickets/%Y/%m/", blank=True)  # foto opcional de la falla

    # Dónde y cómo contactar al cliente para este trabajo
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=200, blank=True)

    # Encuesta de satisfacción: el cliente califica (1 a 5) cuando el ticket se cierra
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    rating_comment = models.CharField(max_length=300, blank=True)

    # Trabajo en terreno: nota que deja el trabajador al cerrar y visita agendada
    closing_note = models.CharField(max_length=500, blank=True)
    visit_at = models.DateTimeField(null=True, blank=True)
    visit_note = models.CharField(max_length=200, blank=True)
    visit_reminded = models.BooleanField(default=False)  # ya se envió el recordatorio de esta visita

    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)  # se llena al cerrar; sirve para medir tiempos

    def __str__(self):
        return f"#{self.id} {self.title}"

    @property
    def maps_url(self):
        """Enlace para abrir la dirección del trabajo en Google Maps."""
        if not self.address:
            return ""
        return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(self.address)

    @property
    def whatsapp_number(self):
        """Teléfono del cliente en el formato que pide WhatsApp (solo dígitos, con código de país)."""
        digits = re.sub(r"\D", "", self.phone)
        if len(digits) == 9 and digits.startswith("9"):  # celular chileno escrito sin el código de país
            digits = "56" + digits
        return digits if len(digits) >= 10 else ""


class TicketComment(models.Model):
    """Comentario de seguimiento dentro de un ticket."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class TicketEvent(models.Model):
    """Historial del ticket: quién hizo qué y cuándo (trazabilidad)."""

    class Kind(models.TextChoices):
        CREADO = "CREADO", "Creado"
        ASIGNADO = "ASIGNADO", "Asignado"
        ESTADO = "ESTADO", "Cambio de estado"
        CATEGORIA = "CATEGORIA", "Cambio de categoría"
        REABIERTO = "REABIERTO", "Reabierto"
        CANCELADO = "CANCELADO", "Cancelado"
        CALIFICADO = "CALIFICADO", "Calificado"
        COTIZACION = "COTIZACION", "Cotización enviada"
        RESPUESTA = "RESPUESTA", "Cotización respondida"
        VISITA = "VISITA", "Visita agendada"
        PRIORIDAD = "PRIORIDAD", "Cambio de prioridad"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    detail = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class Quote(models.Model):
    """Cotización formal que el moderador envía dentro del ticket y que el cliente acepta o rechaza."""

    class Status(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente de respuesta"
        ACEPTADA = "ACEPTADA", "Aceptada"
        RECHAZADA = "RECHAZADA", "Rechazada"
        REEMPLAZADA = "REEMPLAZADA", "Reemplazada por otra"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="quotes")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    detail = models.TextField(max_length=1500)  # qué incluye el trabajo
    amount = models.PositiveIntegerField()  # en pesos chilenos
    valid_until = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDIENTE)
    response_comment = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    @property
    def amount_display(self):
        return "$" + f"{self.amount:,}".replace(",", ".")

    @property
    def is_expired(self):
        return self.status == self.Status.PENDIENTE and self.valid_until < timezone.localdate()


class TicketPhoto(models.Model):
    """Foto del trabajo realizado, que sube el trabajador desde terreno."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="photos")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    image = models.ImageField(upload_to="tickets/work/%Y/%m/")
    caption = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
