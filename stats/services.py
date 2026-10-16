"""Indicadores de gestión para el administrador (coincide con el KPI del informe)."""
from datetime import timedelta

from django.conf import settings
from django.db.models import Avg, Count, F, Min, Q
from django.utils import timezone
from accounts.models import User
from tickets.models import Ticket, TicketComment, TicketEvent
from chatbot.models import ChatMessage

WEEKS = 8


def _breakdown(choices, counts, total):
    """Convierte {codigo: n} en filas con etiqueta legible y porcentaje, en el orden del catálogo."""
    return [
        {
            "code": code,
            "label": label,
            "count": counts.get(code, 0),
            "percent": round(100 * counts.get(code, 0) / total) if total else 0,
        }
        for code, label in choices
    ]


def _format_hours(hours):
    if hours < 1:
        return f"{round(hours * 60)} min"
    if hours < 48:
        return f"{hours:.1f} h".replace(".", ",")
    return f"{hours / 24:.1f} días".replace(".", ",")


def _avg_resolution(tickets):
    """Tiempo medio entre que se crea y se cierra un ticket (solo tickets cerrados con fecha de cierre)."""
    pairs = tickets.filter(status=Ticket.Status.CERRADO, closed_at__isnull=False).values_list("created_at", "closed_at")
    seconds = [(closed - created).total_seconds() for created, closed in pairs]
    if not seconds:
        return None
    return _format_hours(sum(seconds) / len(seconds) / 3600)


# Acciones del personal que el cliente ve y que cuentan como "primera respuesta" (además de un comentario).
FIRST_RESPONSE_EVENTS = [TicketEvent.Kind.ASIGNADO, TicketEvent.Kind.ESTADO, TicketEvent.Kind.COTIZACION, TicketEvent.Kind.VISITA]


def _avg_first_response(tickets):
    """Tiempo medio entre que se crea un ticket y la primera respuesta del equipo. Cuenta como respuesta el primer
    comentario de alguien que no sea el cliente, o la primera asignación, cambio de estado, cotización o visita
    agendada (lo que ocurra antes). Los tickets que aún no reciben respuesta no entran en el promedio.
    Devuelve (promedio legible o None, cantidad de tickets medidos)."""
    created = dict(tickets.values_list("id", "created_at"))
    if not created:
        return None, 0
    # order_by() vacío: el orden por defecto de los modelos (por id) rompería el GROUP BY y no agruparía por ticket
    comments = (TicketComment.objects.filter(ticket__in=tickets).exclude(author_id=F("ticket__client_id"))
                .order_by().values("ticket_id").annotate(first=Min("created_at")))
    events = (TicketEvent.objects.filter(ticket__in=tickets, kind__in=FIRST_RESPONSE_EVENTS, actor__isnull=False)
              .exclude(actor_id=F("ticket__client_id"))
              .order_by().values("ticket_id").annotate(first=Min("created_at")))
    first = {}
    for row in list(comments) + list(events):
        previous = first.get(row["ticket_id"])
        if previous is None or row["first"] < previous:
            first[row["ticket_id"]] = row["first"]
    seconds = [max(0, (moment - created[ticket_id]).total_seconds()) for ticket_id, moment in first.items()]
    if not seconds:
        return None, 0
    return _format_hours(sum(seconds) / len(seconds) / 3600), len(seconds)


def _weekly_volume():
    """Tickets creados en cada una de las últimas semanas (de la más antigua a la más reciente)."""
    now = timezone.now()
    created = list(Ticket.objects.filter(created_at__gte=now - timedelta(weeks=WEEKS)).values_list("created_at", flat=True))
    rows = []
    for i in range(WEEKS - 1, -1, -1):
        end = now - timedelta(weeks=i)
        begin = end - timedelta(weeks=1)
        rows.append({
            "label": f"Semana del {timezone.localtime(begin):%d/%m}",
            "count": sum(1 for c in created if begin < c <= end),
        })
    peak = max(r["count"] for r in rows)
    for r in rows:
        r["percent"] = round(100 * r["count"] / peak) if peak else 0
    return rows


