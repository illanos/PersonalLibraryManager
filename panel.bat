@echo off
rem Panel web del exportador: doble clic para abrirlo en el navegador.
rem Cierra esta ventana (o pulsa Ctrl+C) para apagarlo.
rem Usa el codigo de src\ aunque el paquete no este instalado.
cd /d "%~dp0src"
python -m exportador panel %*
if errorlevel 1 pause
