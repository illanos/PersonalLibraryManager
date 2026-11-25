@echo off
rem @@titulo@@: doble clic para abrirla. Usa el codigo de src aunque el paquete no este instalado.
cd /d "%~dp0src"
python -m @@nombre@@ %*
pause
