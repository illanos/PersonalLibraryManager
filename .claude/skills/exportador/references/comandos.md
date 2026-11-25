# Comandos y opciones

Generado de `exportador.cli.construir_parser()` con `scripts/opciones.py` (no editar a mano: regenerar con `--escribir` si cambia la CLI). Con el paquete instalado, `exportador` equivale a `python -m exportador`. `-h` en cualquier comando muestra lo mismo.

Opciones ocultas por compatibilidad (no las propongas): `--sin-originales` (ya es lo normal) y, en `videos`, `--max-lado` (= `--max-lado-video`).

## `fotos`

Organizar y optimizar fotos

`python -m exportador fotos <origen>`

| Opción | Por defecto | Qué hace |
|---|---|---|
| `<origen>` | — | Carpeta con los archivos a importar |
| `--destino` CARPETA | — | Biblioteca destino (por defecto: <origen>_organizados) |
| `--simular` | no | Muestra qué haría sin crear, mover ni modificar nada |
| `--con-originales` | no | Guardar además una copia intacta de cada original en originales/ (el origen nunca se toca) |
| `--renombrar-aproximadas` | no | Renombrar también lo YA importado con nombre AAAAMMDD_000000 (fecha sacada del nombre sin hora); solo dentro de la biblioteca |
| `--max-lado` N | `3200` | Lado largo máximo de las fotos en px (0 = no reducir; por defecto 3200) |
| `--calidad` N | `88` | Calidad de compresión 1-100 (por defecto 88) |
| `--formato` jpeg\|webp | `jpeg` | jpeg = universal \| webp = ~30 % menos peso (por defecto jpeg) |
| `--hilos` N | `0` | Fotos en paralelo (por defecto: según los núcleos del equipo) |
| `--omitir-parecidas` | no | No importar la peor copia de cada grupo de fotos casi idénticas (p. ej. WhatsApp Sent/ e Images/). Nada se borra del origen |
| `--pegatinas-aparte` | no | Pegatinas de WhatsApp en WhatsApp/Pegatinas/ en vez de con el resto de WhatsApp (que ya va siempre separado, en WhatsApp/) |

## `videos`

Organizar y comprimir vídeos

`python -m exportador videos <origen>`

| Opción | Por defecto | Qué hace |
|---|---|---|
| `<origen>` | — | Carpeta con los archivos a importar |
| `--destino` CARPETA | — | Biblioteca destino (por defecto: <origen>_organizados) |
| `--simular` | no | Muestra qué haría sin crear, mover ni modificar nada |
| `--con-originales` | no | Guardar además una copia intacta de cada original en originales/ (el origen nunca se toca) |
| `--renombrar-aproximadas` | no | Renombrar también lo YA importado con nombre AAAAMMDD_000000 (fecha sacada del nombre sin hora); solo dentro de la biblioteca |
| `--codec` h264\|h265\|vp9 | `h264` | h264 = MP4 universal \| h265 = MP4 más ligero \| vp9 = WebM libre |
| `--max-lado-video` N | `1920` | Lado largo máximo de los vídeos en px (0 = mantener; por defecto 1920) |
| `--crf` N | — | Calidad constante (menor = mejor; por defecto 23 h264, 28 h265, 32 vp9) |
| `--preset` ultrafast\|superfast\|veryfast\|faster\|fast\|medium\|slow\|slower\|veryslow | `medium` | Velocidad de codificación h264/h265 (más lento = archivos menores) |
| `--hilos-video` N | `1` | Vídeos codificándose a la vez (por defecto 1; 2-3 si sobra CPU/GPU) |
| `--hw` auto\|nvenc\|qsv\|amf\|no | `no` | Codificación por hardware: auto = la que ofrezca el FFmpeg instalado (NVIDIA nvenc, Intel qsv, AMD amf); si falla, se repite por software. Por defecto no (software, archivos algo menores) |

## `audio`

Organizar notas de voz y audios (.opus .mp3 .m4a .aac .ogg .wav), copiados sin recomprimir

`python -m exportador audio <origen>`

