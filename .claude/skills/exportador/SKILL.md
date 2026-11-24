---
name: exportador
description: Experta en usar el Exportador (el paquete Python `exportador` de este proyecto) para importar, organizar, renombrar y optimizar fotos, vídeos y notas de voz; generar y servir la galería web (caras, lugares, favoritos); importar un Takeout de Google Fotos; fusionar dos colecciones sin duplicados quedándose con la mejor copia; limpiar fotos repetidas con papelera; reorganizar una biblioteca ya importada y usar el panel web. Úsala siempre que el usuario quiera hacer algo con sus fotos, vídeos o audios o con su biblioteca (volcar el móvil o una tarjeta, separar WhatsApp, pasar fotos de Google Fotos, quitar duplicados, ver la galería, poner nombre a caras, fechas raras, informes CSV, catálogo, papelera, espacio en disco), cuando pregunte qué comando u opción usar, por qué un archivo acabó donde está o no se importó, o cómo usar el paquete desde Python, aunque no nombre la herramienta ni el comando.
---

# Exportador: guía de uso experta

El Exportador copia fotos, vídeos y audios desde una carpeta de **origen** a una
**biblioteca** ordenada por fecha (`Año/MM-Mes/AAAAMMDD_HHMMSS.ext`), optimizándolos sin
perder metadatos, y genera una galería web local. Tu trabajo es ayudar al usuario a
conseguir lo que quiere con él: elegir el comando y las opciones, comprobar requisitos,
ejecutar con seguridad, interpretar el resultado y resolver dudas sobre su biblioteca.

Garantías del programa que debes conocer (y respetar al explicar o ejecutar):

- **El origen solo se lee.** Nunca se mueve, modifica ni borra nada de él.
- **Incremental.** Repetir el mismo comando solo procesa lo nuevo (catálogo con MD5).
- **Escritura atómica.** Todo se escribe como `.part` y se renombra al final: Ctrl+C es
  seguro y basta con volver a lanzar el comando para continuar.
- **Nada se borra directamente.** Lo que se quita (limpiar repetidas, la peor copia al
  fusionar) va a `.exportador/papelera/` y se puede restaurar.
- **WhatsApp va aparte**, en `WhatsApp/`, y la galería no lo mezcla con el resto.

## 1. Cómo ejecutarlo

Raíz del proyecto: la carpeta que contiene `pyproject.toml` (esta skill está en
`<raíz>/.claude/skills/exportador/`). Comprueba primero cómo se puede lanzar:

```bash
python -m exportador -h
```

- Si funciona, el paquete está instalado: usa `python -m exportador <comando> …` (o
  `exportador <comando> …`, que es lo mismo).
- Si dice `No module named exportador`, ejecútalo desde el código del proyecto sin instalar:
  `PYTHONPATH=src python -m exportador …` (bash) o `$env:PYTHONPATH="src"; python -m
  exportador …` (PowerShell), desde la raíz. Instalarlo (`pip install -e ".[todo]"`) cambia
  el Python del usuario: propónselo, no lo hagas sin que diga que sí.
- Las dependencias opcionales y FFmpeg se comprueban en la sección 4.

Para quien no quiera terminal existe el **panel web**: `panel.bat` (doble clic, Windows) o
`python -m exportador panel`. Muestra las mismas opciones, simula, ejecuta y enseña el
progreso. Recomiéndalo cuando el usuario prefiera algo visual o la ejecución vaya a ser larga.

## 2. La regla de oro: simular, enseñar, confirmar

Importar, fusionar y reorganizar escriben en la biblioteca, pueden tardar horas (sobre todo
los vídeos) y mueven archivos a la papelera. Un error de carpeta o de opción cuesta caro. Por
eso, para cualquier comando que modifique algo:

1. Construye el comando completo, con rutas absolutas entre comillas.
2. Ejecútalo primero con `--simular` (no crea, mueve ni modifica nada; en `fusionar`
   deja el plan completo en un CSV de la carpeta temporal).
3. Resume al usuario lo que haría: cuántos archivos nuevos, ya importados, duplicados,
   dañados, cuánto espacio, a qué biblioteca. Señala lo raro (biblioteca nueva cuando
   esperaba una existente, muchas fechas dudosas, poco espacio).
4. **Pide confirmación explícita** y solo entonces lánzalo sin `--simular`. Un «sí» vale
   para ese comando con esas opciones; si cambian, vuelve a preguntar.

Vaciar la papelera de «Limpiar repetidas» es lo único que borra de verdad: no lo hagas
nunca en su nombre; explícale cómo hacerlo él (botón *Vaciar*, escribiendo `VACIAR`).

`galeria` solo escribe sus propios archivos (`galeria.html`, `galeria.json`, `_galeria/`) y
no toca las fotos, así que no tiene `--simular` ni necesita confirmación; sí avisa antes de
las descargas de datos (`--descargar-…`), que salen a internet. Los comandos de lectura (`-h`,
los scripts de esta skill) tampoco la necesitan.

## 3. Qué comando para cada objetivo

| El usuario quiere… | Comando |
|---|---|
| Volcar el móvil, una tarjeta o una carpeta (fotos + vídeos + audios + galería) | `todo <origen> --destino <biblioteca>` |
| Solo fotos / solo vídeos / solo notas de voz | `fotos` / `videos` / `audio` |
| Importar la descarga de Google Fotos (carpeta `Google Fotos` del Takeout) | `google <carpeta> --destino <biblioteca aparte>` y luego `fusionar` con la principal |
| Añadir otra colección o biblioteca a la suya sin repetir nada | `fusionar <colección> --destino <biblioteca>` |
| Ver y explorar la biblioteca (buscar, favoritos, caras, lugares) | `galeria <biblioteca> --servir` |
| Quitar copias repetidas (sobre todo WhatsApp) | `galeria <biblioteca> --servir` → botón *Limpiar repetidas* |
| Separar WhatsApp o arreglar nombres sin hora en una biblioteca antigua | `reorganizar <biblioteca> --whatsapp --fechas-aproximadas` |
| Configurar y lanzar todo desde el navegador | `panel` |

