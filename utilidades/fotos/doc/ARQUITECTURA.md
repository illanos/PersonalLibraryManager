# Exportador — Arquitectura y uso

## Qué es

Herramientas en Python para **importar, organizar, renombrar y optimizar** bibliotecas
personales de fotos, vídeos y notas de voz, más una **galería web local** para explorarlas y
buscar por etiquetas, personas, lugares, cámara o fecha.

Pensado para usarse una y otra vez sobre la misma biblioteca: cada importación solo procesa
lo nuevo, y todo lo calculado (hashes, fotos parecidas, archivos dañados, caras, lugares,
miniaturas) se guarda y se reutiliza.

## Estructura del proyecto

Es una de las utilidades del monorepo y vive en `utilidades/fotos/`; salvo que se diga otra
cosa, las rutas y los comandos de este documento son relativos a esa carpeta. Proyecto Python
estándar con *src layout*: el código es el paquete `exportador` dentro de `src/`, la
documentación en `doc/` y las pruebas en `tests/`.

```
utilidades/fotos/
├── pyproject.toml              Metadatos del paquete, dependencias y comando `exportador`
├── requirements.txt            Solo las dependencias (para usar el código sin instalarlo)
├── README.md                   Presentación, instalación y ejemplos
├── CLAUDE.md, MAPA.md          Guía y mapa del código para el agente (MAPA.md se genera)
├── panel.bat                   Abre el panel con doble clic (Windows; no hace falta instalar)
├── doc/
│   └── ARQUITECTURA.md         Este documento
├── src/
│   └── exportador/             El paquete
│       ├── __init__.py         Versión (__version__) y mapa de módulos
│       ├── __main__.py         `python -m exportador` → cli.ejecutar()
│       ├── cli.py              Comandos y opciones (argparse): fotos, videos, audio, todo, google,
│       │                       reorganizar, fusionar, galeria, panel
│       ├── media_utils.py      Utilidades comunes (fechas, nombres, listado, resumen, progreso)
│       ├── catalogo.py         Catálogo SQLite de lo importado y descartado + informe CSV
│       ├── clasificacion.py    WhatsApp, pegatinas, capturas y fotos en movimiento; carpeta
│       │                       de destino de cada cosa
│       ├── similares.py        Hash perceptual (dHash) y grupos de fotos parecidas
│       ├── danados.py          Detección e informe de archivos dañados
│       ├── metadatos.py        Lectura y conservación de metadatos de fotos (EXIF/XMP/IPTC)
│       ├── descargas.py        Carpeta de datos y descargas únicas de datos opcionales
│       ├── fotos.py            Importación de fotos (Pillow, en paralelo)
│       ├── videos.py           Importación de vídeos (ffprobe + FFmpeg, en paralelo, GPU opcional)
│       ├── audio.py            Importación de notas de voz y audio (copia sin recomprimir)
│       ├── takeout.py          Google Fotos (Takeout): cada archivo con su JSON y sus álbumes
│       ├── reorganizar.py      Ordenar una biblioteca ya importada (solo dentro de ella)
│       ├── fusionar.py         Añadir otra colección a la biblioteca sin repetir (por días, la mejor copia)
│       ├── fusion_metadatos.py Al fusionar: la copia que se queda gana los metadatos de las otras
│       ├── galeria.py          Índice de la galería y miniaturas
│       ├── lugares.py          Lugar a partir del GPS, sin conexión (GeoNames)
│       ├── caras.py            Detección y agrupación local de caras (OpenCV, opcional)
│       ├── limpieza.py         «Limpiar repetidas»: grupos, mejor copia, papelera, decisiones
│       ├── servidor.py         Servidor local de la galería (favoritos, caras y limpieza)
│       ├── panel.py            Panel web: opciones, ejecución y progreso
│       └── plantillas/         Interfaces web (HTML + JS sin dependencias), datos del paquete
│           ├── galeria.html    La galería (se copia a la biblioteca como galeria.html)
│           ├── limpiar.html    «Limpiar repetidas» (la sirve servidor.py como /limpiar.html)
│           └── panel.html      El panel (lo sirve panel.py)
├── tests/                      Pruebas automáticas (unittest); __init__.py añade src/ al path
└── datos/                      (no versionada) descargas y preferencias del panel, ver abajo
```

### Organización del código

Los módulos se importan entre sí con imports relativos (`from .catalogo import Catalogo`) y
forman capas; cada capa solo usa las de debajo. Los módulos pesados (vídeo, caras, servidor)
se importan dentro de las funciones que los necesitan, así `cli.py` arranca rápido y una
dependencia opcional que falte (OpenCV, FFmpeg) solo afecta a su comando.

```
Interfaces       cli ─────────── panel (lanza cli en otro proceso) ─── servidor (galería)
                  │                                                     │
Operaciones      fotos · videos · audio · takeout        galeria · lugares · caras · limpieza
sobre la         reorganizar · fusionar · fusion_metadatos
biblioteca        │
Base             media_utils · catalogo · clasificacion · similares · danados · metadatos · descargas
```

- **Puntos de entrada**: `python -m exportador` (`__main__.py`) y el comando `exportador`
  que instala `pyproject.toml` llaman a `cli.ejecutar()`, que trata Ctrl+Break como Ctrl+C
  y devuelve el código 130 al interrumpir. `cli.main(argv)` hace el trabajo y es lo que usan
  las pruebas y el panel (para leer el `argparse`).
- **Uso como librería**: cada comando es una función con sus opciones en una *dataclass*:
  `fotos.procesar_fotos(origen, destino, simular, OpcionesFotos(...))`,
  `videos.procesar_videos(..., OpcionesVideos(...))`, `audio.procesar_audio(...)`,
  `galeria.generar_galeria(carpeta, regenerar, caras)`, `servidor.servir(carpeta, puerto)`,
  `fusionar.fusionar(coleccion, biblioteca, simular, OpcionesFusion(...))`,
  `reorganizar.reorganizar(biblioteca, simular, whatsapp=..., fechas=...)` y
  `takeout.IndiceTakeout(carpeta)` (se pasa como `opciones.externos`). Las de importar,
  fusionar y reorganizar devuelven un diccionario con el resumen (importados, ya estaban,
  duplicados, dañados, errores, peso…); `generar_galeria`, si ha generado la galería.
