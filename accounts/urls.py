from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from . import views

app_name = "accounts"
urlpatterns = [
    path("usuarios/", views.user_list, name="users"),
    path("usuarios/<int:pk>/activar/", views.user_toggle_active, name="toggle_active"),
    path("usuarios/<int:pk>/quitar-2fa/", views.reset_two_factor, name="reset_two_factor"),
    path("auditoria/", views.audit_list, name="audit"),
    path("galeria/", views.work_gallery, name="gallery"),
    path("galeria/<int:pk>/editar/", views.work_photo_edit, name="gallery_edit"),
    path("galeria/<int:pk>/eliminar/", views.work_photo_delete, name="gallery_delete"),
    path("fotos-trabajos/<int:pk>/", views.work_photo, name="work_photo"),
    path("perfil/", views.profile, name="profile"),
    path("perfil/dos-pasos/", views.two_factor_setup, name="two_factor_setup"),
    path("perfil/dos-pasos/quitar/", views.two_factor_disable, name="two_factor_disable"),
    path("perfil/descargar-datos/", views.export_data, name="export_data"),
    path("perfil/eliminar-cuenta/", views.delete_account, name="delete_account"),
    path("verificacion/", views.two_factor_challenge, name="two_factor"),
    path("verificar/reenviar/", views.resend_verification, name="resend_verification"),
    path("verificar/<str:token>/", views.verify_email, name="verify"),

    # Cambio de contraseña (con sesión iniciada)
    path("clave/cambiar/", auth_views.PasswordChangeView.as_view(
        template_name="accounts/password_change_form.html",
        success_url=reverse_lazy("accounts:password_change_done")), name="password_change"),
    path("clave/cambiada/", auth_views.PasswordChangeDoneView.as_view(
        template_name="accounts/password_change_done.html"), name="password_change_done"),

    # Recuperación de contraseña por correo (sin sesión)
    path("clave/recuperar/", auth_views.PasswordResetView.as_view(
        template_name="accounts/password_reset_form.html",
        email_template_name="accounts/password_reset_email.txt",
        subject_template_name="accounts/password_reset_subject.txt",
        extra_email_context={"site_url": settings.SITE_URL.rstrip("/")},
        success_url=reverse_lazy("accounts:password_reset_done")), name="password_reset"),
    path("clave/recuperar/enviado/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path("clave/restablecer/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="accounts/password_reset_confirm.html",
        success_url=reverse_lazy("accounts:password_reset_complete")), name="password_reset_confirm"),
    path("clave/restablecida/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/password_reset_complete.html"), name="password_reset_complete"),
]
