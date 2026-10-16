import re
from django.conf import settings


def company(request):
    """Datos de la empresa y del ambiente, disponibles en todas las plantillas."""
    info = dict(settings.COMPANY)
    info["phone_href"] = re.sub(r"[^\d+]", "", info.get("phone", ""))
    info["whatsapp"] = re.sub(r"\D", "", info.get("whatsapp", ""))
    has_contact = any(info.get(k) for k in ("phone", "whatsapp", "email", "hours", "area", "address"))
    return {
        "company": info,
        "company_has_contact": has_contact,
        "environment_label": settings.ENVIRONMENT_LABEL,
        "chat_retention_days": settings.CHAT_RETENTION_DAYS,
        "turnstile_enabled": bool(settings.TURNSTILE_SITE_KEY),
    }
