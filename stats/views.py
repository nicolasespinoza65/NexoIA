import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from accounts.decorators import role_required
from accounts.models import User
from . import services


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@login_required
@role_required(User.Role.ADMIN)
def dashboard(request):
    # Filtro opcional por rango de fechas de creación: ?desde=AAAA-MM-DD&hasta=AAAA-MM-DD
    date_from = _parse_date(request.GET.get("desde"))
    date_to = _parse_date(request.GET.get("hasta"))
    return render(request, "stats/dashboard.html", {
        "stats": services.summary(date_from, date_to),
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
    })
