"""Limpieza de las fotos que suben los usuarios.

Las fotos tomadas con un celular traen metadatos (EXIF) que pueden incluir las coordenadas GPS exactas de
donde se tomaron: en este sistema, el domicilio del cliente. Antes de guardar cualquier foto se vuelve a
dibujar sin esos datos, se corrige la orientación y se reduce si es muy grande."""
import io
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_SIDE = 2400  # píxeles del lado más largo


def sanitize(uploaded):
    """Devuelve un archivo nuevo con la misma foto, sin metadatos. Lanza ValueError si no es JPEG, PNG o WEBP."""
    uploaded.seek(0)
    try:
        image = Image.open(uploaded)
        image_format = image.format
        if image_format not in ALLOWED_FORMATS:
            raise ValueError("Formato de imagen no permitido")
        image.load()
    except (OSError, SyntaxError) as error:
        raise ValueError("Archivo de imagen inválido") from error

    image = ImageOps.exif_transpose(image)  # aplica la rotación que indicaba el celular
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    if image_format == "JPEG" and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    image.info = {}  # descarta EXIF, GPS, comentarios y cualquier otro dato asociado

    buffer = io.BytesIO()
    options = {"JPEG": {"quality": 88, "optimize": True}, "PNG": {"optimize": True}, "WEBP": {"quality": 88}}[image_format]
    image.save(buffer, format=image_format, **options)
    return ContentFile(buffer.getvalue(), name=Path(uploaded.name).name)
