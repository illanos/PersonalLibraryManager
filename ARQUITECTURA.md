# Exportador — Arquitectura y uso

## Qué es

Herramientas en Python para **importar, organizar, renombrar y optimizar** bibliotecas
personales de fotos y vídeos, más una **galería web local** para explorarlas y buscar por
etiquetas, personas, cámara o fecha.

Pensado para usarse una y otra vez sobre la misma biblioteca: cada importación solo procesa
lo nuevo.

## Estructura del proyecto

```
Exportador/
├── main.py                 Punto de entrada (CLI: fotos, videos, todo, galeria)
├── media_utils.py          Utilidades comunes (fechas, nombres, listado, resumen)
├── catalogo.py             Catálogo SQLite de lo importado + informe CSV
├── metadatos.py            Lectura y conservación de metadatos de fotos (EXIF/XMP/IPTC)
├── fotos.py                Importación de fotos (Pillow, en paralelo)
├── videos.py               Importación de vídeos (ffprobe + FFmpeg)
├── galeria.py              Índice de la galería y miniaturas
├── galeria_plantilla.html  Interfaz web (HTML + JS sin dependencias)
├── servidor.py             Servidor local de la galería
├── tests/                  Pruebas automáticas (unittest)
├── requirements.txt
└── ARQUITECTURA.md         Este documento
```

## Instalación

```powershell
# Python 3.10+ desde python.org (marcar "Add to PATH")
pip install -r requirements.txt
# FFmpeg para vídeos y miniaturas de vídeo:
winget install Gyan.FFmpeg
```

`pillow-heif` (en `requirements.txt`) es opcional: sin él las fotos HEIC del iPhone se omiten
con un aviso.

## Uso

```powershell
# Todo de una vez: fotos + vídeos + galería. Primero en simulación (no toca nada):
python main.py todo "C:\Users\Tu\Pictures\Movil" --simular
python main.py todo "C:\Users\Tu\Pictures\Movil" --servir

# Por partes
python main.py fotos  "C:\Users\Tu\Pictures\Movil" --destino "D:\Biblioteca"
python main.py videos "C:\Users\Tu\Videos" --destino "D:\Biblioteca" --codec h265
python main.py galeria "D:\Biblioteca" --servir
```

Opciones principales (`python main.py <comando> -h` para verlas todas):

| Opción | Comando | Qué hace |
|---|---|---|
| `--destino` | fotos, videos, todo | Biblioteca destino (por defecto `<origen>_organizados`) |
| `--simular` | fotos, videos, todo | Muestra qué haría sin crear, mover ni modificar nada |
| `--max-lado` | fotos, todo | Lado largo máximo de las fotos (2560; `0` = no reducir) |
| `--calidad` | fotos, todo | Calidad de compresión 1-100 (88) |
| `--formato jpeg\|webp` | fotos, todo | WebP pesa ~30 % menos |
| `--sin-originales` | fotos, todo | No guarda copia de las fotos originales |
| `--hilos N` | fotos, todo | Fotos en paralelo (por defecto, según núcleos) |
| `--codec h264\|h265\|vp9` | videos, todo | MP4 universal, MP4 más ligero o WebM libre |
| `--max-lado-video` | videos, todo | Lado largo máximo de los vídeos (1920; en `videos` también `--max-lado`) |
| `--crf`, `--preset` | videos, todo | Calidad constante y velocidad de codificación |
| `--servir`, `--puerto` | galeria, todo | Abre la galería en el navegador |
| `--regenerar` | galeria | Rehace metadatos y miniaturas aunque no hayan cambiado |

## Resultado

```
Biblioteca/
├── 2024/08-Agosto/20240810_190211.jpg     fotos y vídeos optimizados, por fecha de captura
├── originales/2024/08-Agosto/IMG_0101.JPG copia intacta del original
├── .exportador/catalogo.sqlite            qué se importó, de dónde y con qué resultado
├── .exportador/informes/fotos_*.csv       una fila por archivo y ejecución (abre en Excel)
├── galeria.html + galeria.json            galería web
└── _galeria/thumbs, _galeria/favoritos.json
```