| Opción | Por defecto | Qué hace |
|---|---|---|
| `<origen>` | — | Carpeta con los archivos a importar |
| `--destino` CARPETA | — | Biblioteca destino (por defecto: <origen>_organizados) |
| `--simular` | no | Muestra qué haría sin crear, mover ni modificar nada |
| `--con-originales` | no | Guardar además una copia intacta de cada original en originales/ (el origen nunca se toca) |
| `--renombrar-aproximadas` | no | Renombrar también lo YA importado con nombre AAAAMMDD_000000 (fecha sacada del nombre sin hora); solo dentro de la biblioteca |

## `todo`

Fotos + vídeos + audio + galería en un solo paso

`python -m exportador todo <origen>`

| Opción | Por defecto | Qué hace |
|---|---|---|
| `<origen>` | — | Carpeta con los archivos a importar |
| `--destino` CARPETA | — | Biblioteca destino (por defecto: <origen>_organizados) |
| `--simular` | no | Muestra qué haría sin crear, mover ni modificar nada |
| `--con-originales` | no | Guardar además una copia intacta de cada original en originales/ (el origen nunca se toca) |
| `--renombrar-aproximadas` | no | Renombrar también lo YA importado con nombre AAAAMMDD_000000 (fecha sacada del nombre sin hora); solo dentro de la biblioteca |
| `--max-lado` N | `3200` | Lado largo máximo de las fotos en px (0 = no reducir; por defecto 3200) |
| `--calidad` N | `88` | Calidad de compresión 1-100 (por defecto 88) |
| `--formato` jpeg\|webp | `jpeg` | jpeg = universal \| webp = ~30 % menos peso (por defecto jpeg) |
| `--hilos` N | `0` | Fotos en paralelo (por defecto: según los núcleos del equipo) |
| `--omitir-parecidas` | no | No importar la peor copia de cada grupo de fotos casi idénticas (p. ej. WhatsApp Sent/ e Images/). Nada se borra del origen |
| `--pegatinas-aparte` | no | Pegatinas de WhatsApp en WhatsApp/Pegatinas/ en vez de con el resto de WhatsApp (que ya va siempre separado, en WhatsApp/) |
| `--codec` h264\|h265\|vp9 | `h264` | h264 = MP4 universal \| h265 = MP4 más ligero \| vp9 = WebM libre |
| `--max-lado-video` N | `1920` | Lado largo máximo de los vídeos en px (0 = mantener; por defecto 1920) |
| `--crf` N | — | Calidad constante (menor = mejor; por defecto 23 h264, 28 h265, 32 vp9) |
| `--preset` ultrafast\|superfast\|veryfast\|faster\|fast\|medium\|slow\|slower\|veryslow | `medium` | Velocidad de codificación h264/h265 (más lento = archivos menores) |
| `--hilos-video` N | `1` | Vídeos codificándose a la vez (por defecto 1; 2-3 si sobra CPU/GPU) |
| `--hw` auto\|nvenc\|qsv\|amf\|no | `no` | Codificación por hardware: auto = la que ofrezca el FFmpeg instalado (NVIDIA nvenc, Intel qsv, AMD amf); si falla, se repite por software. Por defecto no (software, archivos algo menores) |
| `--servir` | no | Levanta un servidor local y abre el navegador |
| `--puerto` N | `8080` | Puerto del servidor local (por defecto 8080; si está ocupado, el siguiente) |
| `--sin-navegador` | no | Con --servir, no abrir el navegador automáticamente |
| `--caras` | no | Detectar y agrupar caras para nombrarlas en la galería (local; requiere pip install opencv-python). Solo analiza lo nuevo |
| `--descargar-lugares` | no | Descargar una vez las ciudades de GeoNames (~3 MB) para mostrar el lugar de las fotos con GPS sin conexión |
| `--descargar-modelos-caras` | no | Descargar una vez los modelos YuNet/SFace de OpenCV Zoo (~38 MB) para agrupar bien las caras |
| `--sin-audio` | no | No importar notas de voz ni audios |
| `--sin-galeria` | no | No generar la galería al terminar |

## `google`

Importar un Takeout de Google Fotos (fotos + vídeos + galería) grabando en cada archivo los metadatos de su JSON

