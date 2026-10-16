"""Verificación en dos pasos (TOTP, RFC 6238), compatible con Google Authenticator, Microsoft Authenticator,
Authy y similares. Implementado con la biblioteca estándar de Python: no agrega dependencias."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6


def generate_secret():
    """Clave secreta nueva: 20 bytes aleatorios en base32 (32 caracteres)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _code_for_step(secret, step, digits=DIGITS):
    key = base64.b32decode(secret, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(number).zfill(digits)


def current_step(now=None):
    return int((time.time() if now is None else now) // STEP_SECONDS)


def verify(secret, code, last_step=0, now=None, window=1):
    """Devuelve el paso (número) del código si es válido, o None.
    Acepta el paso anterior y el siguiente por si el reloj del teléfono está algo desfasado, y rechaza
    cualquier paso ya usado (last_step) para que un código no sirva dos veces."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step_now = current_step(now)
    for step in range(step_now - window, step_now + window + 1):
        if step > last_step and hmac.compare_digest(_code_for_step(secret, step), code):
            return step
    return None


def provisioning_uri(secret, account, issuer="Soluciones SSDP"):
    """Dirección otpauth:// que entienden las aplicaciones autenticadoras (para ingreso manual o código QR)."""
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP_SECONDS}"


def format_secret(secret):
    """Agrupa la clave de a 4 caracteres para que sea fácil de copiar a mano."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
