"""
Capa de servicio del módulo Tickets: toda la lógica de negocio vive aquí,
para que las vistas (tickets/views.py) y el chatbot solo la invoquen.
"""
import unicodedata

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from notifications.models import Notification
from notifications.services import notify_user, notify_role
from . import images
from .models import Quote, Ticket, TicketComment, TicketEvent, TicketPhoto

# Palabras clave para clasificar solos los tickets que nacen del asistente IA
# (el cliente que crea un ticket a mano elige la categoría en el formulario).
# Se revisan en este orden: lo más urgente primero. Si nada calza, queda "Consulta general".
# Es una heurística simple: moderador y administrador pueden corregir la categoría en el detalle.
_CATEGORY_KEYWORDS = (
    (Ticket.Category.EMERGENCIA, ("emergencia", "urgente", "urgencia", "chispa", "cortocircuito", "corto circuito", "sin luz", "humo", "incendio", "descarga")),
    (Ticket.Category.RECLAMO, ("reclamo", "queja", "mal servicio", "insatisfech", "garantia")),
    (Ticket.Category.COTIZACION, ("cotiz", "presupuesto", "precio", "cuanto cuesta", "cuanto sale", "cuanto cobran")),
    (Ticket.Category.INSTALACION, ("instal", "empalme", "tendido", "ampliacion", "proyecto", "tablero nuevo")),
    (Ticket.Category.MANTENCION, ("manten", "repar", "arregl", "falla", "revision", "enchufe", "automatico", "diferencial", "tablero")),
)

ACTIVE_STATUSES = (Ticket.Status.ABIERTO, Ticket.Status.ASIGNADO, Ticket.Status.EN_PROCESO)
FINISHED_STATUSES = (Ticket.Status.CERRADO, Ticket.Status.CANCELADO)


