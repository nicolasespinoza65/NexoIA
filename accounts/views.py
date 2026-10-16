import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from accounts.decorators import role_required
from chatbot import services as chatbot_services
from . import audit, services, throttle, totp
from .forms import (AdminCreateUserForm, DeleteAccountForm, PasswordConfirmForm, ProfileForm, RegisterForm,
                    TwoFactorForm, WorkPhotoEditForm, WorkPhotoUploadForm)
from .models import AuditLog, User, WorkPhoto
from .works import hero_photos, load_segments, segment_choices, segment_title

GALLERY_DIR = settings.BASE_DIR / "static" / "img" / "gallery"
GALLERY_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
WORKS_DIR = settings.BASE_DIR / "static" / "img" / "trabajos"
STAFF_ROLES = (User.Role.ADMIN, User.Role.MODERADOR)
GALLERY_ROLES = (User.Role.ADMIN, User.Role.MODERADOR, User.Role.TRABAJADOR)  # quienes pueden subir fotos de trabajos
GALLERY_PAGE_SIZE = 24
PENDING_2FA_SECONDS = 300


class ThrottledLoginView(LoginView):
    """Inicio de sesión que se bloquea unos minutos tras varios intentos fallidos con el mismo usuario
    desde la misma dirección (frena los intentos de adivinar contraseñas). Si la cuenta tiene la
    verificación en dos pasos activa, pide además el código de la aplicación autenticadora."""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        self.throttle_key = throttle.login_key(request, request.POST.get("username", ""))
        if throttle.login_locked(self.throttle_key):
            form = self.get_form_class()(request)
            context = self.get_context_data(form=form, lock_minutes=settings.LOGIN_LOCK_MINUTES)
            return self.render_to_response(context, status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        throttle.login_failed(self.throttle_key)
        if throttle.count(self.throttle_key) == settings.LOGIN_MAX_ATTEMPTS:  # justo al alcanzar el límite
            audit.log(self.request, AuditLog.Action.LOGIN_BLOQUEADO, self.request.POST.get("username", "")[:100],
                      f"{settings.LOGIN_MAX_ATTEMPTS} intentos fallidos")
        return super().form_invalid(form)

    def form_valid(self, form):
        user = form.get_user()
        throttle.login_reset(self.throttle_key)
        if user.totp_enabled:
            # Todavía no se inicia la sesión: falta el código de la aplicación autenticadora
            self.request.session["pending_2fa"] = {"uid": user.pk, "at": time.time(), "next": self.get_success_url()}
            return redirect("accounts:two_factor")
        response = super().form_valid(form)
        if user.role in STAFF_ROLES:
            audit.log(self.request, AuditLog.Action.LOGIN, user.username)
        return response


def two_factor_challenge(request):
    """Segundo paso del ingreso: código de 6 dígitos de la aplicación autenticadora."""
    pending = request.session.get("pending_2fa")
    if not pending or time.time() - pending.get("at", 0) > PENDING_2FA_SECONDS:
        request.session.pop("pending_2fa", None)
        messages.error(request, "La verificación venció. Ingresa de nuevo.")
        return redirect("login")
    user = User.objects.filter(pk=pending["uid"], is_active=True, totp_enabled=True).first()
    if user is None:
        request.session.pop("pending_2fa", None)
        return redirect("login")

    key = throttle.twofa_key(user)
    locked = throttle.login_locked(key)
    form = TwoFactorForm(request.POST or None)
    if request.method == "POST" and not locked and form.is_valid():
        step = totp.verify(user.totp_secret, form.cleaned_data["code"], user.totp_last_step)
        if step is None:
            throttle.login_failed(key)
            form.add_error("code", "El código no es correcto o ya fue usado. Revisa que la hora de tu teléfono sea la correcta.")
        else:
            user.totp_last_step = step
            user.save(update_fields=["totp_last_step"])
            throttle.login_reset(key)
            request.session.pop("pending_2fa", None)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            if user.role in STAFF_ROLES:
                audit.log(request, AuditLog.Action.LOGIN, user.username, "con verificación en dos pasos")
            return redirect(pending.get("next") or settings.LOGIN_REDIRECT_URL)
    return render(request, "accounts/two_factor.html", {"form": form, "locked": locked,
                                                        "lock_minutes": settings.LOGIN_LOCK_MINUTES},
                  status=429 if locked else 200)


@login_required
def two_factor_setup(request):
    """Activa la verificación en dos pasos: se muestra una clave para la aplicación autenticadora y se
    confirma con un primer código."""
    user = request.user
    if user.totp_enabled:
        messages.info(request, "La verificación en dos pasos ya está activa.")
        return redirect("accounts:profile")
    secret = request.session.get("totp_setup_secret")
    if not secret:
        secret = totp.generate_secret()
        request.session["totp_setup_secret"] = secret
    form = TwoFactorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        step = totp.verify(secret, form.cleaned_data["code"], 0)
        if step is None:
            form.add_error("code", "El código no es correcto. Revisa la clave y la hora de tu teléfono.")
        else:
            user.totp_secret = secret
            user.totp_enabled = True
            user.totp_last_step = step
            user.save(update_fields=["totp_secret", "totp_enabled", "totp_last_step"])
            request.session.pop("totp_setup_secret", None)
            audit.log(request, AuditLog.Action.DOS_PASOS_ON, user.username)
            messages.success(request, "Verificación en dos pasos activada.")
            return redirect("accounts:profile")
    return render(request, "accounts/two_factor_setup.html", {
        "form": form, "secret": totp.format_secret(secret),
        "uri": totp.provisioning_uri(secret, user.username),
    })


@login_required
def two_factor_disable(request):
    """Quita la verificación en dos pasos (pide la contraseña). Si es obligatoria para el rol, no se puede quitar."""
    user = request.user
    if not user.totp_enabled:
        return redirect("accounts:profile")
    required = settings.REQUIRE_2FA_STAFF and user.role in STAFF_ROLES
    form = PasswordConfirmForm(user, request.POST or None)
    if request.method == "POST" and not required and form.is_valid():
        user.totp_secret = ""
        user.totp_enabled = False
        user.totp_last_step = 0
        user.save(update_fields=["totp_secret", "totp_enabled", "totp_last_step"])
        audit.log(request, AuditLog.Action.DOS_PASOS_OFF, user.username)
        messages.success(request, "Verificación en dos pasos desactivada.")
        return redirect("accounts:profile")
    return render(request, "accounts/two_factor_disable.html", {"form": form, "required": required})


@login_required
@role_required(User.Role.ADMIN)
@require_POST
def reset_two_factor(request, pk):
    """El administrador quita la verificación en dos pasos de alguien que perdió su teléfono."""
    target = get_object_or_404(User, pk=pk)
    target.totp_secret = ""
    target.totp_enabled = False
    target.totp_last_step = 0
    target.save(update_fields=["totp_secret", "totp_enabled", "totp_last_step"])
    audit.log(request, AuditLog.Action.DOS_PASOS_OFF, target.username, "restablecida por un administrador")
    messages.success(request, f"Se quitó la verificación en dos pasos de {target.username}.")
    return redirect("accounts:users")


# Público: cualquier visitante puede crear su propia cuenta, siempre con rol CLIENTE
# (crear un ADMIN/MODERADOR/TRABAJADOR solo lo puede hacer el administrador, ver user_list más abajo).
def register(request):
    context = {"turnstile_site_key": settings.TURNSTILE_SITE_KEY}
    if request.method == "POST":
        if throttle.register_blocked(request):
            messages.error(request, "Se crearon demasiadas cuentas desde tu conexión. Inténtalo de nuevo más tarde.")
            return render(request, "accounts/register.html", {**context, "form": RegisterForm()}, status=429)
        form = RegisterForm(request.POST, captcha_token=request.POST.get("cf-turnstile-response", ""),
                            ip=throttle.client_ip(request))
        if form.is_valid():
            user = form.save()
            throttle.register_recorded(request)
            services.send_verification(user)  # correo con enlace para confirmar la dirección
            login(request, user)  # entra directo: sin pasar otra vez por el login
            messages.success(request, "Cuenta creada. Te enviamos un correo para confirmar tu dirección. Cuéntanos qué necesitas con tu primer ticket.")
            return redirect("tickets:create")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {**context, "form": form})


