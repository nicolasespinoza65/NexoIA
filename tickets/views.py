"""
Vistas del módulo Tickets. Son deliberadamente "delgadas": no contienen lógica de
negocio, solo reciben la petición HTTP, llaman a services.py (que es quien de
verdad crea/asigna/cierra tickets y dispara notificaciones) y renderizan el resultado.
"""
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts import audit, throttle
from accounts.decorators import role_required
from accounts.models import AuditLog, User
from . import ai_assist, services
from .forms import (AssignForm, CloseForm, CommentForm, QuoteForm, QuoteResponseForm, RatingForm, TicketForm,
                    VisitForm, WorkPhotoForm)
from .models import Quote, Ticket, TicketPhoto

PAGE_SIZE = 15
MODERATION = (User.Role.MODERADOR, User.Role.ADMIN)


def _filters(request):
    """Filtros opcionales de la lista: ?categoria=...&estado=...&q=..."""
    return {
        "category": request.GET.get("categoria", ""),
        "status": request.GET.get("estado", ""),
        "search": request.GET.get("q", "").strip(),
    }


def _back(request, pk):
    """Vuelve al detalle si la acción se hizo desde allí; si no, a la lista."""
    if request.POST.get("from") == "detail":
        return redirect("tickets:detail", pk=pk)
    return redirect("tickets:list")


def _first_error(form):
    """Primer mensaje de error de un formulario, para mostrarlo como aviso."""
    for errors in form.errors.values():
        return errors[0]
    return "Revisa los datos ingresados."


def _error_text(error):
    return error.message if hasattr(error, "message") else str(error)


@login_required
def ticket_list(request):
    # Qué tickets ve cada quién lo decide services.list_for() según el rol
    # (cliente: los suyos · trabajador: los asignados a él · moderador/admin: todos).
    filters = _filters(request)
    tickets = services.list_for(request.user, **filters)
    page_obj = Paginator(tickets, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)  # los enlaces de paginación conservan los filtros
    # El selector de "a qué trabajador asignar" solo lo necesita el moderador.
    workers = User.objects.filter(role=User.Role.TRABAJADOR, is_active=True) if request.user.role == User.Role.MODERADOR else None
    return render(request, "tickets/list.html", {
        "page_obj": page_obj,
        "querystring": params.urlencode(),
        "workers": workers,
        "categories": Ticket.Category.choices,
        "statuses": Ticket.Status.choices,
        "selected_category": filters["category"],
        "selected_status": filters["status"],
        "search": filters["search"],
        "is_filtered": bool(
            filters["search"]
            or filters["category"] in Ticket.Category.values
            or filters["status"] in Ticket.Status.values
        ),
    })


@login_required
def agenda(request):
    """Próximas visitas agendadas: cada rol ve las de sus tickets (el personal ve todas)."""
    start_of_today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    visits = (services.list_for(request.user)
              .filter(visit_at__isnull=False, visit_at__gte=start_of_today)
              .exclude(status__in=services.FINISHED_STATUSES)
              .order_by("visit_at"))
    return render(request, "tickets/agenda.html", {"visits": visits[:100]})


def _csv_cell(value):
    """Texto seguro para planillas: sin saltos de línea y sin que Excel interprete fórmulas."""
    text = " ".join(str(value if value is not None else "").split())
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def _local(dt):
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M") if dt else ""


@login_required
@role_required(*MODERATION)
def ticket_export(request):
    """Descarga la lista (con los filtros activos) como CSV; Excel lo abre directamente."""
    tickets = services.list_for(request.user, **_filters(request))
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="tickets-{timezone.localdate():%Y-%m-%d}.csv"'
    response.write("\ufeff")  # marca para que Excel lea bien las tildes
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["N°", "Asunto", "Categoría", "Estado", "Prioridad", "Origen", "Cliente", "Teléfono", "Dirección",
                     "Trabajador", "Creado", "Visita", "Cerrado", "Calificación", "Descripción"])
    for t in tickets:
        writer.writerow([
            t.id, _csv_cell(t.title), t.get_category_display(), t.get_status_display(), t.get_priority_display(),
            t.get_source_display(), _csv_cell(t.client.get_full_name() or t.client.username),
            _csv_cell(t.phone), _csv_cell(t.address),
            _csv_cell(t.worker.get_full_name() or t.worker.username) if t.worker else "",
            _local(t.created_at), _local(t.visit_at), _local(t.closed_at), t.rating or "", _csv_cell(t.description),
        ])
    return response


@login_required
@role_required(User.Role.CLIENTE)  # solo un cliente puede generar una solicitud nueva
def ticket_create(request):
    if request.method == "POST":
        form = TicketForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data
            try:
                services.create_ticket(
                    request.user, data["title"], data["description"],
                    category=data["category"], image=data.get("image"),
                    phone=data["phone"], address=data["address"],
                )
            except ValidationError as error:
                form.add_error("image", _error_text(error))
            else:
                services.remember_contact(request.user, data["phone"], data["address"])
                messages.success(request, "Ticket creado correctamente.")
                return redirect("tickets:list")
    else:
        # Se precargan los datos de contacto del perfil para no pedirlos de nuevo
        form = TicketForm(initial={"phone": request.user.phone, "address": request.user.address})
    return render(request, "tickets/create.html", {"form": form})


