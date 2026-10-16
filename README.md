# NexoIA (versión Django) — Soluciones SSDP

Misma plataforma que la versión en Java/Spring Boot, reescrita en **Python/Django**.
Mantiene los mismos 4 roles, el mismo flujo de tickets y el mismo asistente IA
acotado a temas de la empresa.

## Novedades de esta versión

**Página y chat**
- **Página de inicio pública** (`templates/home.html`): presenta la empresa, las categorías de servicio, cómo funciona
  el seguimiento y, si se configuran, los datos de contacto.
- **Datos reales de la empresa**: teléfono, WhatsApp, correo, horario, zona y dirección se definen con variables de
  entorno (`COMPANY_PHONE`, `COMPANY_WHATSAPP`, `COMPANY_EMAIL`, `COMPANY_HOURS`, `COMPANY_AREA`, `COMPANY_ADDRESS`; ver
  `.env.example`). Lo que quede vacío no se muestra. El asistente usa estos mismos datos para responder.
- **Chat flotante** (`templates/partials/chat_widget.html` + `static/js/chat.js`): burbuja en la esquina inferior
  derecha para clientes (los visitantes ven una invitación a ingresar). Al abrirse ofrece preguntas rápidas y responde
  sin recargar. Endpoints JSON: `/asistente/historial/` y `/asistente/enviar/`.
- **Chat sin cuenta**: los visitantes pueden preguntar lo básico en `/asistente/visitante/` (sin IA, sin historial y sin
  crear tickets). Las preguntas rápidas reaparecen tras cada respuesta mientras queden sin usar; al agotarlas se invita a
  registrarse. Si su consulta necesita registro, el asistente les ofrece ingresar o crear una cuenta.
- **Preguntas básicas sin IA** (`chatbot/services.py`): saludos, agradecimientos, quién es el asistente, servicios, cómo crear
  un ticket o pedir una cotización, cómo ver el estado, categorías, plazos, qué hacer en una emergencia (Bomberos 132), horario
  y contacto se responden al tiro, sin crear ticket y aunque no haya `ANTHROPIC_API_KEY`. Si el mensaje trae una necesidad real
  ("hola, necesito cotizar un tablero"), sigue el flujo normal y se deriva a ticket.

**Tickets**
- **Categoría** (instalación, mantención o reparación, cotización, emergencia, reclamo, consulta general, otro). El
  cliente la elige; los tickets del asistente se clasifican por palabras clave y moderador/administrador pueden corregirla.
- **Emergencias con prioridad alta** automática, destacadas en rojo en la lista y con aviso `[URGENTE]`.
- **Foto opcional** (hasta 5 MB). Se guarda en `media/` y solo la ve quien puede ver el ticket (no es un archivo público).
- **Búsqueda, filtros y paginación** (15 por página) para moderadores y administradores, y **exportación a CSV** que
  Excel abre directamente (separador `;`, respeta los filtros activos).
- **Correo automático**: cada notificación también llega por email a quien tenga correo registrado. Por defecto los
  correos se imprimen en la terminal (modo prueba); para enviarlos de verdad configura `EMAIL_*` en `.env.example`.
- **Eliminar tickets**: solo el administrador, con confirmación, desde la lista o el detalle. Se borran también sus
  comentarios y su foto. No se puede deshacer.
- Los administradores y moderadores reciben aviso de cada ticket nuevo; si un cliente comenta un ticket sin trabajador,
  el aviso va a los moderadores.

**Administración y calidad**
- **Indicadores**: tickets por estado y categoría, tickets nuevos por semana (8 semanas) y tiempo medio de resolución.
- Tras **registrarse**, el cliente queda con la sesión iniciada y entra directo a crear su primer ticket.
- Las acciones que modifican datos (cambiar estado, activar/desactivar usuario, marcar notificaciones) ahora son **POST**;
  un administrador no puede desactivar su propia cuenta. El botón **Salir** también es POST (obligatorio en Django 5+).
- **`seed_users` genera contraseñas aleatorias** (se muestran una sola vez). Para desarrollo local con contraseñas
  simples usa `python manage.py seed_users --demo`. Cambiar una: `python manage.py changepassword admin`.
- **Pruebas automáticas** en `accounts/tests.py`, `tickets/tests.py` y `chatbot/tests.py`: `python manage.py test`.
- Zona horaria `America/Santiago` e idioma `es-cl`.

**Al actualizar una instalación existente**
```bash
pip install -r requirements.txt      # agrega Pillow (fotos)
python manage.py migrate             # campos nuevos: categoría, foto y fecha de cierre
python manage.py collectstatic --noinput
```

## Mejoras de la segunda revisión

**Seguridad**
- **Ajustes de producción**: el sistema se niega a arrancar con `DEBUG=False` y una clave secreta de ejemplo. Con
  `DJANGO_HTTPS=True` activa redirección a https, cookies seguras y HSTS (ver "HTTPS" más abajo).
  Revisa con `python manage.py check --deploy`.
- **Límite de intentos de login**: 5 fallos con el mismo usuario desde la misma dirección bloquean 15 minutos
  (`LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCK_MINUTES`).
