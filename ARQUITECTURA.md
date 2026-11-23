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
├── main.py                 Punto de entrada (CLI: fotos, videos, audio, todo, reorganizar, fusionar, galeria, panel)
├── media_utils.py          Utilidades comunes (fechas, nombres, listado, resumen)
├── catalogo.py             Catálogo SQLite de lo importado y descartado + informe CSV
├── clasificacion.py        WhatsApp, pegatinas y capturas; carpeta de destino de cada cosa
├── similares.py            Hash perceptual (dHash) y grupos de fotos parecidas
├── limpieza.py             «Limpiar repetidas»: grupos, mejor copia, papelera, decisiones
├── danados.py              Detección e informe de archivos dañados
├── metadatos.py            Lectura y conservación de metadatos de fotos (EXIF/XMP/IPTC)
├── fotos.py                Importación de fotos (Pillow, en paralelo)
├── videos.py               Importación de vídeos (ffprobe + FFmpeg, en paralelo, GPU opcional)
├── audio.py                Importación de notas de voz y audio (copia sin recomprimir)
├── reorganizar.py          Ordenar una biblioteca ya importada (solo dentro de ella)
├── fusionar.py             Añadir otra colección a la biblioteca sin repetir (por días, la mejor copia)
├── galeria.py              Índice de la galería y miniaturas
├── lugares.py              Lugar a partir del GPS, sin conexión (GeoNames)
├── caras.py                Detección y agrupación local de caras (OpenCV, opcional)
├── descargas.py            Descargas únicas de datos opcionales a datos/
├── galeria_plantilla.html  Interfaz web (HTML + JS sin dependencias)
├── limpiar_plantilla.html  Página «Limpiar repetidas» (la sirve servidor.py como limpiar.html)
├── servidor.py             Servidor local de la galería (favoritos, caras y limpieza)
├── panel.py                Panel web: opciones, ejecución y progreso (python main.py panel)
├── panel.html              Interfaz del panel (HTML + JS sin dependencias)
├── panel.bat               Abre el panel con doble clic (Windows)
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

La forma más cómoda es el **panel web**: doble clic en `panel.bat` o

```powershell
python main.py panel        # abre http://127.0.0.1:8765/ en el navegador
```

Ahí se elige qué hacer (importar todo, solo fotos/vídeos/audio, galería, reorganizar o
fusionar otra colección), las carpetas (con *Examinar…*) y las opciones, y se lanza con
**Simular** o **Importar**. Ver
*El panel web* más abajo. Lo mismo desde la terminal:

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

# Añadir otra colección (p. ej. la biblioteca de Google Fotos) sin repetir nada
python main.py fusionar "D:\Google" --destino "D:\Biblioteca" --simular
python main.py fusionar "D:\Google" --destino "D:\Biblioteca"
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
| `--umbral N` | fusionar | Bits (0-12) para que dos fotos sean la misma (5: copias recomprimidas o reducidas) |
| `--margen-dias N` | fusionar | Días antes y después con los que se compara (1; `0` = solo el mismo día) |
| `--max-lado`, `--calidad` | fusionar | Solo para lo que hay que reducir o convertir al añadir (3200, 88) |
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
una sola vez.

El servidor admite peticiones parciales (para saltar en los vídeos y para Safari), rechaza
cabeceras `Host` que no sean locales (protección frente a *DNS rebinding*) y, si el puerto
está ocupado, prueba los siguientes. Abrir el HTML con doble clic no funciona: el navegador
bloquea la lectura de `galeria.json` desde `file://`.

## Limpiar repetidas

Herramienta para quitar copias sobrantes (sobre todo de WhatsApp), grupo a grupo. Solo
funciona con `--servir` (necesita el servidor). Lógica en `limpieza.py`, interfaz en
`limpiar_plantilla.html`.

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

`python main.py fusionar <colección> --destino <biblioteca>` añade a una biblioteca las
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
  Se usa el dHash del catálogo (calculado del original) antes que el de la galería (de la
  miniatura), que casa peor con el de otra biblioteca; si quedan cerca del umbral (6-12
  bits), decide el dHash calculado de los dos archivos.
