"""Límites de intentos y de uso. Los contadores viven en el caché de Django, que es compartido
entre los procesos de Gunicorn, y expiran solos."""
import hashlib

from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    """Dirección del visitante. Detrás de Nginx solo se confía en X-Forwarded-For si TRUST_PROXY_HEADERS está activo."""
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _key(prefix, *parts):
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def hit(key, window_seconds):
    """Cuenta un evento dentro de una ventana de tiempo y devuelve el total acumulado."""
    if cache.add(key, 1, timeout=window_seconds):
        return 1
    try:
        return cache.incr(key)
    except ValueError:  # la clave expiró justo antes
        cache.set(key, 1, timeout=window_seconds)
        return 1


def count(key):
    return cache.get(key, 0)


# --- inicio de sesión: bloqueo tras varios intentos fallidos ---
def login_key(request, username):
    return _key("login", client_ip(request), username.strip().lower())


def login_locked(key):
    return count(key) >= settings.LOGIN_MAX_ATTEMPTS


def login_failed(key):
    hit(key, settings.LOGIN_LOCK_MINUTES * 60)


def login_reset(key):
    cache.delete(key)


# --- chat sin cuenta: tope de mensajes por visitante ---
def visitor_over_limit(request):
    key = _key("visitor", client_ip(request))
    return hit(key, 600) > settings.VISITOR_CHAT_MAX_PER_10MIN


# --- reenvío del correo de verificación: como máximo uno por minuto ---
def can_resend_verification(user):
    return hit(_key("resend", str(user.pk)), 60) == 1


# --- verificación en dos pasos: mismos límites que el login, por usuario ---
def twofa_key(user):
    return _key("2fa", str(user.pk))


# --- registro de cuentas nuevas: tope por dirección y hora (cuenta solo las cuentas creadas) ---
def register_blocked(request):
    return count(_key("register", client_ip(request))) >= settings.REGISTER_MAX_PER_HOUR


def register_recorded(request):
    hit(_key("register", client_ip(request)), 3600)


# --- ayuda de IA para moderadores: tope de sugerencias por usuario y hora ---
def ai_assist_over_limit(user):
    return hit(_key("ai-assist", str(user.pk)), 3600) > settings.AI_ASSIST_MAX_PER_HOUR