Sin `--destino`, la biblioteca se crea junto al origen como `<origen>_organizados`:
pregunta siempre dónde quiere la biblioteca si no lo ha dicho, y si ya tiene una, usa esa
(lo ya importado no se duplica). Todas las opciones de cada comando, con sus valores por
defecto, están en `references/comandos.md`.

## 4. Método de trabajo

1. **Entiende el objetivo y las rutas**: qué quiere conseguir, carpeta de origen, biblioteca
   de destino (¿nueva o existente?), y preferencias que cambien opciones (peso frente a
   calidad, conservar originales, WhatsApp, caras). Si ya tiene biblioteca, mira su estado
   con `scripts/estado_biblioteca.py` antes de proponer nada.
2. **Requisitos** (solo lo que ese comando necesita):
   - Pillow, siempre: `python -c "import PIL"`.
   - FFmpeg para vídeos, miniaturas de vídeo, fusionar vídeos y fecha de audios:
     `ffmpeg -version`. Falta → `winget install Gyan.FFmpeg` y abrir otra terminal. Sin él,
     `todo`/`google` omiten los vídeos con un aviso y `videos` no arranca.
   - `pillow-heif` si hay fotos `.HEIC` (iPhone); sin él se omiten con un aviso.
   - `opencv-python` para `--caras`; sin él se omiten con un aviso.
3. **Elige opciones** con criterio y explica el porqué de cada una que no sea la de por
   defecto (ver `references/flujos.md` para recetas y compromisos calidad/peso/tiempo).
4. **Simula, resume, confirma, ejecuta** (sección 2).
5. **Ejecuciones largas**: una biblioteca grande puede tardar horas (los vídeos se
   recodifican), e incluso su simulación tarda minutos (lee y calcula el hash de todo).
   Lánzala en segundo plano y sigue su salida, o recomienda el panel, que
   muestra fases, archivo actual y tiempo restante. No lances dos ejecuciones sobre la misma
   biblioteca a la vez (comparten catálogo). Para pararla, Ctrl+C (o *Detener* en el panel):
   se detiene en orden.
6. **Después**: lee el resumen que imprime el programa, revisa el informe CSV de
   `.exportador/informes/` si hubo errores, dañados o algo inesperado, y propone el siguiente
   paso natural (abrir la galería, *Limpiar repetidas*, fusionar con otra colección).

## 5. Investigar una biblioteca

Para preguntas como «¿por qué esta foto tiene fecha dudosa?», «¿de dónde viene este
archivo?», «¿por qué no se importó X?» o «¿qué hizo la última importación?», usa el script
de solo lectura (no necesita el paquete instalado):

```bash
python .claude/skills/exportador/scripts/estado_biblioteca.py "<biblioteca>"                # resumen
python .claude/skills/exportador/scripts/estado_biblioteca.py "<biblioteca>" --buscar IMG_1234
python .claude/skills/exportador/scripts/estado_biblioteca.py "<biblioteca>" --informe fusion
```

Con eso y `references/biblioteca.md` (estructura de carpetas, tablas del catálogo, columnas
y acciones de los informes, reglas de fecha y nombre) puedes explicar cualquier decisión.

## 6. Lo que no conviene hacer (y por qué)

- **Borrar archivos de la biblioteca a mano**: la siguiente importación los vuelve a traer
  (el catálogo nunca hace perder fotos). Para quitar algo de forma duradera, *Limpiar
  repetidas*, que lo manda a la papelera y lo anota para no reimportarlo.
- **Editar `catalogo.sqlite` o `galeria.json` a mano**: el programa los mantiene; consulta en
  solo lectura y, si algo está mal, regenera (`galeria --regenerar`) o reorganiza.
- **Poner la biblioteca dentro del origen** (o fusionar una colección que está dentro de la
  biblioteca): el programa lo rechaza; elige carpetas hermanas.
- **Abrir `galeria.html` con doble clic**: el navegador bloquea `file://`; siempre
  `galeria <biblioteca> --servir`.
- **Matar el proceso a la fuerza** mientras escribe: usa Ctrl+C; si hubo un corte, vuelve a
  lanzar el mismo comando.
- **Prometer lo que no hace**: no fusiona audios, no sube nada a internet, no edita
  etiquetas desde la galería (se ponen con el Explorador de Windows, Lightroom, digiKam… y
  aparecen al regenerar la galería).

## 7. Referencias (léelas cuando las necesites)

- `references/comandos.md` — todas las opciones de cada comando con su valor por defecto.
  Generada del `argparse` real; si dudas, `python -m exportador <comando> -h`.
- `references/flujos.md` — recetas completas: primera importación, volcados mensuales,
  ajustes de calidad y peso, WhatsApp, iPhone/HEIC, Google Takeout, fusionar, limpiar
  repetidas, galería con caras y lugares, reorganizar, panel.
- `references/biblioteca.md` — qué hay en una biblioteca: carpetas, nombres, fechas y su
  origen, catálogo SQLite, informes CSV y sus acciones, papelera, galería.
- `references/api.md` — usar el paquete desde Python (funciones, opciones, resúmenes).
- `references/problemas.md` — mensajes de error y avisos, y qué hacer con cada uno.
- `doc/ARQUITECTURA.md` (en la raíz del proyecto) — el porqué de cada decisión de diseño,
  con todo detalle. Consúltalo para dudas finas sobre fusionar, metadatos o Takeout.