def verify_email(request, token):
    """Enlace del correo de verificación."""
    try:
        data = services.read_token(token)
    except signing.BadSignature:  # incluye enlaces vencidos
        messages.error(request, "El enlace no es válido o ya venció. Pide uno nuevo desde tu perfil.")
        return redirect("home")
    user = User.objects.filter(pk=data.get("uid"), email=data.get("email")).first()
    if user is None:
        messages.error(request, "El enlace no corresponde a ninguna cuenta.")
        return redirect("home")
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
    messages.success(request, "¡Correo confirmado! Ya puedes usar el asistente completo.")
    return redirect("home")


@login_required
@require_POST
def resend_verification(request):
    if request.user.email_verified:
        messages.info(request, "Tu correo ya está confirmado.")
    elif not throttle.can_resend_verification(request.user):
        messages.error(request, "Espera un minuto antes de pedir otro correo.")
    else:
        services.send_verification(request.user)
        messages.success(request, f"Te enviamos un correo de confirmación a {request.user.email}.")
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = reverse("accounts:profile")  # nunca se redirige a otro sitio
    return redirect(next_url)


@login_required
def profile(request):
    """Datos de contacto del usuario (se reutilizan al crear tickets) y enlaces a su cuenta."""
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Perfil actualizado.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "accounts/profile.html", {
        "form": form,
        "two_factor_required": settings.REQUIRE_2FA_STAFF and request.user.role in STAFF_ROLES,
    })


