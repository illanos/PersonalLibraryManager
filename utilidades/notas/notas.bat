@echo off
rem Notas: doble clic para abrirlas en el navegador.
rem Cierra esta ventana (o pulsa Ctrl+C) para apagarlo.
rem Usa el codigo de src\ aunque el paquete no este instalado.
cd /d "%~dp0src"
python -m notas abrir %*
if errorlevel 1 pause