def _satisfaction(tickets):
    """Promedio y distribución de las calificaciones (1 a 5) que dejaron los clientes."""
    rated = tickets.filter(rating__isnull=False)
    count = rated.count()
    if not count:
        return {"average": None, "count": 0, "distribution": []}
    counts = dict(rated.values_list("rating").annotate(n=Count("id")))
    average = rated.aggregate(avg=Avg("rating"))["avg"]
    return {
        "average": f"{average:.1f}".replace(".", ","),
        "count": count,
        "distribution": [
            {"label": f"{stars} {'estrella' if stars == 1 else 'estrellas'}", "count": counts.get(stars, 0),
             "percent": round(100 * counts.get(stars, 0) / count)}
            for stars in (5, 4, 3, 2, 1)
        ],
    }


def _worker_load():
    """Carga actual de cada trabajador activo (no depende del filtro de fechas)."""
    active_statuses = [Ticket.Status.ASIGNADO, Ticket.Status.EN_PROCESO]
    return list(
        User.objects.filter(role=User.Role.TRABAJADOR, is_active=True)
        .annotate(
            active=Count("tickets_as_worker", filter=Q(tickets_as_worker__status__in=active_statuses)),
            done=Count("tickets_as_worker", filter=Q(tickets_as_worker__status=Ticket.Status.CERRADO)),
        )
        .order_by("-active", "first_name", "username")
    )


def _stale_tickets():
    """Tickets abiertos y sin asignar hace más horas de las permitidas (STALE_TICKET_HOURS)."""
    now = timezone.now()
    queryset = (Ticket.objects.filter(status=Ticket.Status.ABIERTO, created_at__lt=now - timedelta(hours=settings.STALE_TICKET_HOURS))
                .select_related("client").order_by("created_at"))
    rows = [
        {"id": t.id, "title": t.title, "client": t.client.get_full_name() or t.client.username,
         "hours": int((now - t.created_at).total_seconds() // 3600), "urgent": t.priority == Ticket.Priority.ALTA}
        for t in queryset[:10]
    ]
    return queryset.count(), rows


def summary(date_from=None, date_to=None):
    """Indicadores del período indicado (por fecha de creación). Sin fechas, considera todo el historial."""
    tickets = Ticket.objects.all()
    chats = ChatMessage.objects.all()
    if date_from:
        tickets = tickets.filter(created_at__date__gte=date_from)
        chats = chats.filter(created_at__date__gte=date_from)
    if date_to:
        tickets = tickets.filter(created_at__date__lte=date_to)
        chats = chats.filter(created_at__date__lte=date_to)

    total = tickets.count()
    status_counts = dict(tickets.values_list("status").annotate(n=Count("id")))
    category_counts = dict(tickets.values_list("category").annotate(n=Count("id")))
    total_chats = chats.count()
    resolved = chats.filter(resolved_by_ai=True).count()
    stale_count, stale_rows = _stale_tickets()
    avg_first_response, first_response_count = _avg_first_response(tickets)
    return {
        "total_tickets": total,
        "open_tickets": status_counts.get(Ticket.Status.ABIERTO, 0),
        "tickets_by_status": _breakdown(Ticket.Status.choices, status_counts, total),
        "tickets_by_category": _breakdown(Ticket.Category.choices, category_counts, total),
        "avg_resolution": _avg_resolution(tickets),
        "avg_first_response": avg_first_response,
        "first_response_count": first_response_count,
        "satisfaction": _satisfaction(tickets),
        "weekly_volume": _weekly_volume(),
        "worker_load": _worker_load(),
        "stale_count": stale_count,
        "stale_tickets": stale_rows,
        "stale_hours": settings.STALE_TICKET_HOURS,
        "total_chats": total_chats,
        "resolved_by_ai_percent": round(100 * resolved / total_chats) if total_chats else 0,
    }