- **Plantillas**: `plantillas/*.html` se incluyen en el paquete (`package-data`) y se
  localizan con `Path(__file__)`, así funcionan igual instalado que desde `src/`.
- **Carpeta de datos** (`descargas.carpeta_datos()`): ciudades de GeoNames, modelos de caras
  y preferencias del panel. Es la variable de entorno `EXPORTADOR_DATOS` si existe; si no,
  `datos/` en `utilidades/fotos/` cuando se ejecuta desde `src/` (o instalado en modo
  editable), y si el paquete está instalado normalmente, `%LOCALAPPDATA%\exportador`
  (Windows) o `~/.local/share/exportador`.
- **Pruebas**: `tests/__init__.py` pone `src/` el primero en `sys.path`, así las pruebas usan
  el código de esa misma carpeta aunque no esté instalado (o haya otra copia instalada).

## Instalación

```powershell
# Python 3.10+ desde python.org (marcar "Add to PATH")
pip install -e .            # el paquete (editable) y Pillow; añade el comando `exportador`
pip install -e ".[todo]"    # además pillow-heif (HEIC) y opencv-python (caras)
# FFmpeg para vídeos, miniaturas de vídeo y duración/fecha de los audios:
winget install Gyan.FFmpeg
```

Sin instalar el paquete también funciona: `pip install -r requirements.txt` y ejecutar desde
`src/` (`cd src; python -m exportador …`) o con `PYTHONPATH=src`. `panel.bat` ya lo hace así.

Dependencias opcionales (*extras* de `pyproject.toml`, también en `requirements.txt`): sin
ellas, la función se omite con un aviso.

| Paquete | Extra | Para qué |
|---|---|---|
| `pillow-heif` | `heic` | Fotos HEIC/HEIF del iPhone |
| `opencv-python` | `caras` | Caras en la galería (`galeria --caras`) |

Datos opcionales, descargados **una sola vez** a la carpeta de datos (después todo funciona
sin conexión):

```powershell
python -m exportador galeria "D:\Biblioteca" --descargar-lugares        # ciudades de GeoNames, ~3 MB
python -m exportador galeria "D:\Biblioteca" --descargar-modelos-caras  # YuNet + SFace, ~38 MB
```

## Uso

Todos los ejemplos usan `python -m exportador`; con el paquete instalado, `exportador` a
secas es lo mismo.

La forma más cómoda es el **panel web**: doble clic en `panel.bat` o

```powershell
python -m exportador panel        # abre http://127.0.0.1:8765/ en el navegador
```

Ahí se elige qué hacer (importar todo, solo fotos/vídeos/audio, galería, reorganizar o
fusionar otra colección), las carpetas (con *Examinar…*) y las opciones, y se lanza con
**Simular** o **Importar**. Ver
*El panel web* más abajo. Lo mismo desde la terminal:

```powershell
# Todo de una vez: fotos + vídeos + audio + galería. Primero en simulación (no toca nada):
python -m exportador todo "C:\Users\Tu\Pictures\Movil" --simular
python -m exportador todo "C:\Users\Tu\Pictures\Movil" --servir

# Por partes
python -m exportador fotos  "C:\Users\Tu\Pictures\Movil" --destino "D:\Biblioteca"
python -m exportador videos "C:\Users\Tu\Videos" --destino "D:\Biblioteca" --codec h265 --hw auto --hilos-video 2
python -m exportador audio  "C:\Users\Tu\Pictures\Movil" --destino "D:\Biblioteca"
python -m exportador galeria "D:\Biblioteca" --servir --caras

# Takeout de Google Fotos (fotos + vídeos + galería, con los metadatos de sus JSON)
python -m exportador google "G:\Takeout\Google Fotos" --destino "D:\Google" --simular
python -m exportador google "G:\Takeout\Google Fotos" --destino "D:\Google"

# Ordenar lo que se importó con versiones anteriores (solo dentro de la biblioteca)
python -m exportador reorganizar "D:\Biblioteca" --whatsapp --fechas-aproximadas --simular

# Añadir otra colección (p. ej. la biblioteca de Google Fotos) sin repetir nada
python -m exportador fusionar "D:\Google" --destino "D:\Biblioteca" --simular
python -m exportador fusionar "D:\Google" --destino "D:\Biblioteca"
```

Opciones principales (`python -m exportador <comando> -h` para verlas todas):

| Opción | Comando | Qué hace |
|---|---|---|
| `--destino` | fotos, videos, audio, todo, google | Biblioteca destino (por defecto `<origen>_organizados`) |
| `--simular` | todos menos galeria | Muestra qué haría sin crear, mover ni modificar nada |
| `--con-originales` | fotos, videos, todo | Guarda además una copia intacta de cada original en `originales/` |
| `--renombrar-aproximadas` | fotos, videos, audio, todo | Renombra también lo ya importado como `AAAAMMDD_000000` (ver *Fechas aproximadas*) |
| `--max-lado` | fotos, todo | Lado largo máximo de las fotos (3200; `0` = no reducir) |
| `--calidad` | fotos, todo | Calidad de compresión 1-100 (88) |
| `--formato jpeg\|webp` | fotos, todo | WebP pesa ~30 % menos |
| `--hilos N` | fotos, todo | Fotos en paralelo (por defecto, según núcleos) |
| `--omitir-parecidas` | fotos, todo | No importa la peor copia de cada grupo de fotos casi idénticas |
| `--pegatinas-aparte` | fotos, todo | Pegatinas de WhatsApp en `WhatsApp/Pegatinas/` |
| `--codec h264\|h265\|vp9` | videos, todo | MP4 universal, MP4 más ligero o WebM libre |
| `--max-lado-video` | videos, todo | Lado largo máximo de los vídeos (1920; en `videos` también `--max-lado`) |
| `--crf`, `--preset` | videos, todo | Calidad constante y velocidad de codificación |
| `--hilos-video N` | videos, todo | Vídeos codificándose a la vez (1) |
| `--hw auto\|nvenc\|qsv\|amf\|no` | videos, todo | Codificación por GPU; si falla, se repite por software (`no`) |
| `--sin-audio` | todo | No importar notas de voz ni audios |
| `--sin-galeria` | todo, google | No generar la galería al terminar |
| `--servir`, `--puerto` | galeria, todo | Abre la galería en el navegador |
| `--caras` | galeria, todo | Detecta y agrupa caras para nombrarlas (requiere `opencv-python`) |
| `--descargar-lugares`, `--descargar-modelos-caras` | galeria, todo | Descargas únicas de datos (ver arriba) |
| `--regenerar` | galeria | Rehace metadatos y miniaturas aunque no hayan cambiado |
| `--whatsapp`, `--fechas-aproximadas` | reorganizar | Qué reordenar en una biblioteca ya importada |
| `--umbral N` | fusionar | Bits (0-12) para que dos fotos sean la misma (5: copias recomprimidas o reducidas) |
| `--margen-dias N` | fusionar | Días antes y después con los que se compara (1; `0` = solo el mismo día) |
| `--max-lado`, `--calidad` | fusionar | Límite de la exportación en fotos: lo que pasa se exporta reducido (3200, 88) |
| `--max-lado-video N` | fusionar | Límite de la exportación en vídeos: lo que pasa se recodifica (1920; `0` = tal cual) |
| `--sin-metadatos` | fusionar | No pasar los metadatos de una copia a la que se queda |
| `--sin-galeria` | fusionar | No actualizar la galería de la biblioteca al terminar |