def _normalize(text):
    """Minúsculas y sin tildes, para comparar palabras clave."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def guess_category(text):
    normalized = _normalize(text)
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(k in normalized for k in keywords):
            return category
    return Ticket.Category.CONSULTA


def _link(ticket):
    return reverse("tickets:detail", args=[ticket.id])


def _name(user):
    return user.get_full_name() or user.username


def _log(ticket, actor, kind, detail=""):
    """Deja constancia en el historial del ticket de quién hizo qué."""
    TicketEvent.objects.create(ticket=ticket, actor=actor, kind=kind, detail=detail[:255])


def _require_client_or_staff(user):
    """Cancelar o reabrir lo pueden hacer el cliente dueño, el moderador y el administrador."""
    if user.role not in (User.Role.CLIENTE, User.Role.MODERADOR, User.Role.ADMIN):
        raise PermissionDenied("No tienes permiso para esta acción")


def _notify_team(ticket, actor, message):
    """Avisa al trabajador asignado (o a los moderadores si aún no hay) y, si actúa el personal, al cliente."""
    if ticket.worker and ticket.worker_id != actor.id:
        notify_user(ticket.worker, message, link=_link(ticket))
    elif not ticket.worker:
        notify_role(User.Role.MODERADOR, message, link=_link(ticket))
    if actor.id != ticket.client_id:
        notify_user(ticket.client, message, link=_link(ticket))


def create_ticket(client, title, description, source=Ticket.Source.CLIENTE, category=None, image=None,
                  phone="", address=""):
    if category not in Ticket.Category.values:
        category = guess_category(f"{title} {description}")
    extra = {}
    if image:
        try:
            extra["image"] = images.sanitize(image)  # sin GPS ni otros metadatos
        except ValueError as error:
            raise ValidationError(str(error))
    # Los tickets del asistente no piden teléfono ni dirección: se usan los del perfil del cliente
    phone = phone or client.phone
    address = address or client.address
    # Las emergencias entran con prioridad alta; el moderador puede cambiarla al asignar
    priority = Ticket.Priority.ALTA if category == Ticket.Category.EMERGENCIA else Ticket.Priority.MEDIA
    ticket = Ticket.objects.create(
        client=client, title=title, description=description, source=source,
        category=category, priority=priority, phone=phone, address=address, **extra,
    )
    _log(ticket, client, TicketEvent.Kind.CREADO, f"Origen: {ticket.get_source_display()}. Categoría: {ticket.get_category_display()}")
    # Moderadores (que asignan) y administradores (que supervisan) se enteran de cada ticket nuevo
    urgent = "[URGENTE] " if priority == Ticket.Priority.ALTA else ""
    message = f"{urgent}Nuevo ticket #{ticket.id} ({ticket.get_category_display()}): {title}"
    notify_role(User.Role.MODERADOR, message, link=_link(ticket))
    notify_role(User.Role.ADMIN, message, link=_link(ticket))
    return ticket


def remember_contact(user, phone, address):
    """Guarda en el perfil el teléfono y la dirección si todavía no los tenía, para no pedirlos de nuevo."""
    changed = []
    if phone and not user.phone:
        user.phone = phone
        changed.append("phone")
    if address and not user.address:
        user.address = address
        changed.append("address")
    if changed:
        user.save(update_fields=changed)


def list_for(user, category=None, status=None, search=None):
    """Cliente: sus tickets. Trabajador: los asignados a él. Moderador/Admin: todos.
    Opcionalmente filtra por categoría, estado y texto (valores inválidos se ignoran)."""
    if user.role == User.Role.CLIENTE:
        tickets = Ticket.objects.filter(client=user)
    elif user.role == User.Role.TRABAJADOR:
        tickets = Ticket.objects.filter(worker=user)
    else:
        tickets = Ticket.objects.all()
    if category in Ticket.Category.values:
        tickets = tickets.filter(category=category)
    if status in Ticket.Status.values:
        tickets = tickets.filter(status=status)
    if search:
        query = (
            Q(title__icontains=search) | Q(description__icontains=search)
            | Q(client__username__icontains=search) | Q(client__first_name__icontains=search)
            | Q(address__icontains=search)
        )
        if search.isdigit():
            query |= Q(pk=int(search))
        tickets = tickets.filter(query)
    return tickets.select_related("client", "worker").order_by("-id")


def get_allowed(user, ticket_id):
    try:
        ticket = Ticket.objects.select_related("client", "worker").get(pk=ticket_id)
    except Ticket.DoesNotExist:
        raise Http404("Ticket no encontrado")
    allowed = {
        User.Role.CLIENTE: ticket.client_id == user.id,
        User.Role.TRABAJADOR: ticket.worker_id == user.id,
    }.get(user.role, True)
    if not allowed:
        raise PermissionDenied("No tienes acceso a este ticket")
    return ticket


def set_category(ticket_id, category, actor=None):
    """Corrige la categoría de un ticket (usado por moderador/administrador)."""
    if category not in Ticket.Category.values:
        raise ValidationError("Categoría inválida")
    try:
        ticket = Ticket.objects.get(pk=ticket_id)
    except Ticket.DoesNotExist:
        raise Http404("Ticket no encontrado")
    previous = ticket.get_category_display()
    ticket.category = category
    ticket.save(update_fields=["category"])
    _log(ticket, actor, TicketEvent.Kind.CATEGORIA, f"De «{previous}» a «{ticket.get_category_display()}»")
    return ticket


def assign(ticket_id, worker_id, priority, actor=None):
    """Asigna o reasigna un ticket a un trabajador. Un ticket cerrado o cancelado no se puede asignar."""
    try:
        ticket = Ticket.objects.select_related("worker", "client").get(pk=ticket_id)
    except Ticket.DoesNotExist:
        raise Http404("Ticket no encontrado")
    if ticket.status in FINISHED_STATUSES:
        raise ValidationError("No se puede asignar un ticket cerrado o cancelado")
    worker = User.objects.filter(pk=worker_id, role=User.Role.TRABAJADOR, is_active=True).first()
    if not worker:
        raise ValidationError("Trabajador inválido")

    previous_worker = ticket.worker
    changed_worker = previous_worker is None or previous_worker.id != worker.id
    ticket.worker = worker
    ticket.priority = priority
    if changed_worker or ticket.status == Ticket.Status.ABIERTO:
        ticket.status = Ticket.Status.ASIGNADO  # si solo cambia la prioridad, se respeta el avance (p. ej. "En proceso")
    ticket.save()

    detail = f"{'Reasignado' if previous_worker else 'Asignado'} a {_name(worker)} (prioridad {ticket.get_priority_display().lower()})"
    _log(ticket, actor, TicketEvent.Kind.ASIGNADO, detail)
    if changed_worker:
        notify_user(worker, f"Se te asignó el ticket #{ticket.id}", link=_link(ticket))
        if previous_worker:
            notify_user(previous_worker, f"El ticket #{ticket.id} fue reasignado a otro trabajador", link=_link(ticket))
        notify_user(ticket.client, f"Tu ticket #{ticket.id} fue asignado a un trabajador", link=_link(ticket))
    return ticket


def change_status(worker, ticket_id, status, note=""):
    ticket = get_allowed(worker, ticket_id)
    if status not in (Ticket.Status.EN_PROCESO, Ticket.Status.CERRADO):
        raise ValidationError("Estado no permitido")
    if ticket.status in FINISHED_STATUSES:
        raise ValidationError("El ticket ya está cerrado o cancelado")
    ticket.status = status
    # La fecha de cierre permite medir cuánto demora en promedio resolver un ticket
    ticket.closed_at = timezone.now() if status == Ticket.Status.CERRADO else None
    if status == Ticket.Status.CERRADO:
        ticket.closing_note = note.strip()[:500]  # lo que el cliente lee al revisar su ticket cerrado
    ticket.save()
    _log(ticket, worker, TicketEvent.Kind.ESTADO, f"Pasó a «{ticket.get_status_display()}»")
    notify_user(ticket.client, f"Tu ticket #{ticket.id} ahora está: {ticket.get_status_display()}", link=_link(ticket))
    return ticket


def cancel_ticket(user, ticket_id):
    """El cliente (o el personal) cancela un ticket que ya no se necesita."""
    _require_client_or_staff(user)
    ticket = get_allowed(user, ticket_id)
    if ticket.status in FINISHED_STATUSES:
        raise ValidationError("El ticket ya está cerrado o cancelado")
    ticket.status = Ticket.Status.CANCELADO
    ticket.closed_at = None
    ticket.save()
    _log(ticket, user, TicketEvent.Kind.CANCELADO, f"Cancelado por {_name(user)}")
    _notify_team(ticket, user, f"El ticket #{ticket.id} fue cancelado")
    return ticket


def reopen_ticket(user, ticket_id):
    """Reabre un ticket cerrado o cancelado: vuelve a Asignado si tiene trabajador, o a Abierto si no."""
    _require_client_or_staff(user)
    ticket = get_allowed(user, ticket_id)
    if ticket.status not in FINISHED_STATUSES:
        raise ValidationError("Solo se pueden reabrir tickets cerrados o cancelados")
    ticket.status = Ticket.Status.ASIGNADO if ticket.worker else Ticket.Status.ABIERTO
    ticket.closed_at = None
    ticket.rating = None  # podrá calificar de nuevo cuando vuelva a cerrarse
    ticket.rating_comment = ""
    ticket.save()
    _log(ticket, user, TicketEvent.Kind.REABIERTO, f"Reabierto por {_name(user)}")
    _notify_team(ticket, user, f"El ticket #{ticket.id} fue reabierto")
    return ticket


def rate_ticket(user, ticket_id, rating, comment=""):
    """Encuesta de satisfacción: solo el cliente dueño, una vez, cuando el ticket está cerrado."""
    ticket = get_allowed(user, ticket_id)
    if user.role != User.Role.CLIENTE:
        raise PermissionDenied("Solo el cliente puede calificar")
    if ticket.status != Ticket.Status.CERRADO:
        raise ValidationError("Solo se puede calificar un ticket cerrado")
    if ticket.rating is not None:
        raise ValidationError("Ya calificaste este ticket")
    if rating not in range(1, 6):
        raise ValidationError("La calificación debe ser de 1 a 5")
    ticket.rating = rating
    ticket.rating_comment = comment.strip()[:300]
    ticket.save(update_fields=["rating", "rating_comment"])
    _log(ticket, user, TicketEvent.Kind.CALIFICADO, f"{rating} de 5")
    if ticket.worker:
        notify_user(ticket.worker, f"Tu trabajo en el ticket #{ticket.id} fue calificado con {rating} de 5", link=_link(ticket))
    return ticket


def add_comment(author, ticket_id, text):
    ticket = get_allowed(author, ticket_id)
    comment = TicketComment.objects.create(ticket=ticket, author=author, text=text)
    message = f"Nuevo comentario en el ticket #{ticket.id}"
    if author.role == User.Role.CLIENTE:
        # Si todavía no tiene trabajador, el aviso va a los moderadores para que no pase desapercibido
        if ticket.worker:
            notify_user(ticket.worker, message, link=_link(ticket))
        else:
            notify_role(User.Role.MODERADOR, message, link=_link(ticket))
    else:
        notify_user(ticket.client, message, link=_link(ticket))
    return comment


def delete_ticket(ticket_id):
    """Elimina un ticket con sus comentarios, cotizaciones, fotos y notificaciones (y las fotos también del disco).
    Solo lo usa el administrador. Devuelve el asunto para dejarlo en el registro de auditoría."""
    try:
        ticket = Ticket.objects.get(pk=ticket_id)
    except Ticket.DoesNotExist:
        raise Http404("Ticket no encontrado")
    title = ticket.title
    files = [ticket.image] + [photo.image for photo in ticket.photos.all()]
    link = _link(ticket)
    ticket.delete()
    # Las notificaciones de ese ticket quedarían apuntando a una página que ya no existe: se eliminan también.
    Notification.objects.filter(link=link).delete()
    for stored in files:
        if stored:
            stored.delete(save=False)  # los archivos no se borran solos al borrar el registro
    return title


def set_priority(ticket_id, priority, actor=None):
    """Cambia la prioridad de un ticket (moderador/administrador)."""
    if priority not in Ticket.Priority.values:
        raise ValidationError("Prioridad inválida")
    try:
        ticket = Ticket.objects.get(pk=ticket_id)
    except Ticket.DoesNotExist:
        raise Http404("Ticket no encontrado")
    previous = ticket.get_priority_display()
    ticket.priority = priority
    ticket.save(update_fields=["priority"])
    _log(ticket, actor, TicketEvent.Kind.PRIORIDAD, f"De «{previous}» a «{ticket.get_priority_display()}»")
    return ticket


def _require_moderation(user):
    if user.role not in (User.Role.MODERADOR, User.Role.ADMIN):
        raise PermissionDenied("Solo moderadores y administradores pueden hacer esto")


# ---------------------------------------------------------------- cotizaciones formales

def create_quote(user, ticket_id, detail, amount, valid_until):
    """El moderador envía una cotización dentro del ticket. Una nueva reemplaza a la que estaba pendiente."""
    _require_moderation(user)
    ticket = get_allowed(user, ticket_id)
    if ticket.status not in ACTIVE_STATUSES:
        raise ValidationError("Solo se puede cotizar un ticket en curso")
    if amount < 1:
        raise ValidationError("El monto debe ser mayor que cero")
    if valid_until < timezone.localdate():
        raise ValidationError("La fecha de vigencia ya pasó")
    ticket.quotes.filter(status=Quote.Status.PENDIENTE).update(status=Quote.Status.REEMPLAZADA)
    quote = Quote.objects.create(ticket=ticket, created_by=user, detail=detail, amount=amount, valid_until=valid_until)
    # El historial lo ve también el trabajador, que no debe ver los montos: aquí no se anotan
    _log(ticket, user, TicketEvent.Kind.COTIZACION, f"Vigente hasta el {valid_until:%d/%m/%Y}")
    notify_user(ticket.client, f"Tienes una cotización de {quote.amount_display} para revisar en el ticket #{ticket.id}", link=_link(ticket))
    return quote


def respond_quote(user, ticket_id, quote_id, accept, comment=""):
    """El cliente acepta o rechaza una cotización pendiente y vigente."""
    ticket = get_allowed(user, ticket_id)
    if user.role != User.Role.CLIENTE:
        raise PermissionDenied("Solo el cliente responde las cotizaciones")
    try:
        quote = ticket.quotes.get(pk=quote_id)
    except Quote.DoesNotExist:
        raise Http404("Cotización no encontrada")
    if quote.status != Quote.Status.PENDIENTE:
        raise ValidationError("Esta cotización ya fue respondida o reemplazada")
    if quote.is_expired:
        raise ValidationError("La cotización venció. Pide una nueva al equipo.")
    quote.status = Quote.Status.ACEPTADA if accept else Quote.Status.RECHAZADA
    quote.response_comment = comment.strip()[:300]
    quote.responded_at = timezone.now()
    quote.save()
    verb = "aceptó" if accept else "rechazó"
    _log(ticket, user, TicketEvent.Kind.RESPUESTA, f"El cliente {verb} la cotización")
    notify_role(User.Role.MODERADOR, f"El cliente {verb} la cotización de {quote.amount_display} en el ticket #{ticket.id}", link=_link(ticket))
    if ticket.worker:  # el trabajador se entera, pero sin el monto
        notify_user(ticket.worker, f"El cliente {verb} la cotización en el ticket #{ticket.id}", link=_link(ticket))
    return quote


# ---------------------------------------------------------------- agenda de visitas

def schedule_visit(user, ticket_id, visit_at, note=""):
    """El moderador agenda (o reprograma) la visita; cliente y trabajador reciben aviso."""
    _require_moderation(user)
    ticket = get_allowed(user, ticket_id)
    if ticket.status not in ACTIVE_STATUSES:
        raise ValidationError("Solo se puede agendar la visita de un ticket en curso")
    if visit_at <= timezone.now():
        raise ValidationError("La visita debe ser en el futuro")
    ticket.visit_at = visit_at
    ticket.visit_note = note.strip()[:200]
    ticket.visit_reminded = False  # la nueva fecha volverá a recordarse
    ticket.save(update_fields=["visit_at", "visit_note", "visit_reminded"])
    when = timezone.localtime(visit_at).strftime("%d/%m/%Y %H:%M")
    _log(ticket, user, TicketEvent.Kind.VISITA, f"Visita el {when}")
    message = f"Visita agendada para el {when} en el ticket #{ticket.id}"
    notify_user(ticket.client, message, link=_link(ticket))
    if ticket.worker:
        notify_user(ticket.worker, message, link=_link(ticket))
    return ticket


# ---------------------------------------------------------------- fotos del trabajo (terreno)

def add_work_photo(user, ticket_id, image, caption=""):
    """El trabajador asignado (o el personal) sube una foto del trabajo; el cliente la ve en su ticket."""
    ticket = get_allowed(user, ticket_id)
    if user.role not in (User.Role.TRABAJADOR, User.Role.MODERADOR, User.Role.ADMIN):
        raise PermissionDenied("Solo el equipo puede subir fotos del trabajo")
    if ticket.status == Ticket.Status.CANCELADO:
        raise ValidationError("El ticket está cancelado")
    try:
        clean = images.sanitize(image)
    except ValueError as error:
        raise ValidationError(str(error))
    photo = TicketPhoto.objects.create(ticket=ticket, uploaded_by=user, image=clean, caption=caption.strip()[:200])
    notify_user(ticket.client, f"Se agregó una foto del trabajo en el ticket #{ticket.id}", link=_link(ticket))
    return photo