- **Tope del gasto de IA**: máximo `CHAT_MAX_PER_HOUR` (30) mensajes por cliente y hora, y el asistente con IA exige
  correo confirmado. El chat de visitantes (sin IA) tiene su propio tope (`VISITOR_CHAT_MAX_PER_10MIN`).
- **Verificación de correo** al registrarse (enlace firmado que vence en 3 días), **recuperación y cambio de
  contraseña**, y correo único por cuenta. Los usuarios creados por el administrador nacen verificados.
- **Estáticos con WhiteNoise**: el CSS y el JavaScript se sirven aunque `DEBUG` sea falso.

**Operación**
- **Correos en segundo plano** (`EMAIL_ASYNC`) y tiempo máximo de espera de la IA de 15 s (`ANTHROPIC_TIMEOUT`), para que
  un servicio lento no deje el sitio ocupado.
- **Páginas de error propias** (403, 404, 500) y **registro de eventos** en la consola y en `logs/nexoia.log`.
- **Respaldos**: `python manage.py backup` genera un `.zip` con la base de datos y las fotos (ver "Respaldos").

**Funcionalidad**
- **Teléfono y dirección** del trabajo en cada ticket (se precargan desde el perfil, que el cliente edita en "Mi perfil").
- **Historial del ticket**: quién lo creó, asignó, cambió de estado o de categoría, canceló, reabrió y calificó.
- **Cancelar, reabrir y reasignar**: el cliente cancela su ticket; cliente, moderador y administrador pueden reabrir
  un ticket cerrado o cancelado; el moderador reasigna aunque el ticket ya esté en curso.
- **Encuesta de satisfacción**: el cliente califica de 1 a 5 al cerrarse el ticket; el promedio aparece en indicadores.
- **Indicadores**: filtro por fechas, carga actual por trabajador, tickets sin atender hace más de `STALE_TICKET_HOURS`
  horas y satisfacción.
- **Notificaciones** paginadas, con enlace directo al ticket y botón para eliminar las leídas.
- **Respuestas del asistente editables** (menú "Respuestas", solo administrador): título, palabras clave, texto y si se
  muestra como pregunta rápida. Tienen prioridad sobre las respuestas que trae el código.

**Presentación**
- Menú desplegable en celulares, favicon, metadatos para compartir el enlace, galería de trabajos y foco de teclado
  contenido dentro del chat abierto.
- **Galería**: copia fotos `.jpg`, `.png` o `.webp` en `static/img/gallery/` y aparecen solas en la portada. El personal también puede subir fotos desde el apartado **Galería** del sitio (ver "Trabajos por segmento").
- **Interfaz renovada**: portada con fotos de obras, fotos ampliables con flechas, menú "Administrar", tablas que se convierten en tarjetas en el celular, miniaturas al elegir fotos y avisos que se pueden cerrar.
- **Términos de uso y política de privacidad** (`/terminos/` y `/privacidad/`), con casilla de aceptación al registrarse.
  Son un texto base que describe lo que hace el sistema: **revísalo con un abogado antes de publicar** y ajusta la
  conservación de datos y los medios de contacto a lo que realmente ofrezca la empresa.

**Calidad**
- Pruebas de Python en cada módulo (`python manage.py test`) y pruebas del chat en JavaScript
  (`node --test tests_js/chat.test.js`).
- Integración continua en `.github/workflows/ci.yml` (revisa que las migraciones estén al día y corre todas las pruebas).

### HTTPS
Cuando el sitio tenga un dominio, instala un certificado (por ejemplo `sudo certbot --nginx -d tu-dominio.cl`) y agrega
`DJANGO_HTTPS=True` y `DJANGO_CSRF_TRUSTED_ORIGINS=https://tu-dominio.cl` a las variables de entorno. No lo actives antes:
redirigiría a https:// un sitio que aún no lo tiene.

### Respaldos
```bash
python manage.py backup                 # crea backups/nexoia-AAAAMMDD-HHMMSS.zip (conserva los últimos 7)
python manage.py backup --keep 14 --output /ruta/segura
```
Con SQLite hace una copia consistente del archivo; con MySQL usa `mysqldump` (debe estar instalado). Para automatizarlo
usa `deploy/install_cron.sh` (ver «Tareas programadas»), o agrega con `crontab -e` una línea como esta (todos los días a las 3:00;
recuerda que cron no ve tus variables de entorno, por eso el instalador es más seguro):
```
0 3 * * * cd /home/ubuntu/nexoia/nexoia_django && /home/ubuntu/nexoia/nexoia_django/venv/bin/python manage.py backup
```
Copia los respaldos fuera del servidor (por ejemplo a un bucket de S3 con `aws s3 cp`): un respaldo en el mismo disco no
protege si la instancia se pierde. En producción conviene MySQL/RDS en lugar de SQLite (ver más abajo).

