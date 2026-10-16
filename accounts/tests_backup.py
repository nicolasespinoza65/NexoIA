import io
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

TABLES = ("django_migrations", "accounts_user", "tickets_ticket", "tickets_ticketcomment", "chatbot_chatmessage", "chatbot_faqentry")


class RespaldoYRestauracionTests(SimpleTestCase):
    """Crea un respaldo real con el comando `backup` (sobre una base SQLite de prueba, no la del sitio) y lo
    restaura con `restore_backup`, comparando el contenido. Así se comprueba que el respaldo sirve de verdad."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.live = self.tmp / "vivo.sqlite3"
        db = sqlite3.connect(self.live)
        for table in TABLES:
            db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, x TEXT)")
        db.executemany("INSERT INTO accounts_user(x) VALUES (?)", [("a",), ("b",), ("c",)])
        db.executemany("INSERT INTO tickets_ticket(x) VALUES (?)", [("t1",), ("t2",)])
        db.commit()
        db.close()
        self.media = self.tmp / "media"
        (self.media / "tickets").mkdir(parents=True)
        (self.media / "tickets" / "falla.jpg").write_bytes(b"foto-original")
        fake_settings = SimpleNamespace(
            BASE_DIR=self.tmp, MEDIA_ROOT=self.media,
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(self.live)}})
        patcher = patch("accounts.management.commands.backup.settings", fake_settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        call_command("backup", output=str(self.tmp / "backups"), stdout=io.StringIO())
        self.archive = next((self.tmp / "backups").glob("nexoia-*.zip"))

    def restore(self, *args):
        out = io.StringIO()
        call_command("restore_backup", str(self.archive), *args, stdout=out)
        return out.getvalue()

    def test_verificar_informa_el_contenido_sin_dejar_archivos(self):
        before = sorted(p.name for p in self.tmp.iterdir())
        out = self.restore("--verify")
        self.assertIn("íntegra", out)
        self.assertIn("3  usuarios", out)
        self.assertIn("2  tickets", out)
        self.assertIn("1  archivos en media", out)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), before)

    def test_restaurar_deja_la_base_y_las_fotos_identicas(self):
        target = self.tmp / "restaurado"
        self.restore("--target", str(target))
        restored = sqlite3.connect(target / "db.sqlite3")
        self.assertEqual(restored.execute("SELECT COUNT(*) FROM accounts_user").fetchone()[0], 3)
        self.assertEqual(restored.execute("SELECT x FROM tickets_ticket ORDER BY id").fetchall(), [("t1",), ("t2",)])
        restored.close()
        self.assertEqual((target / "media" / "tickets" / "falla.jpg").read_bytes(), b"foto-original")

    def test_no_pisa_una_carpeta_con_datos(self):
        target = self.tmp / "ocupada"
        target.mkdir()
        (target / "importante.txt").write_text("no tocar")
        with self.assertRaises(CommandError):
            self.restore("--target", str(target))
        self.assertEqual((target / "importante.txt").read_text(), "no tocar")

    def test_exige_verify_o_target(self):
        with self.assertRaises(CommandError):
            self.restore()
        with self.assertRaises(CommandError):
            self.restore("--verify", "--target", str(self.tmp / "x"))

    def test_rechaza_un_respaldo_truncado(self):
        self.archive.write_bytes(self.archive.read_bytes()[:150])
        with self.assertRaises(CommandError):
            self.restore("--verify")

    def test_detecta_contenido_alterado(self):
        corrupt = self.tmp / "alterado.zip"
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(corrupt, "w", zipfile.ZIP_STORED) as out:
            for info in source.infolist():
                out.writestr(info.filename, source.read(info.filename))
        data = bytearray(corrupt.read_bytes())
        data[data.find(b"foto-original")] ^= 0xFF
        corrupt.write_bytes(data)
        self.archive = corrupt
        with self.assertRaises(CommandError):
            self.restore("--verify")

    def test_rechaza_rutas_que_salen_de_la_carpeta(self):
        evil = self.tmp / "malicioso.zip"
        with zipfile.ZipFile(evil, "w") as bundle:
            bundle.write(self.live, "db.sqlite3")
            bundle.writestr("../fuera.txt", "x")
        self.archive = evil
        with self.assertRaises(CommandError):
            self.restore("--target", str(self.tmp / "dest"))
        self.assertFalse((self.tmp / "fuera.txt").exists())

    def test_rechaza_una_base_que_no_es_de_nexoia(self):
        other = self.tmp / "otra.sqlite3"
        db = sqlite3.connect(other)
        db.execute("CREATE TABLE cualquier_cosa (a)")
        db.commit()
        db.close()
        self.archive = self.tmp / "otra.zip"
        with zipfile.ZipFile(self.archive, "w") as bundle:
            bundle.write(other, "db.sqlite3")
        with self.assertRaises(CommandError):
            self.restore("--verify")
