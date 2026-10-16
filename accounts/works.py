"""Apartado "Trabajos por segmento" de la portada.

Cada segmento corresponde a una carpeta dentro de ``static/img/trabajos/<slug>/``. Para agregar una foto basta con
copiarla en la carpeta del segmento (se ordenan por nombre, por eso conviene prefijar 01-, 02-, ...). Si quieres que
tenga un texto propio, añade su nombre de archivo en ``captions``; si no, se usa el título del segmento.
Un segmento sin fotos no se muestra, salvo los marcados con ``show_without_photos``.

Además, el personal puede subir fotos desde el sitio (apartado "Galería", modelo ``WorkPhoto``): se guardan en
``media/trabajos/`` y se muestran en su segmento antes que las incluidas, las más recientes primero.
"""
from functools import lru_cache
from pathlib import Path

from django.templatetags.static import static
from django.urls import reverse

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS_PER_SEGMENT = 12           # fotos incluidas en static/img/trabajos/<segmento>/
MAX_UPLOADED_PER_SEGMENT = 24         # fotos subidas desde el sitio que se muestran por segmento
STATIC_PREFIX = "img/trabajos"

SEGMENTS = [
    {
        "slug": "subestacion-500kva",
        "title": "Subestación con transformador de 500 kVA",
        "description": "Instalación de una subestación con transformador de 500 kVA para un supermercado.",
        "captions": {
            "01-vista-general.jpg": "Subestación con transformador de 500 kVA, vista general",
            "02-transformador.jpg": "Transformador de 500 kVA: aisladores y conexiones",
            "03-caja-de-bornes.jpg": "Caja de bornes del transformador con cables rotulados",
        },
    },
    {
        "slug": "supermercado",
        "title": "Instalación eléctrica de supermercado",
        "note": "Obra en proceso",
        "description": "Instalación eléctrica de un supermercado: iluminación interior y exterior, bandejas "
                       "portacables y luminarias estancas.",
        "captions": {
            "01-bodega-luminarias.jpg": "Bodega con luminarias colgantes y bandejas portacables",
            "02-zona-techada.jpg": "Zona techada con luminarias y acceso a la bodega",
            "03-cielo-luminarias-estancas.jpg": "Luminarias estancas y canalización en cielo",
            "04-iluminacion-exterior-pasillo.jpg": "Iluminación exterior en pasillo lateral",
            "05-patio-postes.jpg": "Patio exterior con iluminación en postes",
        },
    },
    {
        "slug": "casa-habitacion",
        "title": "Instalación eléctrica en casa habitación",
        "description": "Instalación eléctrica de una vivienda: iluminación interior y exterior, enchufes y "
                       "tablero con circuitos rotulados.",
        "captions": {
            "01-living-vigas.jpg": "Living con vigas a la vista y lámparas colgantes",
            "02-fachada-apliques.jpg": "Fachada con apliques de iluminación exterior",
            "03-habitacion-apliques.jpg": "Habitación con apliques de pared",
            "04-tablero-electrico.jpg": "Tablero eléctrico con circuitos rotulados",
        },
    },
    {
        "slug": "empalme-monofasico",
        "title": "Empalme monofásico con línea",
        "description": "Construcción de empalmes monofásicos con línea, con medidor y canalización.",
        "captions": {
            "01-empalme-poste-medidor.jpg": "Empalme con caja de medidor instalada en poste",
            "02-tablero-control-poste.jpg": "Tablero de control sobre poste, con canalización metálica",
            "03-medidores-en-poste.jpg": "Medidores instalados en poste, con canalización",
        },
    },
    {
        "slug": "aire-acondicionado",
        "title": "Equipos de aire acondicionado",
        "description": "Instalación de equipos de aire acondicionado: unidad exterior sobre soportes, "
                       "conexiones y drenaje.",
        "captions": {
            "01-unidad-exterior-muro.jpg": "Unidad exterior montada en soporte sobre el muro",
            "02-unidad-soporte-drenaje.jpg": "Unidad exterior sobre soporte, con drenaje y cableado",
            "03-detalle-conexiones.jpg": "Detalle de las conexiones y los soportes de la unidad exterior",
            "04-unidad-soportes.jpg": "Unidad exterior con soportes de fijación",
        },
    },
    {
        "slug": "informes-certificaciones",
        "title": "Informes y certificaciones de verificación inicial",
        "description": "Informe y certificaciones de verificación inicial de la instalación eléctrica.",
        "captions": {},
        "show_without_photos": True,
    },
]