**Probar que un respaldo sirve** (hazlo al menos una vez, y de vez en cuando):
```bash
# Solo comprobar: abre el .zip, revisa su integridad y muestra cuántos usuarios, tickets y fotos trae. No deja nada.
python manage.py restore_backup backups/nexoia-AAAAMMDD-HHMMSS.zip --verify

# Restaurar en una carpeta aparte (debe estar vacía o no existir). NUNCA pisa el sitio en funcionamiento.
python manage.py restore_backup backups/nexoia-AAAAMMDD-HHMMSS.zip --target /tmp/prueba-restauracion
```
El comando detecta archivos truncados o alterados, bases de datos dañadas, carpetas de destino con datos y rutas
maliciosas dentro del .zip. Para la prueba completa, levanta una copia del sitio apuntando a la base restaurada
(`DB_NAME=/tmp/prueba-restauracion/db.sqlite3`, `MEDIA_ROOT` aparte) y comprueba que puedes entrar y ver tickets y fotos.
Con MySQL/RDS el respaldo es un `dump.sql`: el comando solo confirma que existe y trae tablas; para probarlo de
verdad, cárgalo en una base vacía de prueba con `mysql ... < dump.sql`.

**Al actualizar desde la versión anterior:**
```bash
pip install -r requirements.txt
python manage.py migrate          # nuevas: perfil, historial, calificación, enlaces y respuestas editables
python manage.py collectstatic --noinput
```
Los usuarios que ya existían quedan con el correo marcado como confirmado.

## Mejoras de la tercera revisión

**Para el negocio**
- **Cotizaciones formales**: el moderador envía en el ticket un detalle, un monto en pesos y una fecha de vigencia; el
  cliente la acepta o rechaza (con comentario). Una nueva reemplaza a la pendiente y una vencida no se puede aceptar.
  Los trabajadores no ven los montos.
- **Agenda de visitas**: el moderador agenda o reprograma una fecha y hora (con indicaciones); se avisa al cliente y al
  trabajador. La página **Agenda** muestra las próximas visitas de cada rol.
- **Terreno**: enlace «Abrir en Google Maps» desde la dirección, el trabajador sube **fotos del trabajo terminado** y deja
  una **nota de cierre** que el cliente lee; el personal ve un botón «Escribir por WhatsApp» al teléfono del cliente.
- **«Hablar con una persona»** en el chat: crea un ticket con las últimas conversaciones y avisa a los moderadores
  (no se duplica mientras haya uno abierto).
- **WhatsApp**: si defines `COMPANY_WHATSAPP`, aparece un botón flotante para visitantes y clientes. Avisar los cambios
  de estado por WhatsApp requiere WhatsApp Business API (de pago y con aprobación de Meta): no está incluido.
- **Recordatorios y resumen diario**: `python manage.py send_reminders` avisa de las visitas de hoy y de mañana y envía
  a moderadores y administradores un correo con los tickets sin atender y las visitas próximas.

**Privacidad y seguridad**
- **Derechos del titular desde «Mi perfil»**: descargar todos los datos personales (.zip con `datos.json` y las fotos) y
  **eliminar la cuenta** (borra datos personales, conversaciones, notificaciones y fotos, cancela lo activo y deja el
  historial sin datos de contacto ni identidad).
- **Fotos sin ubicación**: todas las fotos se vuelven a dibujar antes de guardarlas, sin EXIF ni GPS, con la orientación
  corregida y reducidas a 2400 px. Solo se aceptan JPG, PNG y WEBP.
- **Borrado automático de chats** antiguos: `python manage.py purge_old_data` (`CHAT_RETENTION_DAYS`, 180 por defecto).
  La política de privacidad muestra ese plazo: **debes programar el comando** (ver más abajo) para que sea verdad.
- **Verificación en dos pasos** (aplicación autenticadora: Google Authenticator, Microsoft Authenticator, Authy...).
  Disponible para todos desde «Mi perfil». Con `REQUIRE_2FA_STAFF=True` es obligatoria para moderadores y administradores.
  Si alguien pierde el teléfono, un administrador la restablece desde «Usuarios». Está hecha con la biblioteca estándar
  (RFC 6238) y verificada con los vectores oficiales; **no genera código QR**: se escribe la clave a mano en la aplicación.
- **Anti-bots en el registro**: campo señuelo, cronómetro (un formulario enviado en menos de `REGISTER_MIN_SECONDS` se
  rechaza), tope de cuentas por dirección y hora y, si defines las claves `TURNSTILE_*`, un CAPTCHA de Cloudflare.
- **Auditoría** (menú «Auditoría», solo administrador): inicios de sesión del personal, bloqueos por intentos fallidos,
  usuarios creados o desactivados, cambios de verificación en dos pasos, tickets y respuestas eliminadas, descargas de
  datos y cuentas eliminadas.

**Asistente**
- **Reporte de preguntas sin respuesta** (menú «Respuestas» > «Preguntas sin respuesta»): lo que los clientes preguntaron y
  no se pudo contestar, agrupado por frecuencia; «Crear respuesta» abre el formulario ya con el título y las palabras clave.
