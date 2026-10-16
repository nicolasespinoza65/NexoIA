"""Control de acceso por rol: redirige o rechaza si el usuario no tiene el rol requerido."""
from functools import wraps
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Uso: @role_required(User.Role.ADMIN, User.Role.MODERADOR)"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied("No tienes permisos para esta acción")
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
