"""
Asistente IA. Flujo: Cliente -> asistente -> ¿resuelve?
  Pregunta básica (saludos, quién es, servicios, cómo crear un ticket o cotizar, estado, plazos, emergencia, horario, contacto)
      -> responde al tiro con datos de la empresa, sin gastar IA y sin crear ticket.
  Otra consulta que el modelo pueda responder -> responde y registra la interacción.
  No puede responder (precios, casos particulares) -> crea un ticket que revisa el moderador.
  Fuera de tema -> lo indica y no crea ticket.
Visitantes sin cuenta: solo preguntas básicas (ask_visitor), sin IA, sin historial y sin tickets.
"""
import json
import os
import re
import unicodedata
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone
from django.utils.safestring import mark_safe
from tickets.services import ACTIVE_STATUSES, create_ticket
from tickets.models import Ticket
from .models import ChatMessage, FaqEntry

MARK_OFF_TOPIC = "[FUERA_DE_TEMA]"
MARK_HANDOFF = "[DERIVAR]"
OFF_TOPIC_ANSWER = (
    "No puedo ayudarte con eso, porque no está dentro de mi entendimiento. Solo respondo consultas sobre "
    "Soluciones SSDP y sus servicios eléctricos: servicios, cotizaciones, tickets o emergencias."
)

