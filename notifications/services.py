"""API pública del módulo Notificaciones, usada por Tickets, Cuentas y Chatbot.
Cada notificación queda en la plataforma y además se envía por correo si el usuario tiene email."""
import logging
import threading

from django.conf import settings
from django.core.mail import send_mail
from .models import Notification

logger = logging.getLogger(__name__)


def notify_user(user, message, link=None):
    if user is None:
        return
    Notification.objects.create(user=user, message=message, link=link or "")
    body = f"Hola {user.get_full_name() or user.username},\n\n{message}\n"
    if link:
        body += f"\nVer en la plataforma: {settings.SITE_URL.rstrip('/')}{link}\n"
    body += "\nSoluciones SSDP Servicios Integrales SpA"
    send_email(user.email, f"Soluciones SSDP: {message}"[:150], body)


def notify_role(role, message, link=None):
    from accounts.models import User
    for u in User.objects.filter(role=role, is_active=True):
        notify_user(u, message, link=link)


def send_email(to_email, subject, body):
    """Envía un correo. Con EMAIL_ASYNC (por defecto) sale en segundo plano para no hacer esperar al
    usuario si el servidor de correo es lento."""
    if not to_email:
        return
    if getattr(settings, "EMAIL_ASYNC", False):
        threading.Thread(target=_deliver, args=(subject, body, to_email), daemon=True).start()
    else:
        _deliver(subject, body, to_email)


def _deliver(subject, body, to_email):
    """Un fallo de correo (servidor caído, clave mala) nunca debe romper la operación del usuario:
    se registra en el log y se sigue."""
    try:
        send_mail(subject, body, None, [to_email])
    except Exception:
        logger.exception("No se pudo enviar el correo a %s", to_email)
