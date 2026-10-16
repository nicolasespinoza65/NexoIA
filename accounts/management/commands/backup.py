"""Respaldo del sistema: base de datos + fotos de los tickets, en un solo archivo .zip.

Uso:      python manage.py backup
Opciones: --output CARPETA   (por defecto backups/)     --keep N   (guarda solo los últimos N respaldos, por defecto 7)

SQLite: copia consistente del archivo de la base de datos (aunque el sitio esté funcionando).
MySQL/RDS: usa mysqldump, que debe estar instalado en el servidor.
Para automatizarlo, agrégalo al cron (ejemplo en el README)."""
import os
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Crea un respaldo (.zip) de la base de datos y de las fotos subidas"

    def add_arguments(self, parser):
        parser.add_argument("--output", default=str(settings.BASE_DIR / "backups"), help="Carpeta de destino")
        parser.add_argument("--keep", type=int, default=7, help="Cuántos respaldos conservar (0 = todos)")

    def handle(self, *args, **options):
        output = Path(options["output"])
        output.mkdir(parents=True, exist_ok=True)
        archive = output / f"nexoia-{datetime.now():%Y%m%d-%H%M%S}.zip"

        with tempfile.TemporaryDirectory() as tmp:
            dump = self._dump_database(Path(tmp))
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.write(dump, dump.name)
                media = Path(settings.MEDIA_ROOT)
                if media.is_dir():
                    for file in media.rglob("*"):
                        if file.is_file():
                            bundle.write(file, Path("media") / file.relative_to(media))

        keep = options["keep"]
        if keep > 0:
            for old in sorted(output.glob("nexoia-*.zip"))[:-keep]:
                old.unlink()
        self.stdout.write(self.style.SUCCESS(f"Respaldo creado: {archive}"))

    def _dump_database(self, folder):
        db = settings.DATABASES["default"]
        engine = db["ENGINE"]
        if engine.endswith("sqlite3"):
            target_path = folder / "db.sqlite3"
            source = sqlite3.connect(str(db["NAME"]))
            target = sqlite3.connect(str(target_path))
            with target:
                source.backup(target)  # copia consistente aunque haya escrituras en curso
            source.close()
            target.close()
            return target_path
        if engine.endswith("mysql"):
            target_path = folder / "dump.sql"
            command = [
                "mysqldump", f"--host={db['HOST']}", f"--port={db['PORT'] or 3306}", f"--user={db['USER']}",
                "--single-transaction", f"--result-file={target_path}", db["NAME"],
            ]
            try:
                # La contraseña va por variable de entorno para que no aparezca en la lista de procesos
                subprocess.run(command, check=True, env={**os.environ, "MYSQL_PWD": db["PASSWORD"]})
            except FileNotFoundError:
                raise CommandError("No se encontró 'mysqldump'. Instálalo (paquete mysql-client) o respalda desde la consola de RDS.")
            except subprocess.CalledProcessError as error:
                raise CommandError(f"mysqldump falló: {error}")
            return target_path
        raise CommandError(f"Motor de base de datos no soportado para respaldos: {engine}")