## Resultado

```
Biblioteca/
├── 2024/08-Agosto/20240810_190211.jpg       fotos y vídeos optimizados, por fecha de captura
├── WhatsApp/2024/08-Agosto/20240810_WA0011.jpg   todo lo de WhatsApp, separado del resto
├── WhatsApp/Pegatinas/2024/08-Agosto/…      pegatinas (solo con --pegatinas-aparte)
├── WhatsApp/Audio/2024/08-Agosto/…          notas de voz de WhatsApp
├── Audio/2024/08-Agosto/…                   otros audios
├── originales/2024/08-Agosto/IMG_0101.JPG   copia del original (solo con --con-originales)
├── .exportador/catalogo.sqlite              qué se importó o descartó, de dónde y con qué resultado
├── .exportador/informes/fotos_*.csv         una fila por archivo y ejecución (abre en Excel)
├── .exportador/informes/danados_*.csv       archivos dañados de cada ejecución
├── .exportador/papelera/…                   lo quitado con «Limpiar repetidas» o sustituido al fusionar
├── .exportador/limpieza.json                decisiones de «Limpiar repetidas» (seguir otro día)
├── galeria.html + galeria.json              galería web
└── _galeria/thumbs, favoritos.json, caras.sqlite, personas.json
```

## Decisiones de diseño

- **El origen solo se lee**: fotos, vídeos y audios se copian o recodifican hacia la
  biblioteca; en la carpeta de origen nunca se mueve, modifica ni borra nada (tampoco los
  duplicados, las parecidas ni los dañados). Por eso, por defecto, no se guarda otra copia del
  original; con `--con-originales` se añade una en `originales/`. `reorganizar` solo mueve
  archivos *dentro* de la biblioteca.
- **Importación incremental**: el catálogo guarda el MD5 de cada archivo importado. Lo ya
  importado (misma ruta, tamaño y fecha, o mismo contenido en otra ruta) se salta sin
  reprocesar. Lo descartado a propósito (dañados, peor copia de unas parecidas) queda en la
  tabla `descartes` y tampoco se vuelve a leer mientras no cambie. Si borras un archivo de la
  biblioteca, la siguiente importación lo vuelve a traer: el catálogo nunca hace perder fotos.
  La excepción son las fotos quitadas con *Limpiar repetidas*: su MD5 queda en la tabla
  `descartadas` y no se vuelven a importar (ni aunque se vacíe la papelera).
  Los catálogos antiguos se amplían solos (columnas y tablas nuevas) al abrirlos.
- **Fecha de captura**: fotos `EXIF DateTimeOriginal → DateTimeDigitized → DateTime`;
  vídeos `creationdate de Apple (hora local) → creation_time (UTC, se pasa a hora local)`;
  audio, metadatos con ffprobe. Si faltan, se deduce del nombre (`IMG_20240512_102030`,
  WhatsApp `IMG-20240512-WA0001`, `PTT-20240512-WA0001`, capturas…) y, en último caso, de la
  fecha del archivo. El informe y `--simular` dicen de dónde salió cada fecha; en la galería,
  las que vienen del archivo se marcan como *Fecha dudosa*.
- **Vídeos con la fecha de la cámara en el nombre** (`VID_20160812_203028`): si los metadatos
  se alejan más de 10 minutos, manda el nombre y el vídeo exportado lleva esa fecha en
  `creation_time`. En un Takeout real, 105 de 400 vídeos traían en los metadatos la fecha en
  que se volvieron a procesar (siempre posterior, de 20 minutos a 3 días); los demás
  coincidían con el nombre a menos de 10 minutos. El nombre de los `PXL_…` de Pixel va en
  UTC: se pasa a hora local antes de comparar, también si lleva algo delante
  (`.trashed-…-PXL_…`, de la papelera del móvil).
- **Fechas aproximadas**: si la fecha sale de un nombre *sin hora* (WhatsApp), se usa la hora
  de modificación del archivo cuando es del mismo día (etiqueta *Hora aproximada*); si no, el
  nombre lo dice claramente, `20260121_WA0011`, en vez de inventar `20260121_000000_18`. Solo
  afecta a lo nuevo; lo ya importado se renombra únicamente con `--renombrar-aproximadas` o
  `reorganizar --fechas-aproximadas`.
- **Nombre final** `AAAAMMDD_HHMMSS.ext`; las ráfagas del mismo segundo reciben `_01`, `_02`…
  en orden cronológico y de nombre original.
- **WhatsApp va aparte**: lo detecta `clasificacion.py` por el nombre (`IMG/VID/AUD/PTT/STK-
  AAAAMMDD-WA…`) o por estar en una carpeta de WhatsApp, y lo guarda en `WhatsApp/`, nunca
  mezclado con `Año/Mes`. En la galería no aparece en la línea de tiempo, la búsqueda ni los
  recuentos: solo en la vista *WhatsApp*, que hay que elegir explícitamente. Las pegatinas
  (`STK-*`, webp ≤ 512 px) se copian tal cual (transparencia) y las capturas se quedan en la
  línea de tiempo con su etiqueta, que permite ocultarlas.
