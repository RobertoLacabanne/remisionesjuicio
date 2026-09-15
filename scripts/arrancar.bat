@echo off
REM Levanta la aplicacion. Es lo unico que hace falta correr todos los dias.
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   Todavia no esta instalado. Hace clic derecho en scripts\instalar.ps1
  echo   y elegi "Ejecutar con PowerShell".
  echo.
  pause
  exit /b 1
)
echo.
echo   Abri esto en el navegador:  http://127.0.0.1:8714
echo   ^(para cerrar, Ctrl-C en esta ventana^)
echo.
start "" http://127.0.0.1:8714
".venv\Scripts\python.exe" -m punteo.cli servir %*