## Decisiones de diseño

- **Fecha de captura**: fotos `EXIF DateTimeOriginal → DateTimeDigitized → DateTime`;
  vídeos `creationdate de Apple (hora local) → creation_time (UTC, se pasa a hora local)`.
  Si faltan, se deduce del nombre (`IMG_20240512_102030`, WhatsApp `IMG-20240512-WA0001`,
  capturas…) y, en último caso, de la fecha del archivo. El informe y `--simular` dicen de
  dónde salió cada fecha; en la galería, las que vienen del archivo se marcan como
  *Fecha dudosa*.
- **Nombre final** `AAAAMMDD_HHMMSS.ext`; las ráfagas del mismo segundo reciben `_01`, `_02`…
  en orden cronológico y de nombre original.
- **Importación incremental**: el catálogo guarda el MD5 de cada archivo importado. Lo ya
  importado (misma ruta, tamaño y fecha, o mismo contenido en otra ruta) se salta sin
  reprocesar. Si borras un archivo de la biblioteca, la siguiente importación lo vuelve a
  traer: el catálogo nunca hace perder fotos.
- **Nada se destruye**: los duplicados se dejan en el origen; las fotos se copian (el origen
  queda intacto) y se guarda otra copia en `originales/`; los vídeos se mueven a
  `originales/` solo cuando la versión nueva está terminada.
- **Escritura atómica**: todo se escribe primero como `.part` y se renombra al final. Si se
  interrumpe (Ctrl+C, apagón), no quedan archivos a medias y basta con volver a ejecutar.
- **Si recomprimir no compensa** (la salida pesaría más) se conserva el original tal cual.
- **Vídeos verticales**: el escalado lo calcula FFmpeg sobre la imagen ya girada; usar las
  dimensiones de ffprobe (sin girar) deformaba los vídeos de móvil.
- **Calidad constante (CRF)** en vídeo, no bitrate fijo: escenas estáticas no desperdician espacio.

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
- **Etiquetas**: panel con contadores agrupado en *Etiquetas*, *Personas*, *Cámaras* y
  *Automáticas* (Selfies, Capturas de pantalla, WhatsApp, Con ubicación, Con estrellas,
  Verticales, Panorámicas, Fecha dudosa). Los filtros se combinan entre sí.
- **Buscador** en nombre, fecha, mes, carpeta, cámara, etiquetas, personas, título,
  descripción y nombre original. Filtros por tipo, año, favoritos y orden.
- **Visor**: flechas o gestos, presentación (`P`), pantalla completa (`F`), favorito (`S`),
  ficha de información (`I`) con todos los metadatos, enlace al mapa y al original.
  Cada foto tiene su propio enlace (`galeria.html#ruta`), y el botón *Atrás* cierra el visor.
- **Favoritos** guardados en `_galeria/favoritos.json` (o en el navegador si se sirve con
  otro servidor).

Regenerar es incremental: lo que no ha cambiado reutiliza metadatos y miniatura.

El servidor admite peticiones parciales (para saltar en los vídeos y para Safari), rechaza
cabeceras `Host` que no sean locales (protección frente a *DNS rebinding*) y, si el puerto
está ocupado, prueba los siguientes. Abrir el HTML con doble clic no funciona: el navegador
bloquea la lectura de `galeria.json` desde `file://`.

## Pruebas

```powershell
python -m unittest
```

Los tests de vídeo simulan ffprobe y FFmpeg, así que no necesitan tenerlos instalados.

## Posibles ampliaciones

- Editar etiquetas desde la galería y escribirlas en el XMP de la foto.
- Búsqueda por línea de comandos (`main.py buscar --etiqueta playa --copiar-a ...`).
- Mapa con las fotos geolocalizadas y nombre del lugar (requiere conexión).
- Detección de fotos casi iguales (ráfagas) con hash perceptual.
- Compartir la galería en la red local (con contraseña) para verla en el móvil o la tele.
