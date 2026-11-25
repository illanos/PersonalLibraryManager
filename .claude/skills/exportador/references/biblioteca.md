# Qué hay en una biblioteca

## Índice

1. Carpetas
2. Nombres
3. Fechas: de dónde sale cada una
4. Catálogo (`.exportador/catalogo.sqlite`)
5. Informes CSV
6. Papelera y «Limpiar repetidas»
7. Galería (`galeria.json`, `_galeria/`)
8. Carpeta de datos del programa
9. Consultas útiles (solo lectura)

## 1. Carpetas

```
Biblioteca/
├── 2024/08-Agosto/20240810_190211.jpg        fotos y vídeos, por fecha de captura
├── WhatsApp/2024/08-Agosto/20240810_WA0011.jpg   todo lo de WhatsApp, aparte
├── WhatsApp/Pegatinas/2024/08-Agosto/…       pegatinas (solo con --pegatinas-aparte)
├── WhatsApp/Audio/2024/08-Agosto/…           notas de voz de WhatsApp
├── Audio/2024/08-Agosto/…                    otros audios
├── originales/2024/08-Agosto/IMG_0101.JPG    copia intacta del original (--con-originales)
├── galeria.html + galeria.json               la galería web
├── _galeria/                                 thumbs/, favoritos.json, caras.sqlite, personas.json
└── .exportador/
    ├── catalogo.sqlite                       qué se importó o descartó, de dónde y cómo
    ├── informes/<tipo>_AAAAMMDD_HHMMSS.csv   uno por ejecución: fotos, videos, audio, fusion
    ├── informes/danados_*.csv                archivos dañados de cada ejecución
    ├── papelera/<ruta relativa>              lo quitado o sustituido (restaurable)
    └── limpieza.json                         decisiones de «Limpiar repetidas»
```

Los meses van como `01-Enero` … `12-Diciembre`. Las capturas de pantalla se quedan en la
línea de tiempo con su etiqueta. Al buscar archivos se saltan las carpetas ocultas
(`.algo`), `originales`, `_galeria`, `$RECYCLE.BIN`, `System Volume Information` y `@eaDir`.

## 2. Nombres

- `AAAAMMDD_HHMMSS.ext` con la fecha de captura; ráfagas del mismo segundo: `_01`, `_02`…
- Fecha solo con día (WhatsApp) y sin hora fiable: `AAAAMMDD_WA0011` (se conserva el número
  de WhatsApp en vez de inventar una hora).
- `AAAAMMDD_000000` solo aparece en bibliotecas antiguas: se arregla con
  `reorganizar --fechas-aproximadas` o `--renombrar-aproximadas`.
- Extensión de salida: `.jpg` (o `.webp` con `--formato webp`) en fotos; `.mp4` (h264/h265)
  o `.webm` (vp9) en vídeos. GIF animados y pegatinas se copian tal cual. Audio sin cambios.
- La fecha de modificación del archivo exportado se iguala a la de captura (el explorador
  ordena igual que la galería).

## 3. Fechas: de dónde sale cada una

`fuente_fecha` en catálogo, informes y galería:

| Fuente | Significado |
|---|---|
| `exif` | Fotos: `DateTimeOriginal` → `DateTimeDigitized` → `DateTime` |
| `metadatos` | Vídeo/audio: `creationdate` de Apple (hora local) o `creation_time` (UTC → hora local) |
| `nombre` | Del nombre del archivo (`IMG_20240512_102030`, WhatsApp, capturas…) |
| `google` | Del JSON del Takeout (`photoTakenTime`, UTC → hora local de este equipo) |
| `archivo` | Fecha de modificación del archivo: último recurso. La galería la marca **Fecha dudosa** |

Prioridad: metadatos del archivo > nombre con hora > JSON de Google > nombre sin hora >
fecha del archivo. Vídeos con fecha de cámara en el nombre (`VID_20160812_203028`): si los
metadatos se alejan más de 10 minutos, manda el nombre (Google reprocesa vídeos y cambia su
fecha). El nombre de los `PXL_…` de Pixel va en UTC y se pasa a hora local. *Hora
aproximada*: fecha del nombre sin hora + hora del archivo del mismo día.

## 4. Catálogo (`.exportador/catalogo.sqlite`)

Ábrelo solo en lectura (`?mode=ro`); lo mantiene el programa.

**`archivos`** — uno por archivo importado:
`hash` (MD5 del origen, clave), `tipo` (foto|video|audio), `origen` (ruta absoluta),
`tamano`, `mtime_ns`, `destino` (relativo, con `/`), `original` (copia en `originales/` o
NULL), `fecha` (ISO), `fuente_fecha`, `bytes_antes`, `bytes_despues`, `importado` (ISO),
`phash` (dHash de 128 bits en hex, fotos), `ancho`, `alto`.

**`descartes`** — lo que no se importa a propósito y no se vuelve a leer mientras no cambie:
`origen` (clave), `tamano`, `mtime_ns`, `tipo`, `motivo` (`danado` | `parecida` | `fusion`),
`problema` (vacío | sin cabecera válida | truncado | ilegible), `detalle`, `referencia`
(la copia buena), `fecha`.

