#!/usr/bin/env bash
# Instala (o actualiza) las tareas programadas de NexoIA en el crontab del usuario actual. Se puede correr varias veces:
# reemplaza solo su propio bloque y no toca otras líneas del crontab.
#
# Uso, desde la carpeta del proyecto:
#   deploy/install_cron.sh [--env ARCHIVO] [--python RUTA] [--dry-run]
#
#   --env      Archivo con las variables de entorno del sitio, formato  CLAVE=valor  (por defecto: ./.env).
#              Es el mismo contenido de .env.example. Debe existir: sin él, DJANGO_SECRET_KEY no llega a cron y
#              los comandos fallarían al arrancar.
#   --python   Python del entorno virtual (por defecto: ./venv/bin/python).
#   --dry-run  Muestra el crontab resultante sin instalarlo.
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVFILE="$PROJECT/.env"
PYTHON="$PROJECT/venv/bin/python"
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENVFILE="$(realpath "$2")"; shift 2 ;;
    --python) PYTHON="$(realpath "$2")"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
done

[ -f "$PROJECT/manage.py" ] || { echo "No encuentro manage.py en $PROJECT" >&2; exit 1; }
[ -x "$PYTHON" ] || { echo "No existe $PYTHON. Indica el Python del entorno virtual con --python." >&2; exit 1; }
[ -f "$ENVFILE" ] || { echo "No existe $ENVFILE. Crea el archivo de entorno (copia .env.example como .env y complétalo) o indícalo con --env." >&2; exit 1; }
mkdir -p "$PROJECT/logs"
chmod 600 "$ENVFILE" 2>/dev/null || true   # contiene claves: que solo lo lea este usuario

BEGIN="# >>> nexoia (gestionado por deploy/install_cron.sh) >>>"
END="# <<< nexoia <<<"
BLOCK="$(sed -e "s|@PROJECT@|$PROJECT|g" -e "s|@ENVFILE@|$ENVFILE|g" -e "s|@PYTHON@|$PYTHON|g" "$PROJECT/deploy/nexoia.cron")"

CURRENT="$(crontab -l 2>/dev/null || true)"
# quita un bloque anterior (si existe) y agrega el nuevo
CLEANED="$(printf '%s\n' "$CURRENT" | awk -v b="$BEGIN" -v e="$END" '$0==b{skip=1;next} $0==e{skip=0;next} !skip')"
NEW="$(printf '%s\n%s\n%s\n%s\n' "$CLEANED" "$BEGIN" "$BLOCK" "$END" | sed '/./,$!d')"

if [ "$DRY" -eq 1 ]; then
  printf '%s\n' "$NEW"
  exit 0
fi
printf '%s\n' "$NEW" | crontab -
echo "Tareas programadas instaladas. Revisa con:  crontab -l"
echo "Los resultados quedan en $PROJECT/logs/cron.log"
