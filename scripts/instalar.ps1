# Instalación en Windows.
#
# Clic derecho sobre este archivo → «Ejecutar con PowerShell».
#
# Si Windows dice que los scripts están bloqueados, abrir PowerShell y correr una vez:
#     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#
# Chequea todo, instala lo que falta y deja la app lista. Si algo no lo puede resolver
# solo, dice exactamente qué hacer y se detiene, en vez de seguir a medias.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Verde($t) { Write-Host "  $t" -ForegroundColor Green }
function Rojo($t)  { Write-Host "  $t" -ForegroundColor Red }
function Gris($t)  { Write-Host "  $t" -ForegroundColor DarkGray }

Write-Host ""
Write-Host "  Punteo de Evidencia — UFIL Paraná"
Write-Host "  Instalación"
Write-Host "  ------------------------------------------------------------"
Write-Host ""

# ── 1. Python ───────────────────────────────────────────────────────────────
$py = $null
foreach ($c in @("python", "python3", "py")) {
  try {
    $v = & $c -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
    if ($LASTEXITCODE -eq 0 -and [int]$v -ge 311) { $py = $c; break }
  } catch { }
}
if (-not $py) {
  Rojo "Falta Python 3.11 o posterior."
  Write-Host ""
  Write-Host "  Bajalo de:  https://www.python.org/downloads/"
  Write-Host "  IMPORTANTE: en la primera pantalla del instalador, tildar"
  Write-Host "  «Add python.exe to PATH» antes de seguir."
  Write-Host ""
  Read-Host "  Enter para cerrar"
  exit 1
}
Verde "✓ $(& $py --version)"

# ── 2. Tesseract, con castellano ────────────────────────────────────────────
# En Windows el instalador no lo agrega al PATH, así que además de buscarlo ahí se
# miran las dos rutas donde lo deja por omisión. Es el problema número uno de esta
# instalación y resolverlo acá ahorra una llamada telefónica.
$tess = $null
if (Get-Command tesseract -ErrorAction SilentlyContinue) {
  $tess = "tesseract"
} else {
  foreach ($r in @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
                   "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe",
                   "$env:LOCALAPPDATA\Programs\Tesseract-OCR\tesseract.exe")) {
    if (Test-Path $r) {
      $tess = $r
      $env:PATH = "$(Split-Path $r);$env:PATH"
      Gris "Tesseract encontrado en $(Split-Path $r)"
      Gris "(no estaba en el PATH; se agrega para esta sesión)"
      break
    }
  }
}
if (-not $tess) {
  Rojo "Falta Tesseract, que es el que lee los escaneos."
  Write-Host ""
  Write-Host "  Bajá el instalador de:"
  Write-Host "    https://github.com/UB-Mannheim/tesseract/wiki"
  Write-Host ""
  Write-Host "  Durante la instalación, en «Additional language data», tildar:"
  Write-Host "    Spanish   (y también Orientation and script detection)"
  Write-Host ""
  Write-Host "  Después volvé a correr este mismo script."
  Write-Host ""
  Read-Host "  Enter para cerrar"
  exit 1
}
Verde "✓ $((& $tess --version 2>&1 | Select-Object -First 1))"

$langs = & $tess --list-langs 2>&1
if ($langs -notcontains "spa") {
  Rojo "Tesseract está, pero le falta el castellano."
  Write-Host ""
  Write-Host "  Volvé a correr el instalador de Tesseract y, en «Additional language"
  Write-Host "  data», tildá Spanish. O bajá `spa.traineddata` de:"
  Write-Host "    https://github.com/tesseract-ocr/tessdata"
  Write-Host "  y copialo a la carpeta `tessdata` de la instalación."
  Write-Host ""
  Read-Host "  Enter para cerrar"
  exit 1
}
Verde "✓ idioma castellano instalado"

# ── 3. Entorno propio, para no tocar el Python del sistema ──────────────────
if (-not (Test-Path ".venv")) {
  Gris "Creando el entorno..."
  & $py -m venv .venv
  if ($LASTEXITCODE -ne 0) { Rojo "No se pudo crear el entorno."; Read-Host; exit 1 }
}
$vpy = ".\.venv\Scripts\python.exe"
Gris "Instalando las librerías (tarda un minuto la primera vez)..."
& $vpy -m pip install --quiet --upgrade pip 2>$null
& $vpy -m pip install --quiet -r requisitos.txt
if ($LASTEXITCODE -ne 0) {
  Rojo "Falló la instalación de las librerías."
  Write-Host "  Probá a mano:   .venv\Scripts\pip install -r requisitos.txt"
  Read-Host "  Enter para cerrar"
  exit 1
}
Verde "✓ librerías instaladas"

# ── 4. Chequeo final, con el diagnóstico del propio sistema ─────────────────
Write-Host ""
& $vpy -m punteo.cli diagnostico
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Rojo "Falta algo. Está listado arriba, con qué instalar en cada caso."
  Read-Host "  Enter para cerrar"
  exit 1
}

Write-Host ""
Write-Host "  ------------------------------------------------------------"
Verde "Listo. De acá en adelante, todos los días:"
Write-Host ""
Write-Host "      doble clic en  scripts\arrancar.bat"
Write-Host ""
Write-Host "  Y se abre en el navegador:  http://127.0.0.1:8714"
Write-Host ""
Read-Host "  Enter para cerrar"
