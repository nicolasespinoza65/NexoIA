"""Restaura o verifica un respaldo creado con `python manage.py backup`.

Un respaldo que nunca se probó restaurar no es una garantía. Este comando permite comprobarlo sin tocar el sitio:

  python manage.py restore_backup backups/nexoia-20261016-030000.zip --verify
      Abre el respaldo en una carpeta temporal, revisa que el archivo no esté dañado, que la base de datos pase su
      chequeo de integridad y muestra cuántos registros y fotos contiene. No deja nada en el disco.

  python manage.py restore_backup backups/nexoia-20261016-030000.zip --target /ruta/restauracion
      Restaura en una carpeta APARTE (debe estar vacía o no existir) y la verifica. Nunca pisa la base de datos ni las
      fotos del sitio en funcionamiento: al terminar, el comando indica cómo ponerlas en su lugar.

SQLite: se restaura el archivo db.sqlite3 y se revisa con PRAGMA integrity_check.
MySQL/RDS: el respaldo trae un dump.sql; aquí solo se comprueba que exista y tenga las tablas. Para probarlo de
verdad, cárgalo en una base de datos vacía de prueba (el comando imprime la instrucción).
"""
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

SQLITE_NAME = "db.sqlite3"
MYSQL_NAME = "dump.sql"
# Tablas que cualquier base de NexoIA debe tener, y las que se muestran como resumen
REQUIRED_TABLES = ("django_migrations", "accounts_user", "tickets_ticket")
SUMMARY_TABLES = (
    ("accounts_user", "usuarios"), ("tickets_ticket", "tickets"), ("tickets_ticketcomment", "comentarios"),
    ("chatbot_chatmessage", "conversaciones del asistente"), ("chatbot_faqentry", "respuestas del asistente"),
)


def safe_extract(bundle, destination):
    """Extrae el .zip rechazando rutas que intenten salir de la carpeta de destino (zip slip)."""
    destination = Path(destination).resolve()
    for member in bundle.infolist():
        target = (destination / member.filename).resolve()
        if target != destination and destination not in target.parents:
            raise CommandError(f"El respaldo contiene una ruta sospechosa y no se restauró: {member.filename}")
    bundle.extractall(destination)


def check_sqlite(path):
    """Revisa una base SQLite restaurada. Devuelve {tabla: cantidad de filas} o falla con CommandError."""
    try:
        connection = sqlite3.connect(str(path))
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise CommandError(f"La base de datos del respaldo está dañada: {result}")
            tables = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            missing = [t for t in REQUIRED_TABLES if t not in tables]
            if missing:
                raise CommandError("La base del respaldo no parece ser de NexoIA; faltan las tablas: " + ", ".join(missing))
            return {t: connection.execute('SELECT COUNT(*) FROM "%s"' % t.replace('"', '""')).fetchone()[0] for t in tables}
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        raise CommandError(f"No se pudo abrir la base de datos del respaldo: {error}")


class Command(BaseCommand):
    help = "Restaura (en una carpeta aparte) o verifica un respaldo creado con el comando backup"

    def add_arguments(self, parser):
        parser.add_argument("archive", help="Archivo .zip del respaldo")
        parser.add_argument("--target", help="Carpeta donde restaurar (debe estar vacía o no existir)")
        parser.add_argument("--verify", action="store_true", help="Solo verificar, sin dejar archivos")

    def handle(self, *args, **options):
        archive = Path(options["archive"])
        if not archive.is_file():
            raise CommandError(f"No existe el archivo: {archive}")
        if bool(options["target"]) == bool(options["verify"]):
            raise CommandError("Indica --verify (solo comprobar) o --target CARPETA (restaurar), pero no ambos.")

        try:
            bundle = zipfile.ZipFile(archive)
        except zipfile.BadZipFile:
            raise CommandError("El archivo no es un .zip válido: el respaldo está dañado o incompleto.")
        with bundle:
            bad = bundle.testzip()  # lee todo el contenido y comprueba su CRC
            if bad:
                raise CommandError(f"El respaldo está dañado: falla la integridad de «{bad}».")
            names = bundle.namelist()
            if SQLITE_NAME not in names and MYSQL_NAME not in names:
                raise CommandError(f"El respaldo no trae la base de datos ({SQLITE_NAME} o {MYSQL_NAME}).")

            if options["verify"]:
                with tempfile.TemporaryDirectory() as tmp:
                    safe_extract(bundle, tmp)
                    self._report(Path(tmp), restored_to=None)
                return

            target = Path(options["target"])
            if target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise CommandError(f"La carpeta {target} ya existe y no está vacía. Elige otra para no pisar datos.")
            target.mkdir(parents=True, exist_ok=True)
            safe_extract(bundle, target)
        self._report(target, restored_to=target)

    def _report(self, folder, restored_to):
        media = folder / "media"
        photos = sum(1 for f in media.rglob("*") if f.is_file()) if media.is_dir() else 0
        sqlite_file = folder / SQLITE_NAME
        if sqlite_file.is_file():
            counts = check_sqlite(sqlite_file)
            self.stdout.write(self.style.SUCCESS("Base de datos SQLite íntegra. Contenido del respaldo:"))
            for table, label in SUMMARY_TABLES:
                if table in counts:
                    self.stdout.write(f"  {counts[table]:>6}  {label}")
            self.stdout.write(f"  {photos:>6}  archivos en media/ (fotos de tickets y de la galería)")
            hint = (f"Para usarla: detén el sitio, reemplaza db.sqlite3 por {sqlite_file} y la carpeta media/ por "
                    f"{media}, y vuelve a iniciarlo.")
        else:
            dump = folder / MYSQL_NAME
            text = dump.read_text(encoding="utf-8", errors="replace") if dump.stat().st_size else ""
            if "CREATE TABLE" not in text:
                raise CommandError("El dump.sql del respaldo está vacío o no tiene tablas.")
            self.stdout.write(self.style.SUCCESS("dump.sql presente y con tablas."))
            self.stdout.write(f"  {photos:>6}  archivos en media/")
            self.stdout.write("  Esto no prueba que MySQL lo acepte: cárgalo en una base de prueba vacía para confirmarlo.")
            hint = f"Para probarlo: mysql -h HOST -u USUARIO -p BASE_DE_PRUEBA < {dump}"
        if restored_to:
            self.stdout.write(self.style.SUCCESS(f"Restaurado en {restored_to}. El sitio en funcionamiento no se tocó."))
            self.stdout.write(hint)
        else:
            self.stdout.write(self.style.SUCCESS("Verificación completa: el respaldo se puede restaurar."))
