from django.contrib import admin
from django.contrib.auth import views as auth_views
from . import views as site_views
from django.urls import path, include
from accounts import views as account_views

urlpatterns = [
    path("admin-django/", admin.site.urls),  # panel técnico de Django (distinto del rol ADMIN de la app)
    path("", account_views.home, name="home"),
    path("login/", account_views.ThrottledLoginView.as_view(), name="login"),
    path("ingreso/", account_views.post_login, name="post_login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("registro/", account_views.register, name="register"),
    path("salud/", site_views.health, name="health"),
    path("privacidad/", account_views.privacy, name="privacy"),
    path("terminos/", account_views.terms, name="terms"),
    path("cuentas/", include("accounts.urls")),
    path("tickets/", include("tickets.urls")),
    path("asistente/", include("chatbot.urls")),
    path("notificaciones/", include("notifications.urls")),
    path("indicadores/", include("stats.urls")),
]
