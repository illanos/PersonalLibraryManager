# Exportador — Arquitectura y uso

## Qué es

Herramientas en Python para **importar, organizar, renombrar y optimizar** bibliotecas
personales de fotos, vídeos y notas de voz, más una **galería web local** para explorarlas y
buscar por etiquetas, personas, lugares, cámara o fecha.

Pensado para usarse una y otra vez sobre la misma biblioteca: cada importación solo procesa
lo nuevo, y todo lo calculado (hashes, fotos parecidas, archivos dañados, caras, lugares,
miniaturas) se guarda y se reutiliza.

## Estructura del proyecto

```
Exportador/
├── main.py                 Punto de entrada (CLI: fotos, videos, audio, todo, reorganizar, galeria)
├── media_utils.py          Utilidades comunes (fechas, nombres, listado, resumen)
├── catalogo.py             Catálogo SQLite de lo importado y descartado + informe CSV
├── clasificacion.py        WhatsApp, pegatinas y capturas; carpeta de destino de cada cosa
├── similares.py            Hash perceptual (dHash) y grupos de fotos parecidas
├── danados.py              Detección e informe de archivos dañados
├── metadatos.py            Lectura y conservación de metadatos de fotos (EXIF/XMP/IPTC)
├── fotos.py                Importación de fotos (Pillow, en paralelo)
├── videos.py               Importación de vídeos (ffprobe + FFmpeg, en paralelo, GPU opcional)
├── audio.py                Importación de notas de voz y audio (copia sin recomprimir)
├── reorganizar.py          Ordenar una biblioteca ya importada (solo dentro de ella)
├── galeria.py              Índice de la galería y miniaturas
├── lugares.py              Lugar a partir del GPS, sin conexión (GeoNames)
├── caras.py                Detección y agrupación local de caras (OpenCV, opcional)
├── descargas.py            Descargas únicas de datos opcionales a datos/
├── galeria_plantilla.html  Interfaz web (HTML + JS sin dependencias)
├── servidor.py             Servidor local de la galería (favoritos y nombres de caras)
├── tests/                  Pruebas automáticas (unittest)
├── requirements.txt
└── ARQUITECTURA.md         Este documento
```

## Instalación

```powershell
# Python 3.10+ desde python.org (marcar "Add to PATH")
pip install -r requirements.txt
# FFmpeg para vídeos, miniaturas de vídeo y duración/fecha de los audios:
winget install Gyan.FFmpeg
```

Dependencias opcionales (en `requirements.txt`): sin ellas, la función se omite con un aviso.

| Paquete | Para qué |
|---|---|
| `pillow-heif` | Fotos HEIC/HEIF del iPhone |
| `opencv-python` | Caras en la galería (`galeria --caras`) |

Datos opcionales, descargados **una sola vez** a `datos/` (después todo funciona sin conexión):

```powershell
python main.py galeria "D:\Biblioteca" --descargar-lugares        # ciudades de GeoNames, ~3 MB
python main.py galeria "D:\Biblioteca" --descargar-modelos-caras  # YuNet + SFace, ~38 MB
```

## Uso

```powershell
# Todo de una vez: fotos + vídeos + audio + galería. Primero en simulación (no toca nada):
python main.py todo "C:\Users\Tu\Pictures\Movil" --simular
python main.py todo "C:\Users\Tu\Pictures\Movil" --servir

# Por partes
python main.py fotos  "C:\Users\Tu\Pictures\Movil" --destino "D:\Biblioteca"
python main.py videos "C:\Users\Tu\Videos" --destino "D:\Biblioteca" --codec h265 --hw auto --hilos-video 2
python main.py audio  "C:\Users\Tu\Pictures\Movil" --destino "D:\Biblioteca"
python main.py galeria "D:\Biblioteca" --servir --caras

# Ordenar lo que se importó con versiones anteriores (solo dentro de la biblioteca)
python main.py reorganizar "D:\Biblioteca" --whatsapp --fechas-aproximadas --simular
```

Opciones principales (`python main.py <comando> -h` para verlas todas):

| Opción | Comando | Qué hace |
|---|---|---|
| `--destino` | fotos, videos, audio, todo | Biblioteca destino (por defecto `<origen>_organizados`) |
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
| `--sin-galeria` | todo | No generar la galería al terminar |
| `--servir`, `--puerto` | galeria, todo | Abre la galería en el navegador |
| `--caras` | galeria, todo | Detecta y agrupa caras para nombrarlas (requiere `opencv-python`) |
| `--descargar-lugares`, `--descargar-modelos-caras` | galeria, todo | Descargas únicas de datos (ver arriba) |
| `--regenerar` | galeria | Rehace metadatos y miniaturas aunque no hayan cambiado |
| `--whatsapp`, `--fechas-aproximadas` | reorganizar | Qué reordenar en una biblioteca ya importada |

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
  Los catálogos antiguos se amplían solos (columnas y tablas nuevas) al abrirlos.