@lru_cache(maxsize=256)
def _cached_size(path, mtime_ns):
    from PIL import Image  # Pillow ya es dependencia del proyecto (fotos de los tickets)
    with Image.open(path) as im:
        return im.size


def _image_size(path):
    """Ancho y alto de la foto (el navegador reserva el espacio antes de cargarla). None si no se puede leer."""
    try:
        return _cached_size(str(path), path.stat().st_mtime_ns)
    except Exception:
        return None


def photo_orientation(width, height):
    """"portrait" (vertical), "wide" (panorámica) o "landscape" (horizontal normal); "" si no se conoce el tamaño.

    La plantilla la usa para encuadrar cada foto sin recortarla de forma brusca (ver .photo-frame en style.css).
    """
    if not width or not height:
        return ""
    ratio = width / height
    if ratio < 0.9:
        return "portrait"
    if ratio > 1.7:
        return "wide"
    return "landscape"


def segment_choices():
    """Lista (slug, título) de los segmentos, para los formularios de la galería."""
    return [(seg["slug"], seg["title"]) for seg in SEGMENTS]


def segment_title(slug):
    for seg in SEGMENTS:
        if seg["slug"] == slug:
            return seg["title"]
    return slug


def load_segments(base_dir, uploaded=()):
    """Devuelve los segmentos a mostrar, cada uno con sus fotos.

    ``base_dir`` es static/img/trabajos (fotos incluidas). ``uploaded`` son las ``WorkPhoto`` subidas desde el
    sitio, de la más reciente a la más antigua; las de un segmento que ya no existe en ``SEGMENTS`` se ignoran.
    Cada foto trae ``url`` (lista para usar en ``src``) y ``uploaded`` (True si la subió el personal).
    """
    base_dir = Path(base_dir)
    by_segment = {}
    for work in uploaded:
        by_segment.setdefault(work.segment, []).append(work)

    result = []
    for seg in SEGMENTS:
        folder = base_dir / seg["slug"]
        photos = []
        for work in by_segment.get(seg["slug"], [])[:MAX_UPLOADED_PER_SEGMENT]:
            photos.append({
                "id": work.pk,
                "path": "",
                "url": reverse("accounts:work_photo", args=[work.pk]),
                "caption": work.caption or seg["title"],
                "width": work.width,
                "height": work.height,
                "orient": photo_orientation(work.width, work.height),
                "uploaded": True,
            })
        if folder.is_dir():
            names = sorted(f.name for f in folder.iterdir()
                           if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS)
            for name in names[:MAX_PHOTOS_PER_SEGMENT]:
                size = _image_size(folder / name)
                path = f"{STATIC_PREFIX}/{seg['slug']}/{name}"
                photos.append({
                    "id": None,
                    "path": path,
                    "url": static(path),
                    "caption": seg["captions"].get(name, seg["title"]),
                    "width": size[0] if size else None,
                    "height": size[1] if size else None,
                    "orient": photo_orientation(*size) if size else "",
                    "uploaded": False,
                })
        if photos or seg.get("show_without_photos"):
            result.append({
                "slug": seg["slug"],
                "title": seg["title"],
                "note": seg.get("note", ""),
                "description": seg["description"],
                "photos": photos,
            })
    return result


def hero_photos(segments, limit=3):
    """Fotos de la portada: la primera foto incluida (no subida) de cada uno de los primeros segmentos."""
    chosen = []
    for seg in segments:
        photo = next((p for p in seg["photos"] if not p["uploaded"]), None)
        if photo:
            chosen.append({**photo, "segment": seg["title"]})
        if len(chosen) == limit:
            break
    return chosen