- **Fotos parecidas** (`similares.py`): dHash de 128 bits calculado con Pillow sobre una
  versión de 9×8 en grises; dos copias recomprimidas o reducidas difieren en pocos bits. Para
  no comparar todas con todas, el hash se parte en bandas (si difieren en ≤ 12 bits, alguna
  banda coincide entera) y además se exige una proporción parecida. Al importar, el hash se
  guarda en el catálogo; el informe CSV lista las parecidas de cada foto y
  `--omitir-parecidas` no importa la peor (menos píxeles, sin EXIF, menos bytes). En la
  galería, el hash se calcula sobre la miniatura y se guarda en `galeria.json`.
- **Archivos dañados** (`danados.py`): vacíos, sin la firma de su formato o truncados (JPEG
  sin `FFD9` final o PNG sin `IEND`; solo entonces se decodifica para confirmarlo, porque hay
  JPEG válidos con datos añadidos al final). No se importan y van a un CSV aparte, con un
  resumen por carpeta al terminar (también en simulación).
- **Escritura atómica**: todo se escribe primero como `.part` y se renombra al final. Si se
  interrumpe (Ctrl+C, apagón), no quedan archivos a medias y basta con volver a ejecutar.
- **Si recomprimir no compensa** (la salida pesaría más) se conserva el original tal cual.
- **Nunca más calidad que la del original**: la de un JPEG se estima por su tabla de
  cuantización (como la escala libjpeg) y se recomprime como mucho a esa (`--calidad` es el
  máximo). Subirla no recupera detalle y solo engorda: en un Takeout de Google Fotos, con fotos
  ya recomprimidas por Google a calidad 66-79, el 22 % salía más grande que el original aun
  reduciéndolas a 3200 px; así pesan un 25 % menos (y las demás, un 7 % menos).
- **Vídeos**: primero se analiza todo en orden (nombres sin carreras) y luego se codifican
  `--hilos-video` a la vez; con Ctrl+C se matan todos los FFmpeg en marcha. `--hw` detecta los
  codificadores del FFmpeg instalado y prueba un fotograma para comprobar que la GPU
  responde; si un vídeo falla por hardware, se repite por software.
- **Vídeos verticales**: el escalado lo calcula FFmpeg sobre la imagen ya girada; usar las
  dimensiones de ffprobe (sin girar) deformaba los vídeos de móvil.
- **Calidad constante (CRF)** en vídeo, no bitrate fijo: escenas estáticas no desperdician espacio.
- **Audio** sin recomprimir: las notas de voz ya son pequeñas y cualquier conversión pierde.

## Google Fotos (Takeout)

`python -m exportador google <carpeta "Google Fotos" del Takeout> --destino <biblioteca>` hace lo
mismo que `todo` (fotos, vídeos, galería; admite sus opciones), pero lee antes todos los JSON
del Takeout (`takeout.py`) y graba en cada archivo exportado lo que dice el suyo. Los JSON no
se copian: su contenido queda dentro de las fotos y vídeos.

| Del JSON | Foto (JPEG/WebP) | Vídeo (MP4) | Cuándo |
|---|---|---|---|
| `photoTakenTime` | EXIF `DateTimeOriginal` + `OffsetTimeOriginal` | `creation_time` | Solo si el archivo no trae fecha (ver abajo) |
| `geoData` (o `geoDataExif`) | EXIF GPS | `location` (ISO 6709) | Solo si no trae GPS |
| `people` | XMP `Iptc4xmpExt:PersonInImage` | `keywords` | Se suman a las que tenga |
| `description` | XMP `dc:description` | `description` | Manda sobre la que tenga |
| álbumes | XMP `dc:subject` (etiquetas) | `keywords` | Se suman |
| `favorited` | XMP `xmp:Rating` = 5 | — | Si no tiene valoración |

- **Emparejado**: `foto.jpg.supplemental-metadata.json` (o el antiguo `foto.jpg.json`),
  `foto(1).jpg` ↔ `foto.jpg.supplemental-metadata(1).json`, títulos sin extensión
  (`07_04_13 - 1.supplemental-metadata.json`), nombres que Google recorta y, en último caso,
  el campo `title`. El resumen inicial dice cuántos archivos tienen JSON y cuántos no.
- **Fecha**: EXIF/metadatos del archivo > nombre con hora > JSON > nombre sin hora > fecha del
  archivo. En las fotos sin EXIF, `photoTakenTime` suele ser la fecha de *subida* (fotos de
  2012 fechadas un día después), por eso un nombre como `PANO_20120714_124817` manda; si el
  nombre solo trae el día (WhatsApp), el JSON aporta la hora si es del mismo día. La fecha del
  JSON está en UTC y se pasa a la hora local de este equipo. En el catálogo, fuente `google`.
- **Álbumes**: carpetas con `metadatos.json` (no las `Fotos del AAAA`). La misma foto aparece
  en `Fotos del AAAA` y en cada álbum (a veces el álbum solo trae el JSON): se reconoce por
  título + fecha de captura y se importa una sola vez (MD5) con los álbumes y personas de todas
  sus copias. Se ignoran los álbumes sin nombre útil (`Sin título`, fechas como `07/04/13`).
  A veces la copia de un álbum es otra versión, recomprimida o más pequeña (no es idéntica):
  con `--omitir-parecidas` no se importa y sus álbumes y personas pasan a la que queda (en un
  Takeout real, 820 fotos y 455 MB; la página «Limpiar repetidas» permite revisarlas después).
- **Versiones editadas** (`foto-editada.jpg`): se importa solo el original y la editada queda
  en el informe como `OMITIDA`; si el original no está, se importa la editada.
- **Fotos con movimiento** (`PXL_….MP.jpg` + `PXL_….MP`): la foto se recomprime como
  cualquier otra (pierde el vídeo incrustado, y su XMP deja de anunciarlo) y el clip `.MP` se
  importa como vídeo `.mp4` con la fecha de su foto, así ambos se llaman igual
  (`20260627_201032.jpg` y `20260627_201032.mp4`). Igual con los Live Photos de iPhone
  (`IMG_1.HEIC` + `IMG_1.MP4`) y las de Samsung (`X.jpg` + `X.MP4`): el vídeo no trae JSON y
  usa el de su foto.
