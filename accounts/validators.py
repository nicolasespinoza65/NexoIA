import re
from django.core.exceptions import ValidationError

_PHONE_RE = re.compile(r"^[0-9+()\s-]{8,20}$")


def validate_phone(value):
    """Teléfono chileno o internacional: solo números, espacios, +, paréntesis y guiones (8 a 20 caracteres)."""
    if not _PHONE_RE.match(value.strip()):
        raise ValidationError("Ingresa un teléfono válido (solo números, espacios, + y guiones).")