@login_required
def ticket_detail(request, pk):
    # get_allowed() revisa que el usuario tenga derecho a ver este ticket puntual
    # (un cliente no puede abrir el ticket de otro cliente, por ejemplo) y lanza
    # PermissionDenied (HTTP 403) si no corresponde.
    ticket = services.get_allowed(request.user, pk)
    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            services.add_comment(request.user, pk, form.cleaned_data["text"])
            return redirect("tickets:detail", pk=pk)
    else:
        form = CommentForm()

    role = request.user.role
    is_client = role == User.Role.CLIENTE
    is_moderation = role in MODERATION
    can_manage = role in (User.Role.CLIENTE, *MODERATION)
    finished = ticket.status in services.FINISHED_STATUSES
    is_assigned_worker = role == User.Role.TRABAJADOR and ticket.worker_id == request.user.id
    quotes = list(ticket.quotes.all()) if role != User.Role.TRABAJADOR else []  # los montos no los ve el trabajador

    suggestion = request.session.get("ai_suggestion")
    if not (is_moderation and suggestion and suggestion.get("ticket") == ticket.id):
        suggestion = None
    else:
        suggestion = {**suggestion,
                      "category_label": Ticket.Category(suggestion["category"]).label,
                      "priority_label": Ticket.Priority(suggestion["priority"]).label}

    return render(request, "tickets/detail.html", {
        "ticket": ticket,
        "comments": ticket.comments.select_related("author"),
        "events": ticket.events.select_related("actor"),
        "photos": ticket.photos.all(),
        "form": form,
        "categories": Ticket.Category.choices,
        "can_cancel": can_manage and not finished,
        "can_reopen": can_manage and finished,
        "rating_form": RatingForm() if is_client and ticket.status == Ticket.Status.CERRADO and ticket.rating is None else None,
        "workers": (User.objects.filter(role=User.Role.TRABAJADOR, is_active=True)
                    if request.user.role == User.Role.MODERADOR and not finished else None),
        # cotizaciones
        "quotes": quotes,
        "pending_quote": next((q for q in quotes if q.status == Quote.Status.PENDIENTE), None) if is_client else None,
        "quote_response_form": QuoteResponseForm(),
        "quote_form": QuoteForm() if is_moderation and not finished else None,
        # agenda
        "visit_form": VisitForm(initial={"visit_note": ticket.visit_note}) if is_moderation and not finished else None,
        # terreno
        "work_photo_form": WorkPhotoForm() if (is_assigned_worker or is_moderation) and ticket.status != Ticket.Status.CANCELADO else None,
        "close_form": CloseForm() if is_assigned_worker and not finished else None,
        # ayuda de IA (solo propuestas)
        "ai_suggestion": suggestion,
        "priorities": Ticket.Priority.choices,
    })


@login_required
def ticket_image(request, pk):
    """Entrega la foto del ticket solo a quien puede ver el ticket (no es un archivo público)."""
    ticket = services.get_allowed(request.user, pk)
    if not ticket.image:
        raise Http404("Este ticket no tiene foto")
    try:
        response = FileResponse(ticket.image.open("rb"))
    except FileNotFoundError:
        raise Http404("Archivo no encontrado")
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
def ticket_photo(request, pk, photo_id):
    """Foto del trabajo realizado: solo la ve quien puede ver el ticket."""
    ticket = services.get_allowed(request.user, pk)
    photo = get_object_or_404(TicketPhoto, pk=photo_id, ticket=ticket)
    try:
        response = FileResponse(photo.image.open("rb"))
    except FileNotFoundError:
        raise Http404("Archivo no encontrado")
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
@role_required(User.Role.MODERADOR)  # solo el moderador prioriza, asigna y reasigna
def ticket_assign(request, pk):
    if request.method == "POST":
        form = AssignForm(request.POST)
        if form.is_valid():
            try:
                services.assign(pk, form.cleaned_data["worker_id"], form.cleaned_data["priority"], actor=request.user)
                messages.success(request, "Ticket asignado.")
            except ValidationError as error:
                messages.error(request, _error_text(error))
    return _back(request, pk)


@login_required
@role_required(*MODERATION)  # quien clasifica puede corregir la categoría
def ticket_category(request, pk):
    if request.method == "POST":
        try:
            services.set_category(pk, request.POST.get("category", ""), actor=request.user)
            messages.success(request, "Categoría actualizada.")
        except ValidationError:
            messages.error(request, "Categoría inválida.")
    return redirect("tickets:detail", pk=pk)


@login_required
@role_required(*MODERATION)
@require_POST
def ticket_priority(request, pk):
    try:
        services.set_priority(pk, request.POST.get("priority", ""), actor=request.user)
        messages.success(request, "Prioridad actualizada.")
    except ValidationError:
        messages.error(request, "Prioridad inválida.")
    return redirect("tickets:detail", pk=pk)