- **Si recomprimir no compensa**, los metadatos se insertan igualmente sin recomprimir: en JPEG
  se reescriben solo los segmentos EXIF/XMP (píxeles, ICC, IPTC y lo que va tras la imagen,
  intactos) y los MP4/MOV se remultiplexan con `-c copy`.
- Los GIF animados y las pegatinas se copian tal cual: no reciben metadatos.
- **Si se mueve el Takeout** entre dos ejecuciones, basta con lanzar el comando con la ruta
  nueva: lo ya importado se reconoce por su contenido (MD5) y no se repite; solo tarda más la
  primera comprobación, porque hay que volver a leer los archivos.

## Metadatos

Al exportar una foto se conservan (ver `metadatos.py`):

| Metadato | Contiene | JPEG | WebP |
|---|---|---|---|
| EXIF | fecha, cámara, objetivo, exposición, GPS, etiquetas/título de Windows | ✅ | ✅ |
| XMP | etiquetas, valoración ★, título, descripción, personas (Lightroom, digiKam, Windows, Google…) | ✅ | ✅ |
| IPTC | palabras clave, pie de foto, autor | ✅ | ❌ (aviso) |
| ICC | perfil de color (Display P3 de móviles) | ✅ | ✅ |
| Comentario JPEG | | ✅ | — |

La rotación se aplica a los píxeles y la orientación se marca como normal en EXIF **y** XMP,
para que ningún visor la gire dos veces. Lo único que se descarta es la miniatura EXIF
interna, los mapas de profundidad/ganancia HDR y el vídeo incrustado de las fotos con
movimiento (Pixel, Samsung); de estas también se quita del XMP su anuncio
(`GCamera:MotionPhoto`, `Container:Directory`), que ya no apuntaría a nada. La fecha de modificación de la foto
exportada se pone igual a la de captura, así el explorador de archivos ordena igual que la
galería. En vídeo se copian los metadatos del contenedor (`-map_metadata 0` y, en MP4,
`use_metadata_tags`, que mantiene fecha local, cámara y ubicación del iPhone).

Para añadir etiquetas propias basta con cualquier programa que escriba XMP/IPTC/EXIF: el
Explorador de Windows (*Propiedades → Detalles → Etiquetas*), Lightroom, digiKam, Fotos…
Se conservan al exportar y aparecen en la galería al regenerarla.

## La galería web

`python -m exportador galeria <biblioteca> --servir` levanta un servidor en
`http://127.0.0.1:<puerto>/galeria.html` (solo accesible desde tu equipo) y abre el navegador.

- **Línea de tiempo** por meses, con filas justificadas y carga por lotes (miles de fotos).
- **Vista WhatsApp** aparte (botón *WhatsApp*): lo de WhatsApp nunca se mezcla con la línea
  de tiempo. Botón para ocultar las capturas (o, en la vista WhatsApp, las pegatinas).
- **Tipos**: fotos, vídeos, fotos en movimiento y **audio** (notas de voz con reproductor en
  el visor). Los años cuentan lo del tipo elegido.
- **Fotos en movimiento** (botón propio): los vídeos que duran menos de
  `clasificacion.SEGUNDOS_MOVIMIENTO` (5 s; los de 5 s justos, no), que son sobre todo los clips
  de las fotos con movimiento. Salen en *Todo* y con su botón, pero no en *Vídeos* ni al buscar
  «vídeo». Los de duración desconocida siguen en *Vídeos* y los de WhatsApp, en su vista. Es una
  etiqueta automática que se calcula en cada regeneración con la `duracion` de `galeria.json`
  (en décimas de segundo), también en lo que no ha cambiado: no mueve ni renombra archivos, no
  toca el catálogo y, si se cambia el umbral, basta con volver a generar la galería.
- **Etiquetas**: panel con contadores agrupado en *Etiquetas*, *Personas*, *Caras sin
  nombre*, *Lugares*, *Países*, *Cámaras* y *Automáticas* (Selfies, Capturas, WhatsApp,
  Pegatinas, Fotos en movimiento, Con ubicación, Con estrellas, Verticales, Panorámicas,
  Fecha dudosa, Hora aproximada, Parecidas). Los filtros se combinan entre sí.
- **Parecidas**: aviso en el visor con las miniaturas del grupo para comparar (no se borra nada).
- **Limpiar repetidas** (botón en la barra, o `http://127.0.0.1:<puerto>/limpiar.html`): ver
  la sección siguiente.
- **Lugares** a partir del GPS, sin conexión, si se han descargado las ciudades.
- **Caras** (con `--caras`): en la ficha de cada foto aparecen sus caras; al nombrar una, el
  nombre se aplica a todo su grupo y se suma a *Personas* (dar el mismo nombre a dos grupos
  los une). Los nombres se guardan en `_galeria/personas.json`.
- **Buscador** en nombre, fecha, mes, carpeta, cámara, etiquetas, personas, lugar, título,
  descripción y nombre original. Filtros por tipo, año, favoritos y orden.
- **Visor**: flechas o gestos, presentación (`P`), pantalla completa (`F`), favorito (`S`),
  ficha de información (`I`) con todos los metadatos, enlace al mapa y al original.
  Cada foto tiene su propio enlace (`galeria.html#ruta`), y el botón *Atrás* cierra el visor.
- **Favoritos** guardados en `_galeria/favoritos.json` (o en el navegador si se sirve con
  otro servidor).

Regenerar es incremental: lo que no ha cambiado reutiliza metadatos, miniatura, hash
perceptual y lugar; las caras se guardan en `_galeria/caras.sqlite` y cada foto se analiza
una sola vez. Los grupos de *Parecidas* también: solo se rehacen los que tocan fotos
nuevas, cambiadas o que ya no están (`galeria.json` guarda con qué umbral se calcularon; si
cambia, o con `--regenerar`, se rehacen todos). Para saber qué ha cambiado basta una
lectura de cada carpeta (tamaño y fecha de cada archivo, y qué miniaturas hay), sin abrir
nada. Con 45.800 archivos sin cambios, abrir la galería pasó de 2 min 15 s (comparando las
43.000 fotos entre sí en cada arranque) a unos 7 s.

