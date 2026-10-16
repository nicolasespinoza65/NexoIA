import time

from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.core import signing
from tickets.images import sanitize
from . import captcha
from .models import User
from .validators import validate_phone
from .works import segment_choices

FORM_TS_SALT = "register-form"


class RegisterForm(UserCreationForm):
    """Auto-registro: siempre crea un usuario con rol CLIENTE. Incluye defensas contra bots:
    un campo señuelo que las personas no ven, un cronómetro (un formulario enviado en menos de unos
    segundos no lo llenó una persona) y, si se configura, un CAPTCHA de Cloudflare Turnstile."""

    first_name = forms.CharField(label="Nombre", max_length=150)
    email = forms.EmailField(label="Correo")
    accept_terms = forms.BooleanField(
        label="Acepto los términos de uso y la política de privacidad",
        error_messages={"required": "Debes aceptar los términos y la política de privacidad para crear tu cuenta."},
    )
    website = forms.CharField(label="Sitio web", required=False,
                              widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))  # señuelo
    form_ts = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = User
        fields = ["first_name", "email", "username", "password1", "password2"]

    def __init__(self, *args, captcha_token="", ip="", **kwargs):
        super().__init__(*args, **kwargs)
        self.captcha_token = captcha_token
        self.ip = ip
        self.fields["form_ts"].initial = signing.dumps(time.time(), salt=FORM_TS_SALT)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("website"):
            raise forms.ValidationError("No pudimos procesar el registro.")
        if settings.REGISTER_MIN_SECONDS:
            try:
                started = signing.loads(cleaned.get("form_ts") or "", salt=FORM_TS_SALT, max_age=7200)
            except signing.BadSignature:
                raise forms.ValidationError("El formulario venció. Recarga la página e inténtalo de nuevo.")
            if time.time() - started < settings.REGISTER_MIN_SECONDS:
                raise forms.ValidationError("Enviaste el formulario demasiado rápido. Inténtalo de nuevo.")
        if settings.TURNSTILE_SECRET_KEY and not captcha.verify(self.captcha_token, self.ip):
            raise forms.ValidationError("No pudimos confirmar que eres una persona. Inténtalo de nuevo.")
        return cleaned

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo. Si es tuya, usa \"¿Olvidaste tu contraseña?\".")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.CLIENTE
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class AdminCreateUserForm(UserCreationForm):
    """Usado por el administrador: permite elegir cualquier rol."""

    first_name = forms.CharField(label="Nombre", max_length=150)
    email = forms.EmailField(label="Correo")

    class Meta:
        model = User
        fields = ["first_name", "email", "username", "role", "password1", "password2"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email_verified = True  # lo crea una persona de confianza
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    """Datos de contacto del usuario. El equipo los usa para coordinar las visitas."""

    first_name = forms.CharField(label="Nombre", max_length=150)
    phone = forms.CharField(label="Teléfono", max_length=30, required=False, validators=[validate_phone])
    address = forms.CharField(label="Dirección habitual", max_length=200, required=False)

    class Meta:
        model = User
        fields = ["first_name", "phone", "address"]


class TwoFactorForm(forms.Form):
    code = forms.CharField(
        label="Código de 6 dígitos", max_length=10,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "autofocus": True}),
    )


class PasswordConfirmForm(forms.Form):
    """Pide la contraseña actual antes de una acción delicada."""

    password = forms.CharField(label="Tu contraseña actual", widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("La contraseña no es correcta.")
        return password


class DeleteAccountForm(PasswordConfirmForm):
    confirm = forms.BooleanField(
        label="Entiendo que mi cuenta se eliminará y que esta acción no se puede deshacer",
        error_messages={"required": "Marca la casilla para confirmar."},
    )


# ---------- Galería de trabajos (fotos que sube el personal para la portada) ----------

MAX_WORK_PHOTO_MB = 5
MAX_WORK_PHOTOS_PER_UPLOAD = 10
CAPTION_HELP = "Se muestra bajo la foto. Si lo dejas vacío, se usa el título del segmento."


class MultipleFileInput(forms.FileInput):
    """Campo de archivos que permite elegir varias fotos a la vez."""
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """FileField que devuelve una lista de archivos (patrón de la documentación de Django para subidas múltiples)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            if not data and self.required:
                raise forms.ValidationError(self.error_messages["required"], code="required")
            return [single_clean(item, initial) for item in data]
        return [single_clean(data, initial)] if data else []


class WorkPhotoUploadForm(forms.Form):
    field_order = ["images", "segment", "caption"]  # primero la zona para elegir fotos
    segment = forms.ChoiceField(label="Segmento de trabajo", choices=())
    caption = forms.CharField(label="Texto bajo la foto (opcional)", max_length=200, required=False,
                              help_text=CAPTION_HELP)
    images = MultipleFileField(
        label="Fotos",
        widget=MultipleFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        error_messages={"required": "Elige al menos una foto."},
        help_text=f"JPG, PNG o WEBP, hasta {MAX_WORK_PHOTO_MB} MB cada una y {MAX_WORK_PHOTOS_PER_UPLOAD} por vez. "
                  "Se borran los datos de ubicación que traiga la foto.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["segment"].choices = segment_choices()

    def clean_caption(self):
        return self.cleaned_data["caption"].strip()

    def clean_images(self):
        files = self.cleaned_data["images"]
        if len(files) > MAX_WORK_PHOTOS_PER_UPLOAD:
            raise forms.ValidationError(f"Puedes subir hasta {MAX_WORK_PHOTOS_PER_UPLOAD} fotos por vez.")
        clean = []
        for item in files:
            if item.size > MAX_WORK_PHOTO_MB * 1024 * 1024:
                raise forms.ValidationError(f"«{item.name}» pesa más de {MAX_WORK_PHOTO_MB} MB.")
            try:
                clean.append(sanitize(item))  # valida el formato y borra EXIF/GPS
            except Exception:
                raise forms.ValidationError(f"«{item.name}» no es una foto válida. Usa JPG, PNG o WEBP.")
        return clean


class WorkPhotoEditForm(forms.Form):
    segment = forms.ChoiceField(label="Segmento de trabajo", choices=())
    caption = forms.CharField(label="Texto bajo la foto", max_length=200, required=False, help_text=CAPTION_HELP)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["segment"].choices = segment_choices()

    def clean_caption(self):
        return self.cleaned_data["caption"].strip()
