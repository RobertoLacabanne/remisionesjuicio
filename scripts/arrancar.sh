#!/usr/bin/env bash
# Levanta la aplicación. Es lo único que hace falta correr todos los días.
set -u
cd "$(dirname "$0")/.." || exit 1
if [ ! -d ".venv" ]; then
  echo "  Todavía no está instalado. Corré primero:  ./scripts/instalar.sh"
  exit 1
fi
# shellcheck disable=SC1091
. .venv/bin/activate
echo
echo "  Abrí esto en el navegador:  http://127.0.0.1:8714"
echo "  (para cerrar, Ctrl-C en esta ventana)"
echo
# Abrir el navegador solo, si el sistema lo permite.
( sleep 2; (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:8714) \
        || (command -v open >/dev/null && open http://127.0.0.1:8714) ) >/dev/null 2>&1 &
exec python -m punteo.cli servir "$@"