El servidor admite peticiones parciales (para saltar en los vídeos y para Safari), rechaza
cabeceras `Host` que no sean locales (protección frente a *DNS rebinding*) y, si el puerto
está ocupado, prueba los siguientes. Abrir el HTML con doble clic no funciona: el navegador
bloquea la lectura de `galeria.json` desde `file://`.

## Limpiar repetidas

Herramienta para quitar copias sobrantes (sobre todo de WhatsApp), grupo a grupo. Solo
funciona con `--servir` (necesita el servidor). Lógica en `limpieza.py`, interfaz en
`plantillas/limpiar.html`.

- **Grupos**: los de *Parecidas* (dHash de `galeria.json`), con un **umbral ajustable** de
  0 (solo copias casi exactas) a 24 bits; 12 por defecto. Cada grupo muestra las fotos
  grandes una al lado de otra con resolución, peso (y el del original), fecha, nombre
  original, carpeta de origen (del catálogo) y marcas: EXIF de cámara, WhatsApp, *Sent*.
- **Propuesta**: se marca *conservar* la mejor copia y *quitar* las demás. La mejor es la de
  más píxeles (si difieren más de un 5 %); a igual resolución, la que tiene EXIF de cámara,
  luego la que no viene de WhatsApp, luego la que no es la enviada (`Sent/`) y por último la
  que más pesa. Se indica el motivo.
- **Teclado**: `←` `→` elegir foto, `Espacio` conservar/quitar (también clic), `Enter`
  confirmar y siguiente, `S` saltar (vuelve al final de la cola), `N` *no son repetidas* (no
  vuelve a salir), `A` o doble clic ampliar a **tamaño real** (con `←` `→` se cambia de copia
  manteniendo la misma zona), `Z` deshacer la última decisión. No deja quitar todas las
  copias de un grupo.
- **Progreso**: grupo *X de N*, espacio que libera el grupo y lo liberado en la sesión.
- **Decisiones en el servidor** (`.exportador/limpieza.json`), en cuanto se toman: se puede
  cerrar y seguir otro día. Un grupo decidido (o marcado *no son repetidas*) no vuelve a
  salir; si una foto suya se restaura, sí. Los grupos saltados solo se recuerdan mientras
  la página está abierta.
- **Borrado seguro**: lo quitado se **mueve** a `.exportador/papelera/<ruta relativa>` (con
  su copia de `originales/`, si la hay); nunca se borra directamente. `galeria.json` se
  actualiza al momento (sin esas fotos y con los grupos de parecidas recalculados). Desde
  *Papelera* se restaura una foto o todas (vuelven a su sitio, o con `_restaurada` si su
  nombre ya está ocupado) y se **vacía** con confirmación explícita (escribir `VACIAR`).
  El MD5 de lo quitado queda en la tabla `descartadas` del catálogo: la siguiente
  importación incremental no lo vuelve a traer (ni el mismo archivo desde otra ruta).
  Restaurar lo borra de esa tabla.