@login_required
@role_required(User.Role.TRABAJADOR)  # solo el trabajador asignado cambia el estado del trabajo
@require_POST
def ticket_status(request, pk, status):
    try:
        services.change_status(request.user, pk, status, note=request.POST.get("note", ""))
    except ValidationError as error:
        messages.error(request, _error_text(error))
    return _back(request, pk)


@login_required
@require_POST
def ticket_cancel(request, pk):
    try:
        services.cancel_ticket(request.user, pk)
        messages.success(request, "El ticket fue cancelado.")
    except ValidationError as error:
        messages.error(request, _error_text(error))
    return redirect("tickets:detail", pk=pk)


@login_required
@require_POST
def ticket_reopen(request, pk):
    try:
        services.reopen_ticket(request.user, pk)
        messages.success(request, "El ticket fue reabierto.")
    except ValidationError as error:
        messages.error(request, _error_text(error))
    return redirect("tickets:detail", pk=pk)


@login_required
@role_required(User.Role.CLIENTE)
@require_POST
def ticket_rate(request, pk):
    form = RatingForm(request.POST)
    if form.is_valid():
        try:
            services.rate_ticket(request.user, pk, form.cleaned_data["rating"], form.cleaned_data["comment"])
            messages.success(request, "¡Gracias por calificar la atención!")
        except ValidationError as error:
            messages.error(request, _error_text(error))
    else:
        messages.error(request, "Elige una calificación de 1 a 5.")
    return redirect("tickets:detail", pk=pk)


# ---- cotizaciones formales ----

@login_required
@role_required(*MODERATION)
@require_POST
def ticket_quote_create(request, pk):
    form = QuoteForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        try:
            services.create_quote(request.user, pk, data["detail"], data["amount"], data["valid_until"])
            messages.success(request, "Cotización enviada al cliente.")
        except ValidationError as error:
            messages.error(request, _error_text(error))
    else:
        messages.error(request, _first_error(form))
    return redirect("tickets:detail", pk=pk)


@login_required
@role_required(User.Role.CLIENTE)
@require_POST
def ticket_quote_respond(request, pk, quote_id):
    decision = request.POST.get("decision")
    if decision not in ("accept", "reject"):
        messages.error(request, "Elige aceptar o rechazar la cotización.")
        return redirect("tickets:detail", pk=pk)
    form = QuoteResponseForm(request.POST)
    comment = form.cleaned_data["comment"] if form.is_valid() else ""
    try:
        services.respond_quote(request.user, pk, quote_id, decision == "accept", comment)
        messages.success(request, "Cotización aceptada. El equipo se pondrá en contacto." if decision == "accept"
                         else "Cotización rechazada.")
    except ValidationError as error:
        messages.error(request, _error_text(error))
    return redirect("tickets:detail", pk=pk)


# ---- agenda de visitas ----

@login_required
@role_required(*MODERATION)
@require_POST
def ticket_visit(request, pk):
    form = VisitForm(request.POST)
    if form.is_valid():
        try:
            services.schedule_visit(request.user, pk, form.cleaned_data["visit_at"], form.cleaned_data["visit_note"])
            messages.success(request, "Visita agendada. Se avisó al cliente y al trabajador.")
        except ValidationError as error:
            messages.error(request, _error_text(error))
    else:
        messages.error(request, _first_error(form))
    return redirect("tickets:detail", pk=pk)


# ---- fotos del trabajo (terreno) ----

@login_required
@require_POST
def ticket_photo_upload(request, pk):
    form = WorkPhotoForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            services.add_work_photo(request.user, pk, form.cleaned_data["image"], form.cleaned_data["caption"])
            messages.success(request, "Foto agregada.")
        except ValidationError as error:
            messages.error(request, _error_text(error))
    else:
        messages.error(request, _first_error(form))
    return redirect("tickets:detail", pk=pk)


# ---- ayuda de IA para el moderador: solo propuestas ----

@login_required
@role_required(*MODERATION)
@require_POST
def ticket_suggest(request, pk):
    ticket = services.get_allowed(request.user, pk)
    use_ai = True
    if throttle.ai_assist_over_limit(request.user):
        use_ai = False
        messages.warning(request, "Llegaste al límite de sugerencias con IA por hora: esta propuesta usa reglas simples.")
    result = ai_assist.suggest(ticket, use_ai=use_ai)
    request.session["ai_suggestion"] = {"ticket": ticket.id, **result}
    return redirect("tickets:detail", pk=pk)


@login_required
@role_required(*MODERATION)
@require_POST
def ticket_suggest_dismiss(request, pk):
    request.session.pop("ai_suggestion", None)
    return redirect("tickets:detail", pk=pk)


@login_required
@role_required(User.Role.ADMIN)  # solo el administrador elimina tickets
@require_POST
def ticket_delete(request, pk):
    title = services.delete_ticket(pk)
    audit.log(request, AuditLog.Action.TICKET_ELIMINADO, f"Ticket #{pk}", title)
    messages.success(request, f"Ticket #{pk} eliminado.")
    return redirect("tickets:list")
