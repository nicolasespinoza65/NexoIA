from django import forms
from django.utils import timezone
from accounts.validators import validate_phone
from . import images
from .models import Ticket

MAX_IMAGE_MB = 5


def check_photo(image):
    """Valida una foto subida: pesa menos de 5 MB y es JPG, PNG o WEBP (otros formatos, como GIF, se rechazan)."""
    if not image:
        return image
    if image.size > MAX_IMAGE_MB * 1024 * 1024:
        raise forms.ValidationError(f"La foto no puede pesar más de {MAX_IMAGE_MB} MB.")
    detected = getattr(getattr(image, "image", None), "format", None)  # Django ya la abrió con Pillow
    if detected not in images.ALLOWED_FORMATS:
        raise forms.ValidationError("Usa una foto en formato JPG, PNG o WEBP.")
    return image


class TicketForm(forms.Form):
    title = forms.CharField(label="Asunto", max_length=120)
    category = forms.ChoiceField(label="Categoría", choices=Ticket.Category.choices)
    description = forms.CharField(
        label="Descripción",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Cuéntanos qué ocurre, dónde y desde cuándo.",
    )
    phone = forms.CharField(
        label="Teléfono de contacto", max_length=30, validators=[validate_phone],
        help_text="Para coordinar la visita.",
    )
    address = forms.CharField(
        label="Dirección del trabajo", max_length=200,
        help_text="Calle, número y comuna donde se realizará el trabajo.",
    )
    image = forms.ImageField(
        label="Foto (opcional)",
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/*"}),
        help_text="Una foto del tablero o de la falla ayuda a priorizar tu caso. Máximo 5 MB.",
    )

    def clean_image(self):
        return check_photo(self.cleaned_data.get("image"))


class AssignForm(forms.Form):
    worker_id = forms.IntegerField(widget=forms.Select)
    priority = forms.ChoiceField(choices=Ticket.Priority.choices)


class CommentForm(forms.Form):
    text = forms.CharField(label="Comentario", max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))


class RatingForm(forms.Form):
    """Encuesta de satisfacción que el cliente responde cuando su ticket se cierra."""

    rating = forms.TypedChoiceField(
        label="¿Cómo calificas la atención?",
        choices=[(5, "5 · Excelente"), (4, "4 · Buena"), (3, "3 · Regular"), (2, "2 · Mala"), (1, "1 · Muy mala")],
        coerce=int,
    )
    comment = forms.CharField(label="Comentario (opcional)", max_length=300, required=False,
                              widget=forms.Textarea(attrs={"rows": 2}))


class WorkPhotoForm(forms.Form):
    """Foto del trabajo realizado, que sube el trabajador (o el personal) desde terreno."""

    image = forms.ImageField(label="Foto del trabajo", widget=forms.FileInput(attrs={"accept": "image/*"}))
    caption = forms.CharField(label="Descripción (opcional)", max_length=200, required=False)

    def clean_image(self):
        return check_photo(self.cleaned_data.get("image"))


class CloseForm(forms.Form):
    """Nota que el trabajador deja al cerrar el ticket; el cliente puede leerla."""

    note = forms.CharField(label="Nota de cierre (opcional)", max_length=500, required=False,
                           widget=forms.Textarea(attrs={"rows": 3}),
                           help_text="Qué se hizo y cualquier recomendación para el cliente.")


class QuoteForm(forms.Form):
    detail = forms.CharField(label="Qué incluye la cotización", max_length=1500, widget=forms.Textarea(attrs={"rows": 4}))
    amount = forms.IntegerField(label="Monto total (pesos chilenos)", min_value=1, max_value=1_000_000_000)
    valid_until = forms.DateField(label="Válida hasta", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                                  input_formats=["%Y-%m-%d"])

    def clean_valid_until(self):
        value = self.cleaned_data["valid_until"]
        if value < timezone.localdate():
            raise forms.ValidationError("La fecha de vigencia no puede ser anterior a hoy.")
        return value


class VisitForm(forms.Form):
    visit_at = forms.DateTimeField(
        label="Fecha y hora de la visita",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    visit_note = forms.CharField(label="Indicaciones (opcional)", max_length=200, required=False,
                                 help_text="Por ejemplo: llamar al llegar, portón verde.")

    def clean_visit_at(self):
        value = self.cleaned_data["visit_at"]
        if value <= timezone.now():
            raise forms.ValidationError("La visita debe ser en el futuro.")
        return value


class QuoteResponseForm(forms.Form):
    comment = forms.CharField(label="Comentario (opcional)", max_length=300, required=False,
                              widget=forms.Textarea(attrs={"rows": 2}))