- **Ayuda de IA para el moderador**: botón «Sugerir categoría, prioridad y resumen» en el ticket. Es **solo una
  propuesta**: nada se aplica sin que el moderador pulse «Aplicar». Sin clave de IA usa reglas simples y lo indica.
  La respuesta del modelo se valida (solo categorías y prioridades que existen) y hay un tope por usuario y hora.

**Monitoreo y operación**
- **`/salud/`**: responde 200 si la base de datos y el caché funcionan y 503 si no. Úsalo con un monitor externo gratuito
  (UptimeRobot, Better Stack...) para recibir un aviso cuando el sitio se caiga.
- **Errores por correo**: con `DJANGO_ADMIN_EMAILS` definido, cada error 500 llega al correo con el detalle.
- **Ambiente de pruebas**: instala una segunda copia con su propia base de datos y `ENVIRONMENT_LABEL=pruebas`; todas las
  páginas muestran un aviso rojo para no confundirla con el sitio real. Usa una instancia, una base y claves distintas.

### Tareas programadas (cron)
Los tres comandos (`send_reminders`, `purge_old_data`, `backup`) no se ejecutan solos: hay que programarlos **una vez
en el servidor**. Con el instalador incluido:
```bash
cp .env.example .env && nano .env            # variables del sitio (si aún no tienes el archivo)
deploy/install_cron.sh --dry-run             # muestra lo que instalaría, sin instalar
deploy/install_cron.sh                       # lo instala en el crontab (se puede repetir sin duplicar)
crontab -l                                   # comprobar
```
Horarios (hora del servidor): 03:00 respaldo, 03:30 borrado de datos antiguos, 08:00 recordatorios y resumen diario.
Los resultados quedan en `logs/cron.log`. Detalles que importan:
- **cron no lee `~/.bashrc` ni el `.service` de systemd**, así que el instalador carga las variables desde `.env`
  (`--env OTRO_ARCHIVO` para usar otro). Los valores con espacios van entre comillas simples. Sin `DJANGO_SECRET_KEY`
  ahí, los comandos no arrancarían.
- Usa el Python del entorno virtual (`--python RUTA`; por defecto `venv/bin/python`).
- Si prefieres hacerlo a mano, `deploy/nexoia.cron` trae las tres líneas (reemplaza `@PROJECT@`, `@ENVFILE@` y `@PYTHON@`).
- En AWS Academy el laboratorio se detiene y la instancia se apaga: mientras esté apagada, nada se ejecuta (ni los
  respaldos). Para algo permanente se necesita un servidor que no se apague.

**Al actualizar desde la versión anterior:**
```bash
pip install -r requirements.txt
python manage.py migrate     # nuevas: 2FA y auditoría, cotizaciones, agenda, fotos de terreno, "revisada" en el chat y galería de trabajos
python manage.py collectstatic --noinput
```

## Mejoras de la cuarta revisión

**Portada**
- **Preguntas frecuentes**: la portada muestra, como acordeón, las respuestas activas que el administrador cargó en
  «Respuestas» (las marcadas como «sugeridas» primero). Incluye datos estructurados `FAQPage` (schema.org) para que
  Google pueda mostrarlas. Para publicar, corregir u ocultar una, basta editarla o desactivarla en «Respuestas»: no
  hay que tocar código. **El título de cada respuesta es lo que se ve como pregunta**, así que conviene escribirlo como
  tal («¿Atienden fines de semana?»).
- **Menos fricción para consultar**: si `COMPANY_WHATSAPP` está definido, la portada ofrece un botón «Escribir por
  WhatsApp» junto a «Crear cuenta», para quien no quiere registrarse. La cuenta sigue siendo obligatoria para crear
  tickets: así el registro (con correo confirmado y anti-bots) sigue siendo la barrera contra el abuso.

**Seguridad y operación**
- **`DEBUG` ahora está apagado por defecto.** Si se olvida `DJANGO_DEBUG`, el sitio arranca en modo producción (y
  exige una `DJANGO_SECRET_KEY` real) en vez de mostrar páginas de error con detalles internos. Para desarrollar en tu
  computador hay que pedirlo: `export DJANGO_DEBUG=True` (Windows: `set DJANGO_DEBUG=True`). Las pruebas
  (`python manage.py test`) no lo necesitan.
- **Estáticos con versión automática**: con `DEBUG` apagado se usa `CompressedManifestStaticFilesStorage` de WhiteNoise.
  `collectstatic` agrega una huella al nombre de cada archivo (`style.3f2a9c1b.css`) y `{% static %}` apunta siempre a
  la versión vigente: **ya no hay que cambiar `?v=N` a mano**, y el navegador solo descarga lo que cambió. Consecuencia:
  `python manage.py collectstatic --noinput` es obligatorio en cada despliegue (y reiniciar Gunicorn). Si faltara
  correrlo, las páginas siguen funcionando con las URL sin huella en vez de fallar.
- **Tareas programadas listas para instalar**: `deploy/install_cron.sh` instala `backup`, `purge_old_data` y
  `send_reminders` (ver «Tareas programadas»).
