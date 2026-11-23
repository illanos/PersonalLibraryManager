@echo off
rem Panel web del exportador: doble clic para abrirlo en el navegador.
rem Cierra esta ventana (o pulsa Ctrl+C) para apagarlo.
cd /d "%~dp0"
python main.py panel %*
if errorlevel 1 pause