- **Fecha de captura**: fotos `EXIF DateTimeOriginal → DateTimeDigitized → DateTime`;
  vídeos `creationdate de Apple (hora local) → creation_time (UTC, se pasa a hora local)`;
  audio, metadatos con ffprobe. Si faltan, se deduce del nombre (`IMG_20240512_102030`,
  WhatsApp `IMG-20240512-WA0001`, `PTT-20240512-WA0001`, capturas…) y, en último caso, de la
  fecha del archivo. El informe y `--simular` dicen de dónde salió cada fecha; en la galería,
  las que vienen del archivo se marcan como *Fecha dudosa*.
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
- **Vídeos**: primero se analiza todo en orden (nombres sin carreras) y luego se codifican
  `--hilos-video` a la vez; con Ctrl+C se matan todos los FFmpeg en marcha. `--hw` detecta los
  codificadores del FFmpeg instalado y prueba un fotograma para comprobar que la GPU
  responde; si un vídeo falla por hardware, se repite por software.
- **Vídeos verticales**: el escalado lo calcula FFmpeg sobre la imagen ya girada; usar las
  dimensiones de ffprobe (sin girar) deformaba los vídeos de móvil.
- **Calidad constante (CRF)** en vídeo, no bitrate fijo: escenas estáticas no desperdician espacio.
- **Audio** sin recomprimir: las notas de voz ya son pequeñas y cualquier conversión pierde.

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
interna y los mapas de profundidad/ganancia HDR. La fecha de modificación de la foto
exportada se pone igual a la de captura, así el explorador de archivos ordena igual que la
galería. En vídeo se copian los metadatos del contenedor (`-map_metadata 0` y, en MP4,
`use_metadata_tags`, que mantiene fecha local, cámara y ubicación del iPhone).

Para añadir etiquetas propias basta con cualquier programa que escriba XMP/IPTC/EXIF: el
Explorador de Windows (*Propiedades → Detalles → Etiquetas*), Lightroom, digiKam, Fotos…
Se conservan al exportar y aparecen en la galería al regenerarla.

## La galería web

`python main.py galeria <biblioteca> --servir` levanta un servidor en
`http://127.0.0.1:<puerto>/galeria.html` (solo accesible desde tu equipo) y abre el navegador.

- **Línea de tiempo** por meses, con filas justificadas y carga por lotes (miles de fotos).
- **Vista WhatsApp** aparte (botón *WhatsApp*): lo de WhatsApp nunca se mezcla con la línea
  de tiempo. Botón para ocultar las capturas (o, en la vista WhatsApp, las pegatinas).
- **Tipos**: fotos, vídeos y **audio** (notas de voz con reproductor en el visor).
- **Etiquetas**: panel con contadores agrupado en *Etiquetas*, *Personas*, *Caras sin
  nombre*, *Lugares*, *Países*, *Cámaras* y *Automáticas* (Selfies, Capturas, WhatsApp,
  Pegatinas, Con ubicación, Con estrellas, Verticales, Panorámicas, Fecha dudosa, Hora
  aproximada, Parecidas). Los filtros se combinan entre sí.
- **Parecidas**: aviso en el visor con las miniaturas del grupo para comparar (no se borra nada).
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
una sola vez.

El servidor admite peticiones parciales (para saltar en los vídeos y para Safari), rechaza
cabeceras `Host` que no sean locales (protección frente a *DNS rebinding*) y, si el puerto
está ocupado, prueba los siguientes. Abrir el HTML con doble clic no funciona: el navegador
bloquea la lectura de `galeria.json` desde `file://`.

## Pruebas

```powershell
python -m unittest discover -s tests -t .
```

Los tests de vídeo simulan ffprobe y FFmpeg (también la GPU), y los de caras usan un motor
falso, así que no necesitan FFmpeg ni OpenCV instalados.

## Posibles ampliaciones

- Editar etiquetas desde la galería y escribirlas en el XMP de la foto.
- Búsqueda por línea de comandos (`main.py buscar --etiqueta playa --copiar-a ...`).
- Mapa con las fotos geolocalizadas.
- Compartir la galería en la red local (con contraseña) para verla en el móvil o la tele.