Como 'todo', para la carpeta 'Google Fotos' de un Takeout. Cada foto y vídeo recibe lo que dice su JSON y no trae dentro (fecha, GPS), además de descripción, personas y álbumes (como etiquetas). Los JSON no se copian. Las copias '-editada' se omiten si está su original, y el clip de cada foto con movimiento (.MP) se importa como vídeo con su mismo nombre. El origen solo se lee.

`python -m exportador google <origen>`

| Opción | Por defecto | Qué hace |
|---|---|---|
| `<origen>` | — | Carpeta con los archivos a importar |
| `--destino` CARPETA | — | Biblioteca destino (por defecto: <origen>_organizados) |
| `--simular` | no | Muestra qué haría sin crear, mover ni modificar nada |
| `--con-originales` | no | Guardar además una copia intacta de cada original en originales/ (el origen nunca se toca) |
| `--renombrar-aproximadas` | no | Renombrar también lo YA importado con nombre AAAAMMDD_000000 (fecha sacada del nombre sin hora); solo dentro de la biblioteca |
| `--max-lado` N | `3200` | Lado largo máximo de las fotos en px (0 = no reducir; por defecto 3200) |
| `--calidad` N | `88` | Calidad de compresión 1-100 (por defecto 88) |
| `--formato` jpeg\|webp | `jpeg` | jpeg = universal \| webp = ~30 % menos peso (por defecto jpeg) |
| `--hilos` N | `0` | Fotos en paralelo (por defecto: según los núcleos del equipo) |
| `--omitir-parecidas` | no | No importar la peor copia de cada grupo de fotos casi idénticas (p. ej. WhatsApp Sent/ e Images/). Nada se borra del origen |
| `--pegatinas-aparte` | no | Pegatinas de WhatsApp en WhatsApp/Pegatinas/ en vez de con el resto de WhatsApp (que ya va siempre separado, en WhatsApp/) |
| `--codec` h264\|h265\|vp9 | `h264` | h264 = MP4 universal \| h265 = MP4 más ligero \| vp9 = WebM libre |
| `--max-lado-video` N | `1920` | Lado largo máximo de los vídeos en px (0 = mantener; por defecto 1920) |
| `--crf` N | — | Calidad constante (menor = mejor; por defecto 23 h264, 28 h265, 32 vp9) |
| `--preset` ultrafast\|superfast\|veryfast\|faster\|fast\|medium\|slow\|slower\|veryslow | `medium` | Velocidad de codificación h264/h265 (más lento = archivos menores) |
| `--hilos-video` N | `1` | Vídeos codificándose a la vez (por defecto 1; 2-3 si sobra CPU/GPU) |
| `--hw` auto\|nvenc\|qsv\|amf\|no | `no` | Codificación por hardware: auto = la que ofrezca el FFmpeg instalado (NVIDIA nvenc, Intel qsv, AMD amf); si falla, se repite por software. Por defecto no (software, archivos algo menores) |
| `--servir` | no | Levanta un servidor local y abre el navegador |
| `--puerto` N | `8080` | Puerto del servidor local (por defecto 8080; si está ocupado, el siguiente) |
| `--sin-navegador` | no | Con --servir, no abrir el navegador automáticamente |
| `--caras` | no | Detectar y agrupar caras para nombrarlas en la galería (local; requiere pip install opencv-python). Solo analiza lo nuevo |
| `--descargar-lugares` | no | Descargar una vez las ciudades de GeoNames (~3 MB) para mostrar el lugar de las fotos con GPS sin conexión |
| `--descargar-modelos-caras` | no | Descargar una vez los modelos YuNet/SFace de OpenCV Zoo (~38 MB) para agrupar bien las caras |
| `--sin-galeria` | no | No generar la galería al terminar |

## `reorganizar`

Ordenar una biblioteca ya importada (solo dentro de ella)

Mueve o renombra archivos ya importados, solo dentro de la biblioteca, y actualiza catálogo, galería y favoritos. El origen no se toca.

`python -m exportador reorganizar <biblioteca>`

| Opción | Por defecto | Qué hace |
|---|---|---|
| `<biblioteca>` | — | Biblioteca ya organizada |
| `--whatsapp` | no | Separar en WhatsApp/ lo de WhatsApp importado mezclado con el resto |
| `--fechas-aproximadas` | no | Renombrar AAAAMMDD_000000 (fecha del nombre sin hora) con la hora del archivo si es del mismo día, o como AAAAMMDD_WA0011 |
| `--pegatinas-aparte` | no | Con --whatsapp, las pegatinas a WhatsApp/Pegatinas/ |
| `--simular` | no | Muestra qué movería sin tocar nada |

