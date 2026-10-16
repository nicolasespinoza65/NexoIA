"""CAPTCHA opcional con Cloudflare Turnstile. Se activa definiendo TURNSTILE_SITE_KEY y TURNSTILE_SECRET_KEY."""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify(token, ip=""):
    """True si Cloudflare confirma que quien envió el formulario es una persona. Si el servicio no responde,
    se rechaza (es preferible pedir reintentar a dejar pasar bots)."""
    if not token:
        return False
    try:
        response = requests.post(
            VERIFY_URL, data={"secret": settings.TURNSTILE_SECRET_KEY, "response": token, "remoteip": ip}, timeout=5
        )
        return bool(response.json().get("success"))
    except Exception:
        logger.exception("No se pudo verificar el CAPTCHA")
        return False