SYSTEM_PROMPT = (
    "Eres el asistente virtual de Soluciones SSDP Servicios Integrales SpA, empresa de trabajos "
    "eléctricos de Talca, Chile. Responde en español, breve y amable, SOLO consultas relacionadas "
    "con la empresa y sus servicios eléctricos (tipos de servicio, tiempos y extensión estimados de "
    "los trabajos, estado general de solicitudes, cómo pedir un servicio). "
    "Los clientes piden un servicio creando un ticket desde «Nuevo ticket» en el menú: eligen una "
    "categoría (instalación, mantención o reparación, cotización, emergencia, reclamo, consulta general u otro), "
    "lo describen y, si quieren, adjuntan una foto. "
    f"Si la consulta no tiene relación con la empresa (cultura general, política, deportes, tareas escolares, "
    f"programación, chistes, opiniones u otros temas ajenos), responde exactamente: {MARK_OFF_TOPIC}. "
    "Si no puedes responder con certeza (precios, cotizaciones, fechas exactas, reclamos o casos "
    f"particulares), responde exactamente: {MARK_HANDOFF}. Nunca inventes precios, plazos ni compromisos."
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
# Tiempo máximo de espera de la IA: si tarda más, el caso se deriva a ticket en vez de dejar el servidor ocupado
ANTHROPIC_TIMEOUT = int(os.environ.get("ANTHROPIC_TIMEOUT", "15"))


# ---------------------------------------------------------------- datos de la empresa

def _company_facts():
    """Datos reales configurados en settings.COMPANY (variables de entorno). Lo vacío se omite."""
    c = settings.COMPANY
    facts = []
    if c.get("area"):
        facts.append(f"Zona de atención: {c['area']}.")
    if c.get("hours"):
        facts.append(f"Horario de atención: {c['hours']}.")
    if c.get("phone"):
        facts.append(f"Teléfono: {c['phone']}.")
    if c.get("whatsapp"):
        facts.append(f"WhatsApp: {c['whatsapp']}.")
    if c.get("email"):
        facts.append(f"Correo: {c['email']}.")
    if c.get("address"):
        facts.append(f"Dirección: {c['address']}.")
    return facts


def _system_prompt():
    facts = _company_facts()
    if not facts:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + " Datos oficiales de la empresa, que puedes compartir tal cual: " + " ".join(facts)


# ---------------------------------------------------------------- preguntas frecuentes

def _normalize(text):
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


_RE_HOW_TICKET = re.compile(r"\bcomo\b.*\b(cre\w+|abr\w+|gener\w+|hag\w+|hac\w+|levant\w+|envi\w+|pid\w+|pedir)\b.*\b(tickets?|solicitud\w*)\b")
_RE_HOW_QUOTE = re.compile(r"\bcomo\b.*\b(cotiz\w*|presupuest\w*)")
_RE_SERVICES = re.compile(r"\bque servicios\b|\bservicios (ofrec\w+|tienen|realizan|hacen)\b|\bque (es lo que )?(hace|hacen|ofrec\w+)\b|\ba que se dedic\w+")
_RE_HOURS = re.compile(r"\bhorarios?\b|\ba que hora (atienden|abren|cierran)\b|\bhasta que hora\b|\bque dias atienden\b")
_RE_CONTACT = re.compile(r"\b(telefono|whatsapp|numero de contacto|direccion)\b|\bcomo (los |las )?(contacto|contactar|comunico)\b|\bdonde (estan|queda\w*)\b")
_RE_WHO = re.compile(r"\bquien (eres|es)\b|\bque eres\b|\bcomo te llamas\b|\beres (un )?(robot|bot|persona|humano)\b")
_RE_HELP = re.compile(r"\ben que (me )?(puedes|puede|pueden) ayudar\b|\bque (puedes|sabes|pueden) hacer\b")
_RE_TRACK = re.compile(r"\bcomo\b.*\b(veo|ver|reviso|revisar|consulto|consultar|sigo|seguir)\b.*\b(estado|avance)\b|\b(estado|avance) (de|del) (mi|mis|el) (tickets?|solicitud\w*|caso)\b|\bdonde (veo|ver|encuentro)\b.*\b(tickets?|solicitud\w*)\b")
_RE_CATEGORIES = re.compile(r"\bque categorias\b|\bcategorias (hay|tienen|existen|son)\b|\btipos de (tickets?|solicitud\w*)\b")
_RE_TIMING = re.compile(r"\bcuanto (se )?(demora|demoran|tarda|tardan|dura|duran)\b|\bplazos?\b|\bcuando (vienen|llegan|van a venir)\b")
_RE_EMERGENCY = re.compile(r"\bque (hago|debo hacer|hacer)\b.*\b(emergencia|urgencia|chispa|corte|incendio|humo)\w*")

# Mensajes cortos formados solo por saludos, agradecimientos o despedidas
_GREET_WORDS = {"hola", "holi", "buenas", "buenos", "dias", "dia", "tardes", "noches", "hey", "saludos", "que", "tal", "como", "estas", "estan"}
_THANKS_KEY = {"gracias", "perfecto", "genial", "listo", "entendido", "excelente", "vale", "ok", "bacan"}
_THANKS_WORDS = _THANKS_KEY | {"muchas", "mil", "muy", "amable", "por", "todo", "la", "ayuda", "te", "lo", "agradezco", "super"}
_BYE_KEY = {"chao", "chau", "adios", "bye", "hasta", "luego", "vemos"}
_BYE_WORDS = _BYE_KEY | {"nos", "gracias", "que", "estes", "bien", "cuidate"}


def _only(words, vocabulary):
    return bool(words) and all(w in vocabulary for w in words)


def _db_faq_answer(q, words):
    """Respuestas que el administrador crea desde el panel. Se activan si la pregunta contiene alguna de
    sus palabras clave, o si es idéntica al título (así funcionan los botones de preguntas rápidas)."""
    plain = " ".join(words)
    for entry in FaqEntry.objects.filter(active=True):
        if " ".join(re.findall(r"[a-z0-9]+", _normalize(entry.title))) == plain:
            return entry.answer
        for keyword in entry.keywords.split(","):
            keyword = _normalize(keyword).strip()
            if len(keyword) >= 3 and re.search(r"\b" + re.escape(keyword) + r"\b", q):
                return entry.answer
    return None


def _faq_answer(question):
    """Respuesta fija a las preguntas más básicas, o None si hay que pasar por el modelo / ticket."""
    q = _normalize(question)
    words = re.findall(r"[a-z]+", q)
    c = settings.COMPANY

    custom = _db_faq_answer(q, re.findall(r"[a-z0-9]+", q))
    if custom is not None:  # las respuestas del administrador tienen prioridad sobre las del código
        return custom

    # --- conversación básica (mensajes cortos)
    if len(words) <= 4 and _only(words, _GREET_WORDS):
        return ("¡Hola! Soy el asistente virtual de Soluciones SSDP. Puedo contarte sobre nuestros servicios, "
                "cómo crear un ticket o cómo pedir una cotización. ¿En qué te ayudo?")
    if len(words) <= 6 and _only(words, _THANKS_WORDS) and set(words) & _THANKS_KEY:
        return "¡De nada! Si necesitas algo más, aquí estoy."
    if len(words) <= 6 and _only(words, _BYE_WORDS) and set(words) & _BYE_KEY:
        return "¡Hasta luego! Cuando quieras, vuelve a escribirme."
    if _RE_WHO.search(q):
        return ("Soy el asistente virtual de Soluciones SSDP Servicios Integrales SpA. Respondo dudas básicas sobre "
                "nuestros servicios eléctricos y, si no puedo resolver algo, dejo un ticket para que lo revise el equipo.")
    if _RE_HELP.search(q) or words in (["ayuda"], ["ayudame"], ["help"]):
        return ("Puedo ayudarte con: qué servicios ofrecemos, cómo crear un ticket, cómo pedir una cotización, "
                "cómo ver el estado de tus solicitudes y cuánto demora un trabajo. Si tu caso es particular, "
                "lo dejo como ticket para el equipo.")

    # --- seguridad primero
    if _RE_EMERGENCY.search(q) or (len(words) <= 4 and "emergencia" in words):
        return ("Si hay riesgo inmediato para las personas (fuego, humo o descargas), aléjate de la zona y llama a "
                "Bomberos (132). Si no hay riesgo inmediato, crea un ticket con la categoría «Emergencia»: "
                "entra con prioridad alta y el equipo lo ve de inmediato.")

    # --- cómo usar la plataforma
    if _RE_HOW_TICKET.search(q):
        return ("Para crear un ticket entra a «Nuevo ticket» en el menú, elige la categoría, cuéntanos qué ocurre "
                "y, si quieres, adjunta una foto. Un moderador lo revisa y te avisamos por notificación y correo "
                "cada vez que cambie su estado.")
    if _RE_HOW_QUOTE.search(q):
        return ("Para pedir una cotización crea un ticket con la categoría «Cotización» y describe qué necesitas "
                "y dónde (una foto ayuda). Un moderador revisará tu caso y te responderá; por este chat no entregamos precios.")
    if _RE_TRACK.search(q):
        return ("Puedes ver tus solicitudes en «Mis tickets», en el menú superior: ahí está el estado de cada una "
                "y puedes dejar comentarios. También te avisamos en «Notificaciones» y por correo cuando algo cambia.")
    if _RE_CATEGORIES.search(q):
        return ("Los tickets se clasifican en: instalación eléctrica, mantención o reparación, cotización, emergencia, "
                "reclamo, consulta general y otro. Eliges la categoría al crear el ticket.")
    if _RE_TIMING.search(q):
        return ("El plazo depende del tipo de trabajo, así que no comprometemos fechas por chat. "
                "Un moderador te informa los tiempos cuando revisa tu ticket.")

    # --- la empresa
    if _RE_SERVICES.search(q):
        text = ("Realizamos trabajos eléctricos: instalaciones eléctricas, mantención y reparación, "
                "cotizaciones y atención de emergencias.")
        if c.get("area"):
            text += f" Atendemos en {c['area']}."
        return text + " Si quieres pedir uno, crea un ticket desde «Nuevo ticket»."
    if _RE_HOURS.search(q) and c.get("hours"):
        return f"Nuestro horario de atención es: {c['hours']}."
    if _RE_CONTACT.search(q):
        facts = [f for f in _company_facts() if not f.startswith(("Horario", "Zona"))]
        if facts:
            return "Puedes contactarnos así. " + " ".join(facts)
    return None


# Términos que delatan una consulta propia de la empresa o de la plataforma (ya normalizados, sin tildes).
_RELATED = re.compile(
    r"\b(electric\w*|luz|luces|enchuf\w*|interruptor\w*|tablero\w*|cable\w*|cableado|corriente|voltaje|"
    r"medidor\w*|empalme\w*|subestacion\w*|transformador\w*|ampolleta\w*|lampara\w*|iluminacion|alumbrado|"
    r"automatico\w*|diferencial\w*|generador\w*|solar\w*|paneles?|fusible\w*|"
    r"cortocircuito\w*|corte\w*|apagon\w*|chispa\w*|falla\w*|quemo|quemado\w*|"
    r"instal\w*|mantencion\w*|mantenimiento|repar\w*|arregl\w*|emergencia\w*|urgencia\w*|"
    r"cotiz\w*|presupuesto\w*|precio\w*|costo\w*|cuesta\w*|tarifa\w*|cobr\w*|"
    r"tickets?|solicitud\w*|reclamo\w*|servicio\w*|trabajo\w*|visita\w*|tecnico\w*|"
    r"empresa|ssdp|soluciones|talca|horario\w*|atienden|atencion|contacto|telefono|whatsapp|correo|direccion|"
    r"cuenta|registr\w*|cliente\w*|plataforma|notificacion\w*|calific\w*|acondicionado|climatizacion|"
    r"camara\w*|alarma\w*|citofono\w*|porton\w*|"
    r"ayuda|ayudame|ayudar|problema\w*|consulta\w*|urgente\w*|humano|persona|asesor\w*|agend\w*|cita|"
    r"casa|hogar|taller|negocio|oficina|edificio|obra|bodega)\b"
)
_SMALL_TALK = _GREET_WORDS | _THANKS_WORDS | _BYE_WORDS | {
    "si", "no", "claro", "dale", "eso", "es", "nada", "mas", "ya", "bien", "bueno", "favor", "tambien"}


_RE_MATH = re.compile(r"\d\s*[+\-*/x×÷^]\s*\d|\bcuanto es\b|\braiz\b")


def _is_off_topic(question):
    """True si la consulta claramente no tiene relación con la empresa (matemáticas, cultura general, chistes...).
    Es una regla local y conservadora: la charla de cortesía, los mensajes sin letras ni números (emojis) y
    cualquier término del rubro devuelven False."""
    q = _normalize(question)
    words = re.findall(r"[a-z0-9]+", q)
    if not words or _only(words, _SMALL_TALK):
        return False
    if _RE_MATH.search(q):
        return True
    if all(w.isdigit() for w in words):  # un teléfono o un número de ticket suelto no es un tema ajeno
        return False
    return not _RELATED.search(q)


def suggestions(authenticated=True):
    """Preguntas rápidas que el chat ofrece al abrirse (todas tienen respuesta directa).
    A los visitantes sin cuenta no se les ofrece la del estado del ticket, porque aún no tienen tickets."""
    items = ["¿Qué servicios ofrecen?", "¿Cómo creo un ticket?", "¿Cómo pido una cotización?"]
    if authenticated:
        items.append("¿Cómo veo el estado de mi ticket?")
    if settings.COMPANY.get("hours"):
        items.append("¿Cuál es el horario de atención?")
    items += list(FaqEntry.objects.filter(active=True, suggested=True).values_list("title", flat=True))
    return items[:6]


def public_faqs():
    """Preguntas frecuentes para mostrar en la portada: las respuestas activas que el administrador cargó desde
    el panel «Respuestas». Primero las marcadas como sugeridas y luego el resto, por orden alfabético."""
    return list(FaqEntry.objects.filter(active=True).order_by("-suggested", "title").values("id", "title", "answer"))


def faq_jsonld(faqs):
    """Datos estructurados schema.org (FAQPage) de las preguntas de la portada, para que los buscadores las
    entiendan. Devuelve el JSON listo para ir dentro de <script type="application/ld+json">: los caracteres
    <, > y & se escapan para que un texto con «</script>» no pueda romper la página."""
    data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": f["title"], "acceptedAnswer": {"@type": "Answer", "text": f["answer"]}}
            for f in faqs
        ],
    }
    text = json.dumps(data, ensure_ascii=False)
    return mark_safe(text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


# ---------------------------------------------------------------- flujo principal

def ask(client, question):
    faq = _faq_answer(question)
    if faq is not None:
        ChatMessage.objects.create(client=client, question=question, answer=faq, resolved_by_ai=True)
        return {"answer": faq, "ticket_id": None}

    # Sin IA configurada nadie más juzga el tema: un asunto ajeno a la empresa se rechaza aquí en vez de
    # convertirse en ticket. (Con IA, el modelo decide con [FUERA_DE_TEMA].)
    if not ANTHROPIC_API_KEY and _is_off_topic(question):
        ChatMessage.objects.create(client=client, question=question, answer=OFF_TOPIC_ANSWER, resolved_by_ai=False)
        return {"answer": OFF_TOPIC_ANSWER, "ticket_id": None}

    # A partir de aquí la consulta puede costar dinero (IA) o crear un ticket: se aplican los límites.
    if not client.email_verified:
        return {"answer": ("Para usar el asistente completo, confirma tu correo con el enlace que te enviamos "
                           "(puedes pedir otro desde tu perfil). Mientras tanto puedes crear tu solicitud con «Nuevo ticket»."),
                "ticket_id": None}
    if _over_limit(client):
        return {"answer": ("Alcanzaste el límite de mensajes por hora. Espera un rato o crea tu solicitud "
                           "directamente con «Nuevo ticket»."),
                "ticket_id": None}

    raw = _call_model(client, question)
    ticket_id = None

    would_ticket = raw is None or MARK_HANDOFF in raw
    # El modelo a veces antepone texto al marcador. Y si iba a derivar a ticket (o falló) pero la consulta no tiene
    # nada que ver con la empresa, se rechaza en vez de molestar al equipo con un ticket.
    if (raw is not None and MARK_OFF_TOPIC in raw) or (would_ticket and _is_off_topic(question)):
        answer = OFF_TOPIC_ANSWER
        resolved = False
    elif would_ticket:
        title = (question[:60] + "...") if len(question) > 60 else question
        ticket = create_ticket(client, title, question, source=Ticket.Source.IA)
        ticket_id = ticket.id
        answer = (
            f"No puedo resolver esta consulta por mi cuenta, así que generé el ticket #{ticket.id}. "
            "Un moderador la revisará y te avisaremos por notificación."
        )
        resolved = False
    else:
        answer = raw
        resolved = True

    ChatMessage.objects.create(client=client, question=question, answer=answer, resolved_by_ai=resolved)
    return {"answer": answer, "ticket_id": ticket_id}


HUMAN_TITLE = "Solicitud de atención de una persona"
_STOPWORDS = {"que", "para", "como", "donde", "cuando", "tengo", "tiene", "tienen", "hacen", "puedo", "quiero",
              "necesito", "esta", "este", "estoy", "unos", "unas", "desde", "hasta", "pero", "porque", "sobre",
              "entre", "cual", "cuales", "algun", "alguna", "ustedes", "hola", "buenas", "favor", "gracias"}


def request_human(client):
    """El cliente pide hablar con una persona: se crea un ticket con el contexto de la conversación y se avisa a los
    moderadores. Si ya tiene una solicitud así abierta, no se duplica. Devuelve (ticket, creado)."""
    since = timezone.now() - timedelta(hours=12)
    existing = Ticket.objects.filter(client=client, title=HUMAN_TITLE, status__in=ACTIVE_STATUSES,
                                     created_at__gte=since).first()
    if existing:
        return existing, False
    last = list(ChatMessage.objects.filter(client=client).order_by("-id")[:5])[::-1]
    conversation = "\n".join(f"Cliente: {m.question}\nAsistente: {m.answer}" for m in last) or "(sin conversación previa)"
    description = ("El cliente pidió hablar con una persona desde el chat.\n\nÚltimos mensajes:\n" + conversation)[:2000]
    ticket = create_ticket(client, HUMAN_TITLE, description, source=Ticket.Source.IA, category=Ticket.Category.CONSULTA)
    return ticket, True


def suggest_keywords(question):
    """Palabras clave sugeridas para convertir una pregunta sin respuesta en una respuesta editable."""
    words = [w for w in re.findall(r"[a-z0-9]+", _normalize(question)) if len(w) >= 4 and w not in _STOPWORDS]
    unique = list(dict.fromkeys(words))
    return ", ".join(unique[:3])


def unanswered_questions(limit=300):
    """Preguntas de clientes que el asistente no supo responder (se derivaron a ticket o quedaron fuera de tema),
    agrupadas y ordenadas por frecuencia. Desaparecen solas cuando ya existe una respuesta que las cubre."""
    messages = ChatMessage.objects.filter(resolved_by_ai=False, reviewed=False).order_by("-id")[:limit]
    groups = {}
    for message in messages:
        key = " ".join(re.findall(r"[a-z0-9]+", _normalize(message.question)))
        if not key:
            continue
        group = groups.setdefault(key, {"question": message.question, "count": 0, "last": message.created_at, "ids": []})
        group["count"] += 1
        group["ids"].append(message.id)
    result = [g for g in groups.values() if _faq_answer(g["question"]) is None]
    for group in result:
        group["keywords"] = suggest_keywords(group["question"])
        group["ids_text"] = ",".join(str(i) for i in group["ids"])
    return sorted(result, key=lambda g: (-g["count"], g["question"]))


def _over_limit(client):
    """Tope de mensajes por cliente y hora (CHAT_MAX_PER_HOUR): protege el gasto de la IA y evita tickets en masa."""
    since = timezone.now() - timedelta(hours=1)
    return ChatMessage.objects.filter(client=client, created_at__gte=since).count() >= settings.CHAT_MAX_PER_HOUR


def ask_visitor(question):
    """Chat para visitantes sin cuenta: solo preguntas básicas (las mismas respuestas fijas de _faq_answer).
    No guarda nada, no crea tickets y NO llama a la IA, así nadie puede gastar la clave de API desde afuera.
    Si la consulta necesita registrarse (una falla, una cotización), se le pide ingresar o crear una cuenta."""
    faq = _faq_answer(question)
    if faq is not None:
        if "ticket" in faq.lower():
            faq += " Para crear tickets necesitas ingresar o crear una cuenta de cliente."
        return {"answer": faq, "needs_account": False}
    if _is_off_topic(question):  # no tiene sentido pedirle una cuenta a quien pregunta algo ajeno a la empresa
        return {"answer": OFF_TOPIC_ANSWER, "needs_account": False}
    return {
        "answer": ("Para ayudarte con eso necesito registrar tu consulta, y para eso debes ingresar o crear una "
                   "cuenta de cliente. Así el equipo puede responderte y seguir tu caso."),
        "needs_account": True,
    }


def _call_model(client, question):
    """Llama a la API de Anthropic incluyendo las últimas 6 interacciones como contexto.
    Sin ANTHROPIC_API_KEY configurada, toda consulta se deriva a ticket (modo seguro por defecto)."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        history = list(
            ChatMessage.objects.filter(client=client).order_by("-id")[:6]
        )[::-1]
        messages = []
        for h in history:
            messages.append({"role": "user", "content": h.question})
            messages.append({"role": "assistant", "content": h.answer})
        messages.append({"role": "user", "content": question})

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "content-type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json={"model": ANTHROPIC_MODEL, "max_tokens": 500, "system": _system_prompt(), "messages": messages},
            timeout=ANTHROPIC_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        return resp.json()["content"][0]["text"].strip()
    except Exception:
        return None  # ante cualquier falla, el caso se deriva a un humano