@login_required
@require_POST
def export_data(request):
    """Descarga todos los datos personales de la cuenta en un zip."""
    content = services.export_user_data(request.user)
    audit.log(request, AuditLog.Action.DATOS_EXPORTADOS, request.user.username)
    response = HttpResponse(content, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="mis-datos-{request.user.username}-{timezone.localdate():%Y-%m-%d}.zip"'
    return response


@login_required
def delete_account(request):
    """El cliente elimina su cuenta (pide la contraseña). El personal debe pedirlo a un administrador."""
    if request.user.role != User.Role.CLIENTE:
        messages.error(request, "Las cuentas del equipo las elimina un administrador.")
        return redirect("accounts:profile")
    form = DeleteAccountForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = request.user
        target = f"usuario #{user.pk}"
        audit.log(request, AuditLog.Action.CUENTA_ELIMINADA, target)
        logout(request)
        services.anonymize_user(user)
        messages.success(request, "Tu cuenta fue eliminada. Gracias por haber usado la plataforma.")
        return redirect("home")
    return render(request, "accounts/delete_account.html", {"form": form})


def _gallery_images():
    """Fotos de trabajos para la portada: basta con copiar imágenes a static/img/gallery/."""
    if not GALLERY_DIR.is_dir():
        return []
    files = (f.name for f in GALLERY_DIR.iterdir() if f.suffix.lower() in GALLERY_EXTENSIONS)
    return sorted(files)[:12]


def home(request):
    """Página de inicio pública de la empresa. La ve cualquier visitante; el asistente IA
    aparece como chat flotante en la esquina (lo inserta base.html)."""
    segments = load_segments(WORKS_DIR, WorkPhoto.objects.all()[:300])
    faqs = chatbot_services.public_faqs()
    return render(request, "home.html", {"gallery": _gallery_images(), "segments": segments,
                                         "hero_photos": hero_photos(segments),
                                         "faqs": faqs, "faq_jsonld": chatbot_services.faq_jsonld(faqs),
                                         "can_upload_photos": request.user.is_authenticated
                                                              and request.user.role in GALLERY_ROLES})


def work_photo(request, pk):
    """Entrega una foto de la galería de trabajos. Es pública (se ve en la portada), pero el navegador la
    guarda en su caché: el contenido de una foto nunca cambia."""
    photo = get_object_or_404(WorkPhoto, pk=pk)
    try:
        response = FileResponse(photo.image.open("rb"))
    except (FileNotFoundError, ValueError):
        raise Http404("Archivo no encontrado")
    response["Cache-Control"] = "public, max-age=86400"
    return response


def privacy(request):
    return render(request, "legal/privacy.html")


def terms(request):
    return render(request, "legal/terms.html")


@login_required
def post_login(request):
    """Destino tras iniciar sesión: el cliente vuelve a la página de inicio (con su chat
    flotante) y el personal entra directo a su lista de tickets."""
    if request.user.role == User.Role.CLIENTE:
        return redirect("home")
    return redirect("tickets:list")


@login_required
@role_required(User.Role.ADMIN)
def user_list(request):
    """Panel de administración de usuarios: solo el rol ADMIN puede listar y crear
    usuarios de cualquier rol (a diferencia de /registro/, que es público y solo crea clientes)."""
    if request.method == "POST":
        form = AdminCreateUserForm(request.POST)
        if form.is_valid():
            user = form.save()
            audit.log(request, AuditLog.Action.USUARIO_CREADO, user.username, f"rol {user.get_role_display()}")
            messages.success(request, "Usuario creado.")
            return redirect("accounts:users")
    else:
        form = AdminCreateUserForm()
    return render(request, "accounts/users.html", {"users": User.objects.all(), "form": form})


@login_required
@role_required(User.Role.ADMIN)
@require_POST
def user_toggle_active(request, pk):
    """Activa o desactiva una cuenta. Un usuario inactivo no puede iniciar sesión
    (Django lo bloquea automáticamente vía is_active), pero sus datos históricos se conservan."""
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "No puedes desactivar tu propia cuenta.")
    else:
        user.is_active = not user.is_active
        user.save()
        audit.log(request, AuditLog.Action.USUARIO_ESTADO, user.username, "activado" if user.is_active else "desactivado")
    return redirect("accounts:users")


