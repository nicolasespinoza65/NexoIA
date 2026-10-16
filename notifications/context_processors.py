from .models import Notification


def unseen_count(request):
    """Cantidad de notificaciones sin leer, para el globo del menú superior."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return {"unseen_notifications": Notification.objects.filter(user=user, seen=False).count()}
    return {}