- **`restore_backup`**: restaura o verifica un respaldo sin tocar el sitio (ver «Respaldos»).
- **`REQUIRE_2FA_STAFF=True`** viene activado en `.env.example`.

**Indicadores**
- **Tiempo medio de primera respuesta**: desde que se crea el ticket hasta la primera acción visible del equipo
  (comentario de alguien que no sea el cliente, asignación, cambio de estado, cotización o visita agendada). Los
  tickets que aún no reciben respuesta no entran en el promedio; la tarjeta muestra cuántos se midieron.
- Los **tickets sin asignar hace más de X horas** ya estaban (tarjeta y tabla «Tickets sin atender»); X se cambia con
  `STALE_TICKET_HOURS` (24 por defecto).

**Al actualizar desde la versión anterior**
```bash
pip install -r requirements.txt
python manage.py collectstatic --noinput    # ahora genera los archivos con huella: obligatorio
# En el servidor, define DJANGO_DEBUG=False (o no lo definas) y una DJANGO_SECRET_KEY real. No hay migraciones nuevas.
```

## Trabajos por segmento (portada)

La portada tiene un apartado **"Trabajos por segmento"** con fotos de obras agrupadas por tipo de trabajo: subestación
de 500 kVA, supermercado, casa habitación, empalme monofásico y aire acondicionado, más una tarjeta de texto para
informes y certificaciones de verificación inicial. Cada foto se abre ampliada al tocarla y tiene su texto descriptivo.

- Las fotos viven en `static/img/trabajos/<segmento>/` (ver el `LEEME.txt` de esa carpeta).
- Los títulos, descripciones y textos de cada foto se definen en la lista `SEGMENTS` de `accounts/works.py`.
- Para agregar fotos basta copiarlas en la carpeta del segmento (se ordenan por nombre, máximo 12 por segmento) y,
  en el servidor, correr `python manage.py collectstatic --noinput` y reiniciar Gunicorn.
- Un segmento sin fotos no se muestra, salvo el de informes y certificaciones, que es solo texto.
- El apartado de "fotos sueltas" anterior (`static/img/gallery/`) sigue funcionando debajo, por si se necesita.

### Galería: subir fotos desde el sitio

Además de las fotos incluidas en el proyecto, **los trabajadores, moderadores y administradores pueden subir fotos
nuevas desde el sitio**, sin tocar archivos ni reiniciar nada:

- Entrar con la cuenta del equipo y abrir **Galería** en el menú (o el botón "Agregar o quitar fotos" de la portada).
- Elegir una o varias fotos (JPG, PNG o WEBP, hasta 5 MB cada una y 10 por vez), el segmento donde deben aparecer y,
  si se quiere, el texto que se muestra bajo la foto. También se pueden arrastrar las fotos sobre el campo.
- La foto aparece de inmediato en la portada, dentro de su segmento y antes de las incluidas (las más recientes
  primero; se muestran hasta 24 subidas por segmento). Al tocarla se abre ampliada, con flechas para pasar a la siguiente.
- Cada persona puede **editar el texto o cambiar de segmento y eliminar las fotos que subió ella**. Moderadores y
  administradores pueden hacerlo con cualquier foto. Los clientes no tienen acceso.
- Las fotos se guardan en `media/trabajos/` (el mismo respaldo del comando `backup` ya las incluye) y se entregan
  por la vista `accounts.views.work_photo`, así que **no hace falta configurar nada en Nginx** para mostrarlas.
- Antes de guardar cada foto se vuelve a dibujar sin datos EXIF: así no queda publicada la ubicación GPS de la obra.
- Cada subida, edición y eliminación queda en el registro de **Auditoría**.
- Para agregar un segmento nuevo, edita la lista `SEGMENTS` de `accounts/works.py`.

> Si el servidor usa Nginx, subir varias fotos a la vez puede superar el límite por defecto (1 MB). Agrega
> `client_max_body_size 55M;` al bloque `server { ... }` (ver el ejemplo de configuración más abajo) y recarga Nginx.

## Cómo está organizado el código

Cada carpeta es una **app de Django**, equivalente a los módulos del monolito
modular de la versión Java: cada una es dueña de sus propios modelos y expone
su lógica a través de `services.py`, en vez de que otra app toque sus tablas
directamente.

```
nexoia_django/
  nexoia_site/        Configuración del proyecto (settings.py, urls.py raíz)
  accounts/           Usuarios, roles y control de acceso (equivalente al módulo "Usuarios")
    models.py           Modelo User (hereda de Django) + el campo "role"
    decorators.py        @role_required(...) — corta el paso con 403 si el rol no calza
    forms.py              Registro público (siempre CLIENTE) vs. alta por el admin (cualquier rol)
    views.py / urls.py
  tickets/            Ticket y TicketComment
    services.py          *** Aquí vive toda la lógica real: crear, asignar, cambiar
                          estado, comentar. Las vistas solo llaman a estas funciones.
  chatbot/            El asistente IA (endpoints JSON del chat flotante)
    services.py          El "cerebro": arma el prompt, llama a la API de Anthropic,
                          decide si responde, deriva a ticket o rechaza por fuera de tema.
  notifications/      Notificaciones internas (lo usan tickets y chatbot)
  stats/               Indicadores para el administrador (cuenta tickets y % resuelto por IA)
  templates/           HTML de cada pantalla (una carpeta por app, más base.html)
  static/css/style.css  Estilos
```