@login_required
@role_required(User.Role.ADMIN)
def audit_list(request):
    """Registro de auditoría: quién hizo qué y cuándo (solo administrador)."""
    action = request.GET.get("accion", "")
    entries = AuditLog.objects.select_related("actor")
    if action in AuditLog.Action.values:
        entries = entries.filter(action=action)
    page_obj = Paginator(entries, 30).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "accounts/audit_list.html", {
        "page_obj": page_obj, "actions": AuditLog.Action.choices, "selected_action": action,
        "querystring": params.urlencode(),
    })


# ---- Galería de trabajos: el personal sube las fotos que se muestran en la portada ----

@login_required
@role_required(*GALLERY_ROLES)
def work_gallery(request):
    """Subir fotos de trabajos realizados y ver (o quitar) las ya subidas."""
    if request.method == "POST":
        form = WorkPhotoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            segment = form.cleaned_data["segment"]
            created = services.add_work_photos(request.user, segment, form.cleaned_data["caption"],
                                               form.cleaned_data["images"])
            for photo in created:
                audit.log(request, AuditLog.Action.FOTO_SUBIDA, f"foto #{photo.pk}", segment_title(segment))
            messages.success(request, "Foto subida: ya se ve en la portada." if len(created) == 1
                             else f"{len(created)} fotos subidas: ya se ven en la portada.")
            return redirect(f"{reverse('accounts:gallery')}?segmento={segment}")
    else:
        form = WorkPhotoUploadForm(initial={"segment": request.GET.get("segmento", "")})

    selected = request.GET.get("segmento", "")
    photos = WorkPhoto.objects.select_related("uploaded_by")
    if selected:
        photos = photos.filter(segment=selected)
    page_obj = Paginator(photos, GALLERY_PAGE_SIZE).get_page(request.GET.get("page"))
    for photo in page_obj:
        photo.segment_title = segment_title(photo.segment)
        photo.can_manage = services.can_manage_work_photo(request.user, photo)
        photo.edit_form = WorkPhotoEditForm(initial={"segment": photo.segment, "caption": photo.caption},
                                            auto_id=f"edit-{photo.pk}-%s") if photo.can_manage else None
    counts = dict(WorkPhoto.objects.order_by().values_list("segment").annotate(n=Count("id")))
    chips = [{"slug": slug, "title": title, "count": counts.get(slug, 0)} for slug, title in segment_choices()]
    return render(request, "accounts/gallery.html", {
        "form": form, "page_obj": page_obj, "selected": selected, "total": sum(counts.values()),
        "chips": chips, "querystring": f"segmento={selected}" if selected else "",
        "is_manager": request.user.role in (User.Role.ADMIN, User.Role.MODERADOR),
    })


def _back_to_gallery(request):
    """Vuelve a la página de la galería desde donde se hizo la acción (solo a direcciones del propio sitio)."""
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("accounts:gallery")


def _managed_photo_or_403(request, pk):
    photo = get_object_or_404(WorkPhoto, pk=pk)
    if not services.can_manage_work_photo(request.user, photo):
        raise PermissionDenied("Solo puedes cambiar las fotos que subiste tú")
    return photo


@login_required
@role_required(*GALLERY_ROLES)
@require_POST
def work_photo_edit(request, pk):
    photo = _managed_photo_or_403(request, pk)
    form = WorkPhotoEditForm(request.POST)
    if form.is_valid():
        photo.segment = form.cleaned_data["segment"]
        photo.caption = form.cleaned_data["caption"]
        photo.save(update_fields=["segment", "caption"])
        audit.log(request, AuditLog.Action.FOTO_EDITADA, f"foto #{photo.pk}", segment_title(photo.segment))
        messages.success(request, "Foto actualizada.")
    else:
        messages.error(request, "No se pudo guardar: revisa el segmento y el texto de la foto.")
    return _back_to_gallery(request)


@login_required
@role_required(*GALLERY_ROLES)
@require_POST
def work_photo_delete(request, pk):
    photo = _managed_photo_or_403(request, pk)
    target, detail = f"foto #{photo.pk}", segment_title(photo.segment)
    services.delete_work_photo(photo)
    audit.log(request, AuditLog.Action.FOTO_ELIMINADA, target, detail)
    messages.success(request, "Foto eliminada de la portada.")
    return _back_to_gallery(request)
