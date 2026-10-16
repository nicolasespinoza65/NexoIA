from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .models import User

STAFF_ROLES = (User.Role.ADMIN, User.Role.MODERADOR)


class RequireTwoFactorMiddleware:
    """Con REQUIRE_2FA_STAFF activo, un moderador o administrador que aún no configuró la verificación en
    dos pasos solo puede ver la página para configurarla (o cerrar sesión)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (settings.REQUIRE_2FA_STAFF and user is not None and user.is_authenticated
                and user.role in STAFF_ROLES and not user.totp_enabled):
            allowed = (reverse("accounts:two_factor_setup"), reverse("logout"), "/static/", reverse("health"))
            if not request.path.startswith(allowed):
                messages.info(request, "Por seguridad, activa la verificación en dos pasos para continuar.")
                return redirect("accounts:two_factor_setup")
        return self.get_response(request)