### El flujo más importante del proyecto: `chatbot/services.py`

```
Cliente escribe una pregunta
        │
        ▼
 ¿Es un tema de la empresa Y la IA puede responderla con certeza?
   SÍ ──────────────► responde directo y queda registrado (resolved_by_ai=True)
   NO (no está segura) ─► se crea un ticket automático (tickets.services.create_ticket)
   Fuera de tema ──────► rechaza cortésmente, sin crear ticket
```

Esto se controla con un *system prompt* que le pide al modelo contestar con
marcadores especiales (`[DERIVAR]`, `[FUERA_DE_TEMA]`) cuando corresponda, en
vez de inventar una respuesta. **Si no hay `ANTHROPIC_API_KEY` configurada**,
`_call_model()` devuelve `None` y todo se deriva a ticket automáticamente — así
el flujo de tickets se puede probar completo sin pagar ni configurar nada.
En ese modo, en el chat de visitantes (que nunca usa IA) y también cuando la IA iba a
derivar o falló, un detector local, `_is_off_topic()`, rechaza con «No puedo ayudarte con
eso, porque no está dentro de mi entendimiento» las consultas que no mencionan nada del
rubro (cuentas como 1+1, capitales, chistes, recetas…) en vez de crear un ticket. Es una
regla conservadora: ante la duda (cortesías, teléfonos, «necesito ayuda») deja pasar el mensaje.

### Control de acceso por rol

`accounts/decorators.py` define `@role_required(...)`, usado en cada vista que
debe ser exclusiva de un rol (por ejemplo, solo el moderador puede asignar
tickets). Si el rol no calza, Django responde con error 403 automáticamente.

## Probado de punta a punta

Antes de entregarlo se probó el flujo completo contra el servidor real
(no solo leyendo el código): un cliente pregunta algo que la IA no puede
resolver → se crea un ticket → el moderador lo asigna a un trabajador → el
trabajador lo cierra → el cliente recibe la notificación → el administrador
ve el indicador actualizado → y un cliente que intenta asignar un ticket
recibe un 403. Los seis pasos pasaron correctamente.

## Cómo correrla en tu computador

```bash
python3 -m venv venv
source venv/bin/activate          # en Windows: venv\Scripts\activate
export DJANGO_DEBUG=True          # modo desarrollo (en Windows: set DJANGO_DEBUG=True). Sin esto arranca como producción
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_users --demo  # crea admin/mod/trabajador/cliente de prueba (contraseñas simples, solo local)
python manage.py runserver
```

Abre `http://127.0.0.1:8000`. Usuarios de prueba creados con `--demo` (nunca los uses en un servidor público):

| Usuario | Contraseña | Rol |
|---|---|---|
| `admin` | `admin123` | Administrador |
| `mod` | `mod123` | Moderador |
| `trabajador` | `trab123` | Trabajador |
| `cliente` | `cli123` | Cliente |

Para que el asistente responda de verdad (y no derive todo a ticket), define
la variable de entorno `ANTHROPIC_API_KEY` antes de levantar el servidor.

---

## Cómo correrla en AWS Academy (Learner Lab)

AWS Academy entrega una cuenta "de laboratorio" (Learner Lab) con permisos y
tiempo limitados. Estos son los pasos, pensados para alguien que nunca ha
usado AWS:

### 1. Entrar al laboratorio

1. Entra a tu curso en **AWS Academy** y abre el módulo **Learner Lab**.
2. Haz clic en **Start Lab** y espera a que el ícono quede en verde (puede
   tardar 1-2 minutos). Mientras el lab esté detenido, nada de lo que crees
   adentro seguirá funcionando.
3. Haz clic en **AWS** (arriba, junto al círculo verde) para entrar a la
   consola de AWS normal.

### 2. Crear el servidor (una instancia EC2)

1. En la barra de búsqueda de la consola escribe **EC2** y entra a ese servicio.
2. Haz clic en **Launch instance**.
3. **Name**: `nexoia-server`.
4. **AMI (sistema operativo)**: elige **Ubuntu Server 22.04 LTS**.
5. **Instance type**: `t2.micro` (la que entra en el free tier/créditos del lab).
6. **Key pair**: en Academy normalmente ya existe una llamada **vockey** —
   selecciónala (no se puede crear una nueva clave propia en el lab). Si no
   aparece, créala con el nombre que te deje el laboratorio.
7. **Network settings → Edit**: agrega estas reglas de entrada (*Add security
   group rule*):
   - SSH, puerto 22, origen `0.0.0.0/0` (para conectarte).
   - HTTP, puerto 80, origen `0.0.0.0/0` (para que la página sea pública).
