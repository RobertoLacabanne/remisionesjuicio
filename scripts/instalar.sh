#!/usr/bin/env bash
# Instalación en un solo comando, para Linux y macOS.
#
# Pensado para que lo corra alguien que no participó del desarrollo, en la computadora
# donde se va a usar. Chequea todo, instala lo que falta y deja la app lista. Si algo no
# puede resolver solo, dice exactamente qué hacer y se detiene, en vez de seguir a
# medias y fallar más adelante, que es cuando ya nadie sabe qué pasó.
set -u

verde() { printf '\033[32m%s\033[0m\n' "$1"; }
rojo()  { printf '\033[31m%s\033[0m\n' "$1"; }
gris()  { printf '\033[90m%s\033[0m\n' "$1"; }

cd "$(dirname "$0")/.." || exit 1
echo
echo "  Punteo de Evidencia — UFIL Paraná"
echo "  Instalación"
echo "  ------------------------------------------------------------"
echo

# ── 1. Python ───────────────────────────────────────────────────────────────
PY=""
for c in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null || echo 0)
    if [ "$v" -ge 311 ] 2>/dev/null; then PY="$c"; break; fi
  fi
done
if [ -z "$PY" ]; then
  rojo "  Falta Python 3.11 o posterior."
  echo
  echo "  En Ubuntu/Debian:   sudo apt install python3 python3-pip python3-venv"
  echo "  En Mac:             brew install python@3.12"
  echo "  O bajalo de:        python.org/downloads"
  echo
  exit 1
fi
verde "  ✓ $($PY --version)"

# ── 2. Tesseract, con castellano ────────────────────────────────────────────
if ! command -v tesseract >/dev/null 2>&1; then
  rojo "  Falta Tesseract, que es el que lee los escaneos."
  echo
  if [ "$(uname)" = "Darwin" ]; then
    echo "  Instalalo con:   brew install tesseract tesseract-lang"
    echo "  (si no tenés brew: brew.sh)"
  else
    echo "  Instalalo con:   sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-osd"
  fi
  echo
  echo "  Después volvé a correr este mismo comando."
  exit 1
fi
verde "  ✓ $(tesseract --version 2>&1 | head -1)"

if ! tesseract --list-langs 2>&1 | grep -qx spa; then
  rojo "  Tesseract está, pero le falta el castellano."
  echo
  if [ "$(uname)" = "Darwin" ]; then
    echo "  Instalalo con:   brew install tesseract-lang"
  else
    echo "  Instalalo con:   sudo apt install tesseract-ocr-spa tesseract-ocr-osd"
  fi
  echo
  exit 1
fi
verde "  ✓ idioma castellano instalado"

# ── 3. Entorno propio, para no tocar el Python del sistema ──────────────────
if [ ! -d ".venv" ]; then
  gris "  Creando el entorno..."
  "$PY" -m venv .venv || { rojo "  No se pudo crear el entorno."; exit 1; }
fi
# shellcheck disable=SC1091
. .venv/bin/activate
gris "  Instalando las librerías (tarda un minuto la primera vez)..."
pip install --quiet --upgrade pip >/dev/null 2>&1
if ! pip install --quiet -r requisitos.txt; then
  rojo "  Falló la instalación de las librerías."
  echo "  Probá a mano:   .venv/bin/pip install -r requisitos.txt"
  exit 1
fi
verde "  ✓ librerías instaladas"

# ── 4. Chequeo final, con el diagnóstico del propio sistema ─────────────────
echo
python -m punteo.cli diagnostico || {
  echo
  rojo "  Falta algo. Está listado arriba, con qué instalar en cada caso."
  exit 1
}

echo
echo "  ------------------------------------------------------------"
verde "  Listo. De acá en adelante, todos los días:"
echo
echo "      ./scripts/arrancar.sh"
echo
echo "  Y se abre en el navegador:  http://127.0.0.1:8714"
echo
