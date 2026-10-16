"""Registro de auditoría. Uso: audit.log(request, AuditLog.Action.TICKET_ELIMINADO, "Ticket #5", "detalle")"""
from . import throttle
from .models import AuditLog


def log(request, action, target="", detail=""):
    user = getattr(request, "user", None)
    actor = user if (user is not None and user.is_authenticated) else None
    return AuditLog.objects.create(
        actor=actor, action=action, target=target[:120], detail=detail[:255],
        ip=throttle.client_ip(request) or None,
    )