8. Deja el resto por defecto y haz clic en **Launch instance**.
9. Espera a que el **Instance state** diga **Running**, y copia su
   **Public IPv4 address** (la vas a necesitar para conectarte y para abrir
   la página).

### 3. Conectarte al servidor

Más fácil, directo desde el navegador:

1. Selecciona la instancia → botón **Connect** → pestaña **EC2 Instance Connect** → **Connect**.
   Se abre una terminal en el navegador, ya conectado al servidor.

(Si prefieres usar tu propia terminal con SSH, necesitas descargar el archivo
`.pem` de la vockey al crear el lab y conectarte con
`ssh -i vockey.pem ubuntu@TU_IP_PUBLICA`.)

### 4. Instalar lo necesario en el servidor

Una vez dentro (verás un prompt como `ubuntu@ip-...$`), ejecuta:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv git nginx
```

### 5. Subir el proyecto

Si lo tienes en un repositorio Git (recomendado):

```bash
git clone TU_REPOSITORIO.git nexoia
cd nexoia
```

Si no, puedes subir el .zip del proyecto arrastrándolo en la misma ventana de
**EC2 Instance Connect** (tiene un botón de subir archivo), y luego:

```bash
unzip nexoia_django.zip
cd nexoia_django
```

### 6. Configurar el entorno Python

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 7. Configurar las variables de entorno

```bash
export DJANGO_SECRET_KEY="una-clave-larga-inventada-por-ti"
export DJANGO_DEBUG=False
export DJANGO_ALLOWED_HOSTS="TU_IP_PUBLICA"
export ANTHROPIC_API_KEY=""   # opcional; vacío = todo se deriva a ticket
export TRUST_PROXY_HEADERS=True   # con Nginx: los límites de uso distinguen a cada visitante
```

> Con `DJANGO_DEBUG=False` el sistema **no arranca** si `DJANGO_SECRET_KEY` es la clave de ejemplo o tiene menos de
> 20 caracteres. Es a propósito: con una clave conocida cualquiera podría falsificar sesiones.

(Para que no tengas que escribir esto cada vez que te conectes, puedes
agregar esas mismas líneas al final del archivo `~/.bashrc`.)

### 8. Preparar la base de datos y los archivos estáticos

Por simplicidad se usa SQLite (un archivo, sin necesidad de contratar una
base de datos aparte). Si tu proyecto exige una base de datos MySQL en RDS,
ver la sección "Usar MySQL/RDS en vez de SQLite" más abajo.

```bash
python manage.py migrate
python manage.py seed_users          # sin --demo: genera contraseñas aleatorias y las muestra una vez
python manage.py collectstatic --noinput
```

### 9. Probar rápido (antes de dejarlo en modo producción)

```bash
python manage.py runserver 0.0.0.0:8000
```

Abre en tu navegador `http://TU_IP_PUBLICA:8000` (necesitas abrir también el
puerto 8000 en el Security Group, igual que hiciste con el 80). Si ves la
pantalla de login, vas bien. Detén el servidor con `Ctrl+C` y sigue al
siguiente paso para dejarlo corriendo de forma más estable, en el puerto 80.

### 10. Dejarlo corriendo de forma estable con Gunicorn + Nginx

Gunicorn es el servidor que de verdad ejecuta Django en producción; Nginx
recibe las visitas por el puerto 80 y se las pasa a Gunicorn.

```bash
# Dentro de la carpeta del proyecto y con el entorno (venv) activado:
pip install gunicorn
```

Crea un servicio para que Gunicorn se mantenga corriendo (y se reinicie solo
si el servidor se reinicia):

```bash
sudo nano /etc/systemd/system/nexoia.service
```

Pega esto (reemplaza `/home/ubuntu/nexoia/nexoia_django` por la ruta real
donde quedó tu proyecto):

```ini
[Unit]
Description=NexoIA Django (Gunicorn)
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/nexoia/nexoia_django
Environment="DJANGO_SECRET_KEY=una-clave-larga-inventada-por-ti"
Environment="DJANGO_DEBUG=False"
Environment="DJANGO_ALLOWED_HOSTS=TU_IP_PUBLICA"
Environment="ANTHROPIC_API_KEY="
ExecStart=/home/ubuntu/nexoia/nexoia_django/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 nexoia_site.wsgi:application

[Install]
WantedBy=multi-user.target
```

> Para no mantener las variables en dos sitios (el `.service` y el `.env` que usa cron), puedes reemplazar las líneas
> `Environment=` por `EnvironmentFile=/home/ubuntu/nexoia/nexoia_django/.env`; systemd acepta los valores entre comillas.

Guarda (`Ctrl+O`, Enter, `Ctrl+X`) y activa el servicio:

```bash
sudo systemctl daemon-reload
sudo systemctl enable nexoia
sudo systemctl start nexoia
sudo systemctl status nexoia   # debe decir "active (running)"
```

Ahora configura Nginx para que redirija el puerto 80 hacia Gunicorn:

```bash
sudo nano /etc/nginx/sites-available/nexoia
```