## `fusionar`

Añadir a una biblioteca otra colección sin repetir fotos ni vídeos

Añade a una biblioteca las fotos y vídeos de otra colección (otra biblioteca del exportador o cualquier carpeta). Compara por días: lo que ya está no se añade y, de dos copias iguales, se queda la de más calidad; la peor va a la papelera de la biblioteca (restaurable). La colección solo se lee.

`python -m exportador fusionar <coleccion>`

| Opción | Por defecto | Qué hace |
|---|---|---|
| `<coleccion>` | — | Colección a añadir (solo se lee) |
| `--destino` CARPETA *(obligatoria)* | — | Biblioteca a la que se añade (debe existir) |
| `--simular` | no | Muestra qué haría sin tocar nada (el informe CSV va a la carpeta temporal del sistema) |
| `--umbral` N | `5` | Bits de diferencia (0-12, de 128) para considerar dos fotos la misma (por defecto 5: copias recomprimidas o reducidas). Más = más agresivo |
| `--margen-dias` N | `1` | Días antes y después con los que se compara cada foto o vídeo (por defecto 1, por medianoche y zonas horarias; 0 = el mismo día) |
| `--max-lado` N | `3200` | Límite de la exportación en fotos: las más grandes se exportan reducidas al añadirlas, como al importar, y se comparan ya reducidas (0 = copiarlas siempre tal cual; por defecto 3200) |
| `--max-lado-video` N | `1920` | Límite de la exportación en vídeos: los más grandes se recodifican al añadirlos, como al importar (0 = tal cual; por defecto 1920) |
| `--calidad` N | `88` | Calidad al reducir o convertir una foto (por defecto 88) |
| `--hilos` N | `0` | Archivos en paralelo (por defecto: según los núcleos del equipo) |
| `--sin-metadatos` | no | No completar la copia que se queda con los metadatos de las otras copias iguales (fecha, GPS, cámara, etiquetas, personas...); por defecto se completan, sin recomprimir |
| `--sin-sustituir` | no | No cambiar nada de lo que ya está en la biblioteca: aunque la copia de la colección sea mejor, se queda la de la biblioteca (que sí gana sus metadatos, salvo con --sin-metadatos) |
| `--omitir-parecidas` | no | No añadir las fotos parecidas a una de la biblioteca sin llegar a ser iguales (otras tomas de una ráfaga, editadas, recortes...: hasta 12 bits, como «Parecidas» en la galería); el informe las lista |
| `--sin-galeria` | no | No actualizar la galería de la biblioteca al terminar |

## `galeria`

Generar (y servir) la galería web local

`python -m exportador galeria <carpeta>`

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--servir` | no | Levanta un servidor local y abre el navegador |
| `--puerto` N | `8080` | Puerto del servidor local (por defecto 8080; si está ocupado, el siguiente) |
| `--sin-navegador` | no | Con --servir, no abrir el navegador automáticamente |
| `--caras` | no | Detectar y agrupar caras para nombrarlas en la galería (local; requiere pip install opencv-python). Solo analiza lo nuevo |
| `--descargar-lugares` | no | Descargar una vez las ciudades de GeoNames (~3 MB) para mostrar el lugar de las fotos con GPS sin conexión |
| `--descargar-modelos-caras` | no | Descargar una vez los modelos YuNet/SFace de OpenCV Zoo (~38 MB) para agrupar bien las caras |
| `<carpeta>` | — | Biblioteca ya organizada |
| `--regenerar` | no | Rehacer metadatos y miniaturas aunque no hayan cambiado |

## `panel`

Panel web local para elegir opciones, lanzar y ver el progreso

Abre en el navegador un panel para configurar y lanzar importaciones, galerías, reorganizaciones y fusiones, con su progreso en directo.

`python -m exportador panel`

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--puerto` N | `8765` | Puerto del panel (por defecto 8765; si está ocupado, el siguiente) |
| `--sin-navegador` | no | No abrir el navegador automáticamente |