**`descartadas`** — fotos quitadas con «Limpiar repetidas»: `hash`, `destino`, `fecha`. Su
contenido no se reimporta aunque siga en el origen ni aunque se vacíe la papelera.
Restaurar la foto la borra de aquí.

Si se borra a mano un archivo de la biblioteca, el catálogo deja de darlo por importado y la
siguiente importación lo trae otra vez.

## 5. Informes CSV

En `.exportador/informes/`, separador `;`, UTF-8 con BOM (Excel en español los abre bien).
En simulación no se escriben, salvo el de `fusionar`, que va a la carpeta temporal.

Columnas: `hora; accion; origen; destino; fecha_captura; fuente_fecha; bytes_antes;
bytes_despues; detalle; parecidas`.

Acciones al importar (`fotos_*`, `videos_*`, `audio_*`):

| Acción | Significado |
|---|---|
| `OK` | Exportado (recomprimido/reducido) |
| `SIN_CAMBIOS` | Copiado tal cual: recomprimir no compensaba |
| `COPIADO` | Audio copiado (nunca se recomprime) |
| `COPIADO_ANIMADO` | GIF/WebP animado copiado tal cual |
| `PEGATINA` | Pegatina de WhatsApp copiada tal cual |
| `DUPLICADO` | Mismo contenido que otro archivo (el detalle dice cuál) |
| `PARECIDA_OMITIDA` | Peor copia de un grupo de casi idénticas (`--omitir-parecidas`) |
| `OMITIDA` / `OMITIDO` | Versión `-editada` de Google cuyo original sí está |
| `DANADO` | Vacío, sin cabecera válida, truncado o ilegible (también en `danados_*.csv`) |
| `ERROR` | No se pudo procesar (el detalle dice por qué) |

Lo ya importado en ejecuciones anteriores no aparece en el informe (solo cuenta en el
resumen como *ya importados*).

Los dañados van además a `danados_<tipo>_*.csv` (solo si hay alguno y no es simulación) con
`origen; carpeta; problema; detalle; bytes; ya_conocido`. Al terminar, el programa imprime
un resumen de dañados por carpeta (también al simular). Nunca se importan ni se tocan en el
origen.

Acciones de `fusion_*`: `ANADIDA`, `SUSTITUYE`, `YA_ESTA`, `REPETIDA`, `QUITADA_ANTES`,
`METADATOS`, `ERROR` (ver `flujos.md`, receta 7). El detalle dice con qué copia se emparejó,
por qué gana una y qué metadatos gana.

## 6. Papelera y «Limpiar repetidas»

- `.exportador/papelera/<ruta relativa>`: lo quitado con «Limpiar repetidas» (con su copia
  de `originales/` si la hay) y lo sustituido al fusionar (`…_sustituida`). Se restaura
  desde la página *Limpiar repetidas → Papelera*; si el nombre está ocupado vuelve como
  `…_restaurada`.
- `limpieza.json`: historial de decisiones (`historial`), grupos marcados *no son
  repetidas*. Un grupo decidido no vuelve a salir salvo que se restaure una de sus fotos.

## 7. Galería

- `galeria.json`: `{version, titulo, elementos, nombres_caras}`. Cada elemento: `tipo`,
  `src` (ruta relativa), `nombre`, `carpeta`, `fecha`, `fuente_fecha`, `bytes`, `ancho`,
  `alto`, `thumb`, `dhash`, `nombre_original` y, si los hay, cámara, etiquetas, personas,
  lugar, GPS, título, descripción, valoración…
- Etiquetas automáticas: Selfies, Capturas, WhatsApp, Pegatinas, Con ubicación, Con
  estrellas, Verticales, Panorámicas, Fecha dudosa, Hora aproximada, Parecidas.
- `_galeria/thumbs/` miniaturas; `favoritos.json`; `caras.sqlite` (caras analizadas, cada
  foto una vez); `personas.json` (nombres puestos a los grupos de caras).
- Se sirve en `http://127.0.0.1:<puerto>/galeria.html` (8080 o el siguiente libre), solo
  accesible desde el propio equipo. Cada foto tiene enlace propio (`galeria.html#ruta`).

## 8. Carpeta de datos del programa

Ciudades (`lugares.tsv`), modelos de caras (`modelos/`) y preferencias del panel
(`panel.json`). Está en `EXPORTADOR_DATOS` si se define; si no, en `datos/` en la raíz del
proyecto (ejecutando desde `src/` o instalado en modo editable) o en
`%LOCALAPPDATA%\exportador` si el paquete se instaló de forma normal. No forma parte de
ninguna biblioteca.

## 9. Consultas útiles (solo lectura)

`scripts/estado_biblioteca.py` cubre lo habitual. Para algo más concreto:

```python
import sqlite3
from pathlib import Path
ruta = Path(r"D:\Biblioteca") / ".exportador" / "catalogo.sqlite"
db = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
# Fotos con fecha dudosa de 2019
db.execute("SELECT destino, origen FROM archivos WHERE fuente_fecha='archivo' AND fecha LIKE '2019%'").fetchall()
# Cuánto se ha ahorrado por tipo
db.execute("SELECT tipo, SUM(bytes_antes), SUM(bytes_despues) FROM archivos GROUP BY tipo").fetchall()
```