```nginx
server {
    listen 80;
    server_name TU_IP_PUBLICA;
    client_max_body_size 55M;   # permite subir varias fotos a la vez (galería y tickets)

    location /static/ {
        alias /home/ubuntu/nexoia/nexoia_django/staticfiles/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/nexoia /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t          # debe decir "syntax is ok"
sudo systemctl restart nginx
```

Ahora abre `http://TU_IP_PUBLICA` (sin `:8000`, puerto 80 normal) — ahí está
la plataforma corriendo de forma estable.

### Importante sobre AWS Academy

- **El lab se reinicia:** cuando termina la sesión del Learner Lab, la
  instancia EC2 se detiene y **pierdes la IP pública** (al volver a iniciar
  el lab, la instancia arranca con una IP distinta). Antes de cada sesión de
  prueba, vuelve a hacer `Start Lab`, anota la nueva IP, y actualiza
  `DJANGO_ALLOWED_HOSTS` (en el archivo del servicio systemd) y la URL con la
  que accedes.
- **Para que esto no sea un problema** al presentar el proyecto, considera
  dejar todo lo de los pasos 4-10 en un script (`deploy.sh`) para poder
  repetirlo rápido la próxima vez que cambie la IP.
- **Créditos limitados:** `t2.micro` es la opción más económica incluida en
  el lab; evita dejar la instancia corriendo más tiempo del necesario.

### Usar MySQL/RDS en vez de SQLite (opcional)

Si tu curso pide explícitamente una base de datos gestionada:

1. En la consola de AWS, busca **RDS** → **Create database** → motor
   **MySQL**, plantilla **Free tier**.
2. Anota el **endpoint**, usuario y contraseña que configures.
3. En el Security Group de la base de datos, permite conexiones entrantes en
   el puerto 3306 **solo** desde el Security Group de tu instancia EC2 (no
   desde "todo internet").
4. En el servidor EC2: `pip install mysqlclient` (puede requerir
   `sudo apt install -y python3-dev default-libmysqlclient-dev build-essential`
   antes).
5. Agrega estas variables de entorno (en el `.service` de systemd, igual que
   las demás):
   ```
   DB_ENGINE=django.db.backends.mysql
   DB_NAME=nexoia
   DB_USER=admin
   DB_PASSWORD=la-que-definiste-en-rds
   DB_HOST=tu-endpoint.rds.amazonaws.com
   DB_PORT=3306
   ```
6. Vuelve a correr `python manage.py migrate` para crear las tablas en la
   nueva base de datos.

## Pendiente / próximos pasos

Lo que ya está hecho en el código pero **hay que activar en el servidor** (el proyecto no puede hacerlo por ti):
- Instalar las tareas programadas: `deploy/install_cron.sh` (ver «Tareas programadas»). Hasta entonces los respaldos,
  el borrado de chats antiguos (que la política de privacidad promete) y los recordatorios **no se ejecutan**.
- Definir `REQUIRE_2FA_STAFF=True` en las variables de entorno del servidor (ya viene en `.env.example`). Cada
  moderador y administrador configurará su aplicación autenticadora en su próximo ingreso; hazlo primero con tu cuenta
  para no quedarte fuera. Si alguien pierde el teléfono, un administrador restablece la verificación desde «Usuarios».
- Configurar un monitor externo para `/salud/` (abajo).
- Probar una restauración real con `restore_backup` (ver «Respaldos») y copiar los respaldos fuera del servidor.

**Monitor externo de `/salud/`** (UptimeRobot, Better Stack u otro con plan gratuito):
1. Crea un monitor de tipo HTTP(s) con la URL `https://TU-DOMINIO/salud/` (o `http://TU_IP/salud/` mientras no haya HTTPS;
   con `DJANGO_HTTPS=True` el sitio redirige a https, así que usa la dirección https).
2. Si el servicio lo permite, agrega la palabra clave `"status": "ok"` que debe aparecer en la respuesta. `/salud/`
   responde 200 con la base y el caché funcionando, y 503 si alguno falla.
3. Intervalo de 5 minutos y un aviso por correo (o Telegram) a una persona que lo vea de verdad.
4. En AWS Academy la IP pública cambia cada vez que se reinicia el laboratorio: actualiza la URL del monitor.

Pendientes que dependen de decisiones o de terceros:
- Contenido real de la portada, presencia en Google y tipografía local.
- Un **formulario corto de contacto** para visitantes sin cuenta: requiere guardar datos de personas que no se
  registraron (modelo nuevo, migración, plazo de retención y texto en la política de privacidad). No está incluido; el
  botón de WhatsApp de la portada cubre el caso mientras tanto.
- Revisar con un abogado los textos de `templates/legal/` antes de publicar.
- HTTPS real (certificado, por ejemplo con Let's Encrypt) — en el lab de Academy no se puede usar un dominio propio
  fácilmente, así que esto queda para un despliegue fuera del ambiente académico.
- Completar los datos de contacto (variables `COMPANY_*`) y, si se desea, agregar fotos de trabajos reales a la página de inicio.
- Las fotos de los tickets se guardan en la carpeta `media/`: inclúyela en los respaldos del servidor.