- **Límites**: solo actúa sobre fotos de la biblioteca servida. Se rechazan rutas
  absolutas, con `..` o `\`, en carpetas internas (`.exportador`, `_galeria`,
  `originales`) o que no sean fotos, y cualquier archivo que sea el *origen* de una
  importación. La carpeta de origen nunca se toca.
- **API** (`/api/limpieza/…`): `GET grupos?umbral=N` (incluye el token), `GET papelera`, y
  `POST decidir | no-repetidas | deshacer | restaurar | vaciar` (JSON). Los `POST` exigen
  `Origin` con el mismo host y puerto, `Sec-Fetch-Site: same-origin` (si el navegador lo
  envía) y la cabecera `X-Exportador-Token` con un secreto aleatorio de cada ejecución del
  servidor, que solo puede leer la propia página: otra web abierta en el navegador no puede
  provocar estas acciones (CSRF). Como el resto del servidor, solo escucha en 127.0.0.1.

## Fusionar colecciones

`python -m exportador fusionar <colección> --destino <biblioteca>` añade a una biblioteca las
fotos y vídeos de otra colección —otra biblioteca del exportador, como la de Google Fotos,
o cualquier carpeta— sin repetir lo que ya tiene. Lógica en `fusionar.py`.

- **Por días**: cada foto o vídeo de la colección solo se compara con los de la biblioteca
  del mismo día, ± `--margen-dias` (1 por defecto: fotos de cerca de medianoche o con la
  fecha en otra zona horaria). La fecha es la del catálogo de cada una (la de captura) y,
  si no hay catálogo, la de la galería o la del archivo.
- **Mismo original**: si el archivo original tiene el mismo nombre y la misma hora de
  captura (p. ej. `IMG_20160221_115858.jpg` importado del móvil en una y del Takeout en
  la otra), es la misma foto o vídeo aunque cada biblioteca lo haya reducido a su manera
  (su dHash llega a diferir ~10 bits; se exige ≤ 12 como comprobación) o esté girada 90°
  en una de las dos (se compara con el archivo girado). El «(1)» que Takeout añade a los
  nombres repetidos no cuenta. También si el original tiene el mismo MD5 en los dos
  catálogos, o los archivos son idénticos.
- **Fotos iguales**, si no: dHash a `--umbral` bits o menos (5 por defecto, lo que separa
  una foto de su copia recomprimida, reducida o reenviada), proporción compatible y, si
  las dos tienen fecha EXIF, exactamente la misma: las tomas de una ráfaga se separan un
  segundo y su dHash puede diferir solo 1-2 bits, pero no son copias, así que se añaden
  (el resumen las cuenta como *parecidas*, para revisarlas luego en *Limpiar repetidas*).
  Con `--omitir-parecidas` no se añade nada que se parezca (≤ 12 bits, como *Parecidas* en
  la galería) a una foto de la biblioteca sin llegar a ser igual: otras tomas, editadas,
  recortes. Van al informe como `PARECIDA`, con la foto a la que se parecen. Lo que solo se
  parece a otra de la propia colección sí entra (no está en ningún sitio más).
  Se usa el dHash del catálogo (calculado del original) antes que el de la galería (de la
  miniatura), que casa peor con el de otra biblioteca; si quedan cerca del umbral (6-12
  bits), decide el dHash calculado de los dos archivos.
- **Vídeos iguales** (requiere FFmpeg; sin él se omiten): duración casi igual (±1 s o
  ±2 %), proporción compatible y fotogramas parecidos (≤ 8 bits) en los mismos instantes,
  al 20, 50 y 80 % del más corto. Si los fotogramas no se pueden comparar (casi negros),
  no se dan por iguales.
- **Se queda la de más calidad**. Fotos: más resolución (si difieren más de un 5 %; lo
  que pasa del límite de la exportación cuenta ya reducido, como quedará en la
  biblioteca), EXIF de cámara, no WhatsApp, no la enviada (`Sent/`), más peso (+10 %).
  Vídeos: resolución, no WhatsApp, más bitrate (+10 %), metadatos de cámara. Si
  empatan, se queda la de la biblioteca.
  - Entre dos copias hechas del mismo archivo (el mismo MD5 del original en los dos
    catálogos) y con la misma resolución, el peso (o el bitrate) no cuenta: solo dice
    cómo se recomprimió cada una (p. ej. una biblioteca exportada antes de topar la
    calidad a la del original pesa más sin ser mejor). Gana la que sea el original tal
    cual (mismo tamaño y MD5 que el original); si ninguna lo es, se queda la de la
    biblioteca. Con el mismo nombre y hora sí cuenta: una puede venir de una versión
    recomprimida (el «ahorro de espacio» de Google Fotos).
  - La de la biblioteca es igual o mejor: la de la colección no se añade.
  - La de la colección es mejor: entra y la otra va a la **papelera** de la biblioteca
    (restaurable desde *Limpiar repetidas*, también los vídeos). Si las dos van a la misma
    carpeta con la misma extensión, la nueva **ocupa el nombre** de la antigua (siguen
    valiendo favoritos y enlaces) y la antigua va a la papelera como `…_sustituida`; si no,
    el favorito pasa a la nueva.
  - Con `--sin-sustituir` lo que ya está en la biblioteca no se cambia nunca: aunque la de
    la colección sea mejor, no se añade (el informe lo dice: «esta es mejor…, pero no se
    sustituye») y la de la biblioteca solo gana sus metadatos (salvo con `--sin-metadatos`).
    Para añadir una colección llena de copias de lo que ya hay sin que nada se mueva.
  - Dentro de la propia colección tampoco se repite nada: de varias copias entra la mejor.
  - Lo igual a una foto que se quitó antes con *Limpiar repetidas* (está en la papelera o
    su original en `descartadas`) no vuelve.
- **El límite de la exportación**: lo que entra (nuevo o mejor que otra) se copia tal
  cual, sin recomprimir, si está en un formato de la galería y dentro del límite; si lo
  pasa (fotos de más de `--max-lado` px, 3200; vídeos de más de `--max-lado-video`, 1920),
  se exporta como al importar: reducido y recomprimido. También se convierte lo que no
  está en un formato de la galería (HEIC, TIFF, AVI… a JPEG o MP4). Así un 4K de la
  colección no entra en 4K ni gana a la copia a 1080p por resolución: cuenta ya reducido.
  El contenido de WhatsApp va a `WhatsApp/`, como siempre.
- **Metadatos** (`fusion_metadatos.py`; `--sin-metadatos` para no tocarlos): de dos (o
  más) copias iguales, la que se queda gana lo que saben las otras, metadato a metadato,
  quedándose siempre con el que más información tiene:
  - Fotos: ubicación (el GPS entero: altitud, dirección…), cámara (marca, modelo,
    objetivo, exposición…), autor y copyright, de la otra solo si la que se queda no los
    tiene; de la misma cámara, los datos de la toma que le falten. Descripción y título:
    el más largo. Etiquetas (álbumes de Google) y personas: las de todas, sin repetir.
    Valoración (la favorita de Google es un 5): la más alta.
  - Fecha de captura: la de la otra, si la que se queda no la trae en sus metadatos y la
    suya es dudosa (la del archivo, la de subida) o sale del nombre sin hora el mismo día
    (gana la hora); una hora fiable del nombre no se pisa. Si es la misma hora y le falta
    la zona horaria, la zona. La fecha ganada va también al catálogo (la galería deja de
    marcarla como dudosa y la próxima fusión compara con el día bueno); si la que se
    queda entra nueva, entra ya con su carpeta y su nombre, y si es de la biblioteca,
    sigue en su carpeta.
  - Vídeos: fecha y ubicación si le faltan, la descripción más larga y todas las palabras
    clave.
  - Nada se recomprime: en un JPEG solo se reescriben los segmentos EXIF y XMP (los
    píxeles quedan byte a byte, como al importar un Takeout) y un MP4/MOV se
    remultiplexa sin recodificar; si la que se queda se exporta al entrar, los metadatos
    van en la exportación. Si se queda la de la biblioteca, se completa en su sitio
    (escritura atómica, misma fecha de archivo). PNG, WebP, GIF… no se pueden completar
    sin recomprimirlos: se dejan como están y el informe lo dice.
  - Cuenta cualquier copia igual: la de la colección que no entra, la sustituida de la
    biblioteca (pasa a la que la sustituye) y las repetidas dentro de la colección.
- **Espacio en disco**: antes de copiar nada calcula lo que ocupará lo que entra (lo mismo
  que en la colección, más ~60 KB de miniatura por archivo; lo sustituido va a la papelera
  del mismo disco y no libera nada). Si no cabe dejando 2 GB libres, no empieza y lo dice;
  en simulación, el resumen muestra el espacio libre y lo avisa.
- **Incremental**: lo añadido queda en el catálogo con la colección como origen, y lo
  descartado en `descartes` (motivo `fusion`, con la copia que se queda): una segunda
  fusión solo mira lo nuevo o lo que ha cambiado. Al terminar se actualiza la galería.
- **Simulación** (`--simular`): no toca la biblioteca ni la colección; el plan completo va
  a un CSV en la carpeta temporal del sistema para revisarlo en Excel antes de fusionar.
  Fuera de simulación, el CSV va a `.exportador/informes/fusion_*.csv`. Acciones:
  `ANADIDA`, `SUSTITUYE`, `YA_ESTA`, `REPETIDA`, `QUITADA_ANTES`, `PARECIDA`, `ERROR` y `METADATOS`
  (una de la biblioteca que gana los de otra copia); el detalle dice qué gana cada una.
- La colección **solo se lee**, y no puede estar dentro de la biblioteca ni al revés.
  Los audios no se fusionan.

## El panel web

`python -m exportador panel` (o `panel.bat`) levanta un servidor en `http://127.0.0.1:8765/`
(solo accesible desde tu equipo; si el puerto está ocupado, prueba los siguientes) y abre el
navegador.

