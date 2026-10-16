from django import forms
from .models import FaqEntry


class FaqEntryForm(forms.ModelForm):
    """Respuesta del asistente que el administrador puede crear o editar sin tocar el código."""

    class Meta:
        model = FaqEntry
        fields = ["title", "keywords", "answer", "suggested", "active"]
        labels = {
            "title": "Título",
            "keywords": "Palabras clave",
            "answer": "Respuesta",
            "suggested": "Mostrar como pregunta rápida en el chat",
            "active": "Activa",
        }
        help_texts = {
            "title": "Nombre de la respuesta. Si la muestras como pregunta rápida, este es el texto del botón (ej. ¿Hacen visitas a domicilio?).",
            "keywords": "Frases separadas por coma que activan esta respuesta (ej. visita, a domicilio, van a mi casa).",
            "answer": "Lo que responderá el asistente. Máximo 1.000 caracteres.",
        }
        widgets = {"answer": forms.Textarea(attrs={"rows": 4})}

    def clean_keywords(self):
        keywords = [k.strip() for k in self.cleaned_data["keywords"].split(",")]
        keywords = [k for k in keywords if len(k) >= 3]
        if not keywords:
            raise forms.ValidationError("Escribe al menos una palabra clave de 3 letras o más, separadas por coma.")
        return ", ".join(keywords)