- **Vídeos iguales** (requiere FFmpeg; sin él se omiten): duración casi igual (±1 s o
  ±2 %), proporción compatible y fotogramas parecidos (≤ 8 bits) en los mismos instantes,
  al 20, 50 y 80 % del más corto. Si los fotogramas no se pueden comparar (casi negros),
  no se dan por iguales.
- **Se queda la de más calidad**. Fotos: más resolución (si difieren más de un 5 %; lo
  que se va a reducir al añadirlo cuenta ya reducido), EXIF de cámara, no WhatsApp, no la
  enviada (`Sent/`), más peso (+10 %). Vídeos: resolución, no WhatsApp, más bitrate
  (+10 %), metadatos de cámara. Si empatan, se queda la de la biblioteca.
  - La de la biblioteca es igual o mejor: la de la colección no se añade.
  - La de la colección es mejor: entra y la otra va a la **papelera** de la biblioteca
    (restaurable desde *Limpiar repetidas*, también los vídeos). Si las dos van a la misma
    carpeta con la misma extensión, la nueva **ocupa el nombre** de la antigua (siguen
    valiendo favoritos y enlaces) y la antigua va a la papelera como `…_sustituida`; si no,
    el favorito pasa a la nueva.
  - Dentro de la propia colección tampoco se repite nada: de varias copias entra la mejor.
  - Lo igual a una foto que se quitó antes con *Limpiar repetidas* (está en la papelera o
    su original en `descartadas`) no vuelve.
- **Sin recomprimir**: lo que entra se copia tal cual si ya está en un formato de la
  galería; solo se reduce (fotos de más de `--max-lado`) o se convierte (HEIC, TIFF, AVI…
  a JPEG o MP4) lo que lo necesita, como al importar. El contenido de WhatsApp va a
  `WhatsApp/`, como siempre.
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
  `ANADIDA`, `SUSTITUYE`, `YA_ESTA`, `REPETIDA`, `QUITADA_ANTES`, `ERROR`.
- La colección **solo se lee**, y no puede estar dentro de la biblioteca ni al revés.
  Los audios no se fusionan.

## El panel web

`python main.py panel` (o `panel.bat`) levanta un servidor en `http://127.0.0.1:8765/` (solo
accesible desde tu equipo; si el puerto está ocupado, prueba los siguientes) y abre el navegador.

- **Opciones**: salen del propio `argparse` de `main.py` (valores por defecto, listas, ayudas
  y validación), así que la web y la línea de comandos nunca se desincronizan. Una opción
  nueva de la CLI aparece sola en *Otras opciones* hasta que se le dé un sitio en
  `panel.html`. Debajo del formulario se ve el comando equivalente, para copiarlo.
- **Comprobación en vivo**: avisa antes de lanzar si la carpeta no existe, si el destino está
  dentro del origen o si un valor está fuera de rango, y dice qué biblioteca se usará y si ya
  existe (en ese caso solo se añade lo nuevo).
- **Ejecución**: cada ejecución es un `python main.py <comando> …` aparte, de una en una.
  Los módulos emiten eventos de progreso (`media_utils.progreso`, líneas `@@progreso {json}`)
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
  marcha; en Windows se envía Ctrl+Break, que `main.py` trata igual que Ctrl+C). Si no
  responde en 45 s, se fuerza el cierre.
- **Registro** completo en directo, con errores y avisos resaltados, filtro y descarga.
- **Preferencias**: las últimas opciones, carpetas recientes e historial de ejecuciones se
  guardan en `datos/panel.json`.
- **Seguridad**: igual que el servidor de la galería (solo `127.0.0.1`, cabeceras `Host` y
  `Origin` locales) y además exige JSON en los POST, así que ninguna web puede lanzar nada.

## Pruebas

```powershell
python -m unittest discover -s tests -t .
```

Los tests de vídeo simulan ffprobe y FFmpeg (también la GPU), y los de caras usan un motor
falso, así que no necesitan FFmpeg ni OpenCV instalados.

## Posibles ampliaciones

- Panel accesible desde el móvil en la red local (con contraseña).
- Editar etiquetas desde la galería y escribirlas en el XMP de la foto.
- Búsqueda por línea de comandos (`main.py buscar --etiqueta playa --copiar-a ...`).
- Mapa con las fotos geolocalizadas.
- Compartir la galería en la red local (con contraseña) para verla en el móvil o la tele.
