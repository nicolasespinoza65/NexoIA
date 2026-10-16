import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BASE_DIR = Path(__file__).resolve().parent.parent
CODE = "import nexoia_site.settings as s; print(s.DEBUG, s.STORAGES['staticfiles']['BACKEND'])"


def import_settings(**env):
    """Importa settings.py en un proceso aparte con exactamente las variables de entorno indicadas."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "ENVIRONMENT"))}
    clean.update(env)
    return subprocess.run([sys.executable, "-c", CODE], cwd=BASE_DIR, env=clean, capture_output=True, text=True)


class ValoresPorDefectoSegurosTests(SimpleTestCase):
    def test_sin_variable_el_modo_debug_queda_apagado(self):
        result = import_settings(DJANGO_SECRET_KEY="una-clave-larga-y-aleatoria-para-pruebas-1234")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("False"), result.stdout)

    def test_sin_variable_ni_clave_segura_se_niega_a_arrancar(self):
        result = import_settings()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_el_modo_desarrollo_hay_que_pedirlo_explicitamente(self):
        result = import_settings(DJANGO_DEBUG="True")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("True"), result.stdout)

    def test_en_produccion_los_estaticos_llevan_version_automatica(self):
        result = import_settings(DJANGO_SECRET_KEY="una-clave-larga-y-aleatoria-para-pruebas-1234")
        self.assertIn("whitenoise.storage.CompressedManifestStaticFilesStorage", result.stdout)

    def test_en_desarrollo_no_se_exige_collectstatic(self):
        result = import_settings(DJANGO_DEBUG="True")
        self.assertIn("django.contrib.staticfiles.storage.StaticFilesStorage", result.stdout)