- **Opciones**: salen del propio `argparse` de `cli.py` (valores por defecto, listas, ayudas
  y validación), así que la web y la línea de comandos nunca se desincronizan. Una opción
  nueva de la CLI aparece sola en *Otras opciones* hasta que se le dé un sitio en
  `plantillas/panel.html`. Debajo del formulario se ve el comando equivalente, para copiarlo.
- **Comprobación en vivo**: avisa antes de lanzar si la carpeta no existe, si el destino está
  dentro del origen o si un valor está fuera de rango, y dice qué biblioteca se usará y si ya
  existe (en ese caso solo se añade lo nuevo).
- **Ejecución**: cada ejecución es un `python -m exportador <comando> …` aparte, de una en
  una, lanzado desde la carpeta que contiene el paquete (`src/` o `site-packages`) y con ella
  en `PYTHONPATH`: siempre usa el mismo código que el panel, esté instalado o no. Los módulos emiten eventos de progreso (`media_utils.progreso`, líneas `@@progreso {json}`)
  solo cuando los lanza el panel (`EXPORTADOR_PROGRESO=1`); en la terminal no cambia nada.
- **Progreso**: fases (fotos, vídeos, audio, galería…), paso actual (*Analizando*,
  *Guardando*, *Codificando*, *Miniaturas*, *Caras*…), contador, archivo en curso, tiempo
  restante estimado, porcentaje de cada vídeo que se está codificando y el porcentaje en el
  título de la pestaña. Al terminar, resumen por fase (importados, ya estaban, duplicados,
  dañados, errores, peso antes → después) y botones para abrir la galería o la carpeta, y
  tras una simulación, para ejecutarlo de verdad con las mismas opciones.
- **Fusionar**: pide la colección a añadir y la biblioteca (la misma casilla que el destino
  al importar), con las secciones *Cómo comparar* (bits y días de margen) y *Lo que se
  añade*. El progreso muestra la lectura de las dos colecciones, la comparación por días y
  la copia; el resumen, cuántas son nuevas, mejores (sustituyen), ya estaban, repetidas y
  parecidas, el espacio, y un botón para abrir la carpeta del informe CSV.
- **Detener** equivale a Ctrl+C: el programa se detiene en orden (sin `.part` ni FFmpeg en
  marcha; en Windows se envía Ctrl+Break, que `cli.ejecutar` trata igual que Ctrl+C). Si no
  responde en 45 s, se fuerza el cierre.
- **Registro** completo en directo, con errores y avisos resaltados, filtro y descarga.
- **Preferencias**: las últimas opciones, carpetas recientes e historial de ejecuciones se
  guardan en `panel.json` dentro de la carpeta de datos (`datos/panel.json` desde el proyecto).
- **Seguridad**: igual que el servidor de la galería (solo `127.0.0.1`, cabeceras `Host` y
  `Origin` locales) y además exige JSON en los POST, así que ninguna web puede lanzar nada.

## Pruebas

```powershell
python -m unittest discover -s tests -t .
```

Desde `utilidades/fotos/`, sin necesidad de instalar el paquete (`tests/__init__.py` añade
`src/`). Los tests de vídeo simulan ffprobe y FFmpeg (también la GPU), y los de caras usan un
motor falso, así que no necesitan FFmpeg ni OpenCV instalados. Para simular una dependencia
se parchea en el módulo del paquete: `mock.patch("exportador.videos.sondear", ...)`.

## Skill de Claude Code

`.claude/skills/exportador/` (en la raíz del monorepo, como las de las demás utilidades) es
una *skill* para Claude Code que conoce todos los comandos, opciones, flujos de trabajo, la
estructura de la biblioteca y la API del paquete. Al abrir Claude Code en el monorepo se
carga sola cuando se le pide ayuda para importar, fusionar, limpiar, generar la galería o
entender un informe. Su regla principal es la del propio programa: primero `--simular`, y
nada real sin confirmación.

```
.claude/skills/exportador/
├── SKILL.md                  Cómo ayudar: ejecutar, simular y confirmar, qué comando usar
├── references/
│   ├── comandos.md           Todas las opciones (generado del argparse; no editar a mano)
│   ├── flujos.md             Recetas: móvil, WhatsApp, iPhone, Takeout, fusionar, limpiar…
│   ├── biblioteca.md         Carpetas, nombres, fechas, catálogo, informes, papelera
│   ├── api.md                Uso del paquete desde Python
│   └── problemas.md          Mensajes de error y avisos, y qué hacer
└── scripts/
    ├── opciones.py           Genera comandos.md desde cli.construir_parser()
    └── estado_biblioteca.py  Resumen de una biblioteca y búsqueda de un archivo (solo lectura)
```

Si cambia un comando o una opción, regenera la referencia con
`python .claude/skills/exportador/scripts/opciones.py --escribir` (desde la raíz del monorepo);
`tests/test_skill.py` falla mientras no coincida con la CLI o si la skill cita opciones o
comandos que no existen.
Si cambia el comportamiento (no solo las opciones), revisa también `flujos.md`.

## Posibles ampliaciones

- Panel accesible desde el móvil en la red local (con contraseña).
- Editar etiquetas desde la galería y escribirlas en el XMP de la foto.
- Búsqueda por línea de comandos (`exportador buscar --etiqueta playa --copiar-a ...`).
- Mapa con las fotos geolocalizadas.
- Compartir la galería en la red local (con contraseña) para verla en el móvil o la tele.
