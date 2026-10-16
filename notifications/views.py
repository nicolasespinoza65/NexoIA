import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import Notification

PAGE_SIZE = 20


@login_required
def notification_list(request):
    notifs = Notification.objects.filter(user=request.user)
    page_obj = Paginator(notifs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {"page_obj": page_obj})


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(user=request.user, seen=False).update(seen=True)
    return redirect("notifications:list")


@login_required
@require_POST
def clear_read(request):
    """Elimina las notificaciones ya leídas para que la lista no crezca sin límite."""
    deleted, _ = Notification.objects.filter(user=request.user, seen=True).delete()
    messages.success(request, f"Se eliminaron {deleted} notificaciones leídas.")
    return redirect("notifications:list")


@login_required
def notification_open(request, pk):
    """Abre el destino de una notificación. La marca como leída y, si apunta a un ticket que ya no
    existe, la elimina y avisa en vez de mostrar un 404."""
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.seen:
        n.seen = True
        n.save(update_fields=["seen"])
    m = re.fullmatch(r"/tickets/(\d+)/", n.link or "")
    if m:
        from tickets.models import Ticket  # import perezoso para no acoplar los módulos
        if not Ticket.objects.filter(pk=m[1]).exists():
            n.delete()
            messages.info(request, "Ese ticket ya no existe; quitamos la notificación.")
            return redirect("notifications:list")
    return redirect(n.link or "notifications:list")
