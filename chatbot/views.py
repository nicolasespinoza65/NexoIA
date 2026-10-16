"""Vistas del asistente IA. El chat vive como burbuja flotante en todas las páginas
(ver templates/partials/chat_widget.html y static/js/chat.js), así que aquí solo hay
dos endpoints JSON: historial y envío de mensajes. Toda la decisión (responder /
derivar a ticket / rechazar fuera de tema) sigue en chatbot.services.ask()."""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from accounts import throttle
from accounts.decorators import role_required
from accounts import audit
from accounts.models import AuditLog, User
from . import services
from .forms import FaqEntryForm
from .models import ChatMessage, FaqEntry

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 1000
MAX_VISITOR_LENGTH = 300
HISTORY_LIMIT = 30


def chat(request):
    """La antigua página /asistente/ ya no existe: el chat es flotante. Se mantiene la URL
    para no romper enlaces guardados y se lleva al usuario a la página de inicio."""
    return redirect("home")


@login_required
@role_required(User.Role.CLIENTE)  # el chat es un canal exclusivo del cliente
@require_GET
def history(request):
    last = list(ChatMessage.objects.filter(client=request.user).order_by("-id")[:HISTORY_LIMIT])
    return JsonResponse({
        "messages": [{"question": m.question, "answer": m.answer} for m in reversed(last)],
        "suggestions": services.suggestions(),
    })


@login_required
@role_required(User.Role.CLIENTE)
@require_POST
def human(request):
    """«Hablar con una persona»: crea (o reutiliza) un ticket para que un moderador responda."""
    ticket, created = services.request_human(request.user)
    if created:
        answer = (f"Listo, avisé a nuestro equipo: una persona revisará tu consulta y te responderá por la plataforma "
                  f"(ticket #{ticket.id}).")
    else:
        answer = f"Ya tienes una solicitud abierta (ticket #{ticket.id}): una persona la revisará pronto."
    return JsonResponse({"answer": answer, "ticket_id": ticket.id,
                         "ticket_url": reverse("tickets:detail", args=[ticket.id])})


@login_required
@role_required(User.Role.CLIENTE)
@require_POST
def send(request):
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Solicitud inválida."}, status=400)

    question = str(payload.get("message", "")).strip()[:MAX_QUESTION_LENGTH]
    if not question:
        return JsonResponse({"error": "Escribe un mensaje."}, status=400)

    try:
        result = services.ask(request.user, question)  # aquí ocurre todo el flujo IA -> ticket si corresponde
    except Exception:
        logger.exception("Error en el asistente al procesar un mensaje")
        return JsonResponse({"error": "El asistente no está disponible por ahora. Inténtalo de nuevo en unos minutos."}, status=500)
    ticket_url = reverse("tickets:detail", args=[result["ticket_id"]]) if result["ticket_id"] else None
    return JsonResponse({"answer": result["answer"], "ticket_id": result["ticket_id"], "ticket_url": ticket_url})


@require_http_methods(["GET", "POST"])
def visitor(request):
    """Chat para visitantes sin cuenta. GET: preguntas rápidas sugeridas. POST: respuesta a una pregunta básica.
    Es público a propósito, por eso no usa IA, no guarda nada y no crea tickets (ver services.ask_visitor)."""
    if request.method == "GET":
        return JsonResponse({"suggestions": services.suggestions(authenticated=False)})

    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Solicitud inválida."}, status=400)
    question = str(payload.get("message", "")).strip()[:MAX_VISITOR_LENGTH]
    if not question:
        return JsonResponse({"error": "Escribe un mensaje."}, status=400)
    if throttle.visitor_over_limit(request):
        return JsonResponse({"error": "Enviaste muchos mensajes seguidos. Espera unos minutos o crea una cuenta."}, status=429)
    return JsonResponse(services.ask_visitor(question))


# ---- Respuestas editables del asistente (solo administrador) ----

@login_required
@role_required(User.Role.ADMIN)
def faq_list(request):
    """Lista las respuestas del asistente y permite crear una nueva."""
    if request.method == "POST":
        form = FaqEntryForm(request.POST)
        if form.is_valid():
            entry = form.save()
            audit.log(request, AuditLog.Action.RESPUESTA_CREADA, entry.title)
            messages.success(request, "Respuesta creada.")
            return redirect("chatbot:faq_list")
    else:
        # Si viene desde el reporte de preguntas sin respuesta, el formulario ya trae el título y las palabras clave
        form = FaqEntryForm(initial={"active": True, "title": request.GET.get("title", "")[:120],
                                     "keywords": request.GET.get("keywords", "")[:300]})
    return render(request, "chatbot/faq_list.html", {"entries": FaqEntry.objects.all(), "form": form})


@login_required
@role_required(User.Role.ADMIN)
def faq_edit(request, pk):
    entry = get_object_or_404(FaqEntry, pk=pk)
    if request.method == "POST":
        form = FaqEntryForm(request.POST, instance=entry)
        if form.is_valid():
            form.save()
            audit.log(request, AuditLog.Action.RESPUESTA_EDITADA, entry.title)
            messages.success(request, "Respuesta actualizada.")
            return redirect("chatbot:faq_list")
    else:
        form = FaqEntryForm(instance=entry)
    return render(request, "chatbot/faq_form.html", {"form": form, "entry": entry})


@login_required
@role_required(User.Role.ADMIN)
@require_POST
def faq_delete(request, pk):
    entry = get_object_or_404(FaqEntry, pk=pk)
    audit.log(request, AuditLog.Action.RESPUESTA_ELIMINADA, entry.title)
    entry.delete()
    messages.success(request, "Respuesta eliminada.")
    return redirect("chatbot:faq_list")


@login_required
@role_required(User.Role.ADMIN)
def unanswered(request):
    """Preguntas que el asistente no supo responder, para convertirlas en respuestas con un clic."""
    return render(request, "chatbot/unanswered.html", {"groups": services.unanswered_questions()})


@login_required
@role_required(User.Role.ADMIN)
@require_POST
def unanswered_dismiss(request):
    ids = [int(i) for i in request.POST.get("ids", "").split(",") if i.strip().isdigit()]
    ChatMessage.objects.filter(pk__in=ids, resolved_by_ai=False).update(reviewed=True)
    messages.success(request, "Pregunta descartada.")
    return redirect("chatbot:unanswered")
