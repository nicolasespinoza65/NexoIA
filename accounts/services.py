"""Verificación del correo electrónico con un enlace firmado (sin guardar tokens en la base de datos)."""
import json
import zipfile
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.files.images import get_image_dimensions
from django.urls import reverse
from django.utils import timezone
from notifications.services import send_email

SALT = "verify-email"
MAX_AGE_SECONDS = 3 * 24 * 3600  # el enlace vence en 3 días


def make_token(user):
    # El correo va dentro de la firma: si el usuario cambia de correo, el enlace antiguo deja de servir.
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=SALT)


def read_token(token):
    """Devuelve los datos del token o lanza signing.BadSignature (incluye SignatureExpired)."""
    return signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)


def send_verification(user):
    link = settings.SITE_URL.rstrip("/") + reverse("accounts:verify", args=[make_token(user)])
    body = (
        f"Hola {user.get_full_name() or user.username},\n\n"
        f"Confirma tu correo electrónico para usar todas las funciones de la plataforma:\n{link}\n\n"
        "El enlace vence en 3 días. Si no creaste esta cuenta, ignora este mensaje.\n\n"
        "Soluciones SSDP Servicios Integrales SpA"
    )
    send_email(user.email, "Soluciones SSDP: confirma tu correo", body)


# ---------------------------------------------------------------- derechos del titular de los datos

def _iso(value):
    return value.isoformat() if value else None


def _add_file(bundle, field_file, arcname):
    """Agrega una foto al zip; si el archivo ya no existe en el disco, se omite."""
    try:
        with field_file.open("rb") as handle:
            bundle.writestr(arcname, handle.read())
    except (FileNotFoundError, ValueError):
        pass


def export_user_data(user):
    """Zip con todos los datos personales de la cuenta (datos.json) y las fotos de sus tickets."""
    from chatbot.models import ChatMessage
    from notifications.models import Notification
    from tickets.models import Ticket, TicketComment

    tickets = list(Ticket.objects.filter(client=user).prefetch_related("quotes", "photos", "events"))
    data = {
        "generado": _iso(timezone.now()),
        "perfil": {
            "usuario": user.username, "nombre": user.first_name, "apellido": user.last_name, "correo": user.email,
            "rol": user.get_role_display(), "telefono": user.phone, "direccion": user.address,
            "correo_confirmado": user.email_verified, "verificacion_en_dos_pasos": user.totp_enabled,
            "registrado": _iso(user.date_joined),
        },
        "tickets": [{
            "numero": t.id, "asunto": t.title, "descripcion": t.description, "categoria": t.get_category_display(),
            "estado": t.get_status_display(), "prioridad": t.get_priority_display(), "telefono": t.phone,
            "direccion": t.address, "creado": _iso(t.created_at), "cerrado": _iso(t.closed_at),
            "visita": _iso(t.visit_at), "nota_de_cierre": t.closing_note,
            "calificacion": t.rating, "comentario_de_calificacion": t.rating_comment,
            "cotizaciones": [{"detalle": q.detail, "monto": q.amount, "vigente_hasta": _iso(q.valid_until),
                              "estado": q.get_status_display(), "creada": _iso(q.created_at)} for q in t.quotes.all()],
            "historial": [{"fecha": _iso(e.created_at), "tipo": e.get_kind_display(), "detalle": e.detail} for e in t.events.all()],
        } for t in tickets],
        "comentarios": [{"ticket": c.ticket_id, "texto": c.text, "fecha": _iso(c.created_at)}
                        for c in TicketComment.objects.filter(author=user)],
        "conversaciones_con_el_asistente": [{"pregunta": m.question, "respuesta": m.answer, "fecha": _iso(m.created_at)}
                                            for m in ChatMessage.objects.filter(client=user)],
        "notificaciones": [{"mensaje": n.message, "fecha": _iso(n.created_at)} for n in Notification.objects.filter(user=user)],
    }
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("datos.json", json.dumps(data, ensure_ascii=False, indent=2))
        for ticket in tickets:
            if ticket.image:
                _add_file(bundle, ticket.image, f"fotos/ticket-{ticket.id}/{Path(ticket.image.name).name}")
            for photo in ticket.photos.all():
                _add_file(bundle, photo.image, f"fotos/ticket-{ticket.id}/trabajo-{Path(photo.image.name).name}")
    return buffer.getvalue()


def anonymize_user(user):
    """Elimina la cuenta de un cliente sin romper el historial de la empresa: se borran sus datos personales,
    sus conversaciones, notificaciones y fotos; sus tickets activos se cancelan; el contenido de las solicitudes
    se conserva sin teléfono ni dirección y sin vínculo con su identidad."""
    from chatbot.models import ChatMessage
    from django.core.exceptions import ValidationError
    from notifications.models import Notification
    from tickets import services as ticket_services
    from tickets.models import Ticket

    for ticket in Ticket.objects.filter(client=user, status__in=ticket_services.ACTIVE_STATUSES):
        try:
            ticket_services.cancel_ticket(user, ticket.id)
        except ValidationError:
            pass
    for ticket in Ticket.objects.filter(client=user):
        if ticket.image:
            ticket.image.delete(save=False)
        for photo in ticket.photos.all():
            photo.image.delete(save=False)
            photo.delete()
        ticket.image = ""
        ticket.phone = ""
        ticket.address = ""
        ticket.save(update_fields=["image", "phone", "address"])
    ChatMessage.objects.filter(client=user).delete()
    Notification.objects.filter(user=user).delete()

    user.username = f"eliminado-{user.pk}"
    user.first_name = ""
    user.last_name = ""
    user.email = ""
    user.phone = ""
    user.address = ""
    user.email_verified = False
    user.totp_secret = ""
    user.totp_enabled = False
    user.is_active = False
    user.set_unusable_password()
    user.save()


# ---------- Galería de trabajos ----------

MANAGER_ROLES = ("ADMIN", "MODERADOR")  # pueden editar y borrar cualquier foto; un trabajador, solo las suyas


def add_work_photos(user, segment, caption, files):
    """Guarda las fotos (ya limpiadas por el formulario) en el segmento indicado y devuelve las ``WorkPhoto``."""
    from .models import WorkPhoto
    created = []
    for file in files:
        width, height = get_image_dimensions(file) or (None, None)
        file.seek(0)
        created.append(WorkPhoto.objects.create(
            segment=segment, caption=caption, image=file, width=width, height=height, uploaded_by=user,
        ))
    return created


def can_manage_work_photo(user, photo):
    return user.role in MANAGER_ROLES or (photo.uploaded_by_id is not None and photo.uploaded_by_id == user.pk)


def delete_work_photo(photo):
    """Borra la foto y su archivo del disco."""
    photo.image.delete(save=False)
    photo.delete()
