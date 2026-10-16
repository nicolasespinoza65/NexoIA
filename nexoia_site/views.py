from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


def health(request):
    """Estado del sitio para monitores externos (UptimeRobot, Better Stack, etc.): responde 200 si la base de
    datos y el caché funcionan, y 503 si no. No expone datos ni requiere sesión."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = True
    except Exception:
        checks["database"] = False
    try:
        cache.set("health-check", "ok", 10)
        checks["cache"] = cache.get("health-check") == "ok"
    except Exception:
        checks["cache"] = False
    healthy = all(checks.values())
    return JsonResponse({"status": "ok" if healthy else "error", **checks}, status=200 if healthy else 503)
