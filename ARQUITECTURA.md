# Exportador — Arquitectura y uso

## Qué es

Conjunto de herramientas en Python para **organizar, renombrar y optimizar** bibliotecas
personales de fotos y vídeos, más una **galería web local** para explorar el resultado.

## Estructura del proyecto

```
Exportador/
├── main.py           Punto de entrada (CLI con subcomandos)
├── media_utils.py    Utilidades compartidas (hash, nombres libres, carpetas, resumen)
├── fotos.py          Módulo de fotos (EXIF, redimensionado, JPEG optimizado)
├── videos.py         Módulo de vídeos (ffprobe, recodificación FFmpeg)
├── galeria.py        Galería web local (índice JSON, miniaturas, HTML+JS)
├── ARQUITECTURA.md   Este documento
└── .gitignore
```

## Módulos

| Módulo | Responsabilidad |
|---|---|
| `main.py` | CLI. Subcomandos `fotos`, `videos` y `galeria`. Valida rutas y dependencias. |
| `media_utils.py` | Código común: hash MD5 para duplicados, nombres sin colisión (`_01`, `_02`…), carpetas `Año/Mes`, listado de archivos y resumen final. |
| `fotos.py` | Lee la fecha desde EXIF (`DateTimeOriginal` → `DateTime` → mtime), corrige la orientación, reduce a máx. 2560 px y guarda en JPEG calidad 88. |
| `videos.py` | Lee fecha/dimensiones con `ffprobe`, recodifica con FFmpeg a H.264/MP4 o VP9/WebM con CRF, y conserva el original si la recompresión no reduce tamaño. |
| `galeria.py` | Escanea una carpeta ya organizada, genera miniaturas (Pillow para fotos, FFmpeg para vídeos) y crea `galeria.html` + `galeria.json`. |

## Decisiones de diseño

- **Fuente de la fecha**: metadatos primero (EXIF en fotos, `creation_time` en vídeos);
  si faltan, fecha de modificación del archivo. El nombre final es
  `AAAAMMDD_HHMMSS.ext`, con sufijos `_01`, `_02`… si hay colisión.
- **Duplicados**: hash MD5 del contenido. Dos archivos idénticos aunque cambie el nombre
  se detectan; solo queda una copia.
- **Originales aparte**: en fotos se copian a `originales/`; en vídeos se **mueven**
  (mover evita duplicar gigabytes). Nada se destruye sin copia.
- **Red de seguridad en vídeos**: si FFmpeg falla, el original se restaura; si el
  resultado pesa igual o más, se conserva el original tal cual.
- **Formatos**: fotos siempre JPEG (universal); vídeos H.264/MP4 por defecto
  (compatibilidad total) o VP9/WebM (`--codec vp9`, libre de patentes).
- **Calidad constante (CRF)** en vídeo, no bitrate fijo: escenas estáticas no desperdician
  espacio.

## Flujo de datos

```
Carpeta origen ──► main.py fotos/videos ──► Destino_organizados/
                                            ├── 2024/05-Mayo/*.jpg
                                            ├── 2024/06-Junio/*.mp4
                                            ├── originales/
                                            └── galeria.html + galeria.json + _galeria/thumbs
```

## Instalación

```powershell
# Python 3.10+ desde python.org (marcar "Add to PATH")
pip install Pillow
# FFmpeg para vídeos y miniaturas de vídeo:
winget install Gyan.FFmpeg
```

## Ejemplos de uso

```powershell
# 1. Previsualizar qué haría el organizador de fotos (no toca nada)
python main.py fotos "C:\Users\Tu\Pictures\MisFotos" --simular

# 2. Ejecutar de verdad (crea C:\...\MisFotos_organizados)
python main.py fotos "C:\Users\Tu\Pictures\MisFotos"

# 3. Previsualizar y luego comprimir vídeos a Full HD con H.264
python main.py videos "C:\Users\Tu\Videos" --simular
python main.py videos "C:\Users\Tu\Videos"

# 4. Vídeos en formato libre WebM (VP9), conservando hasta 1440p
python main.py videos "C:\Users\Tu\Videos" --codec vp9 --max-lado 2560

# 5. Generar la galería web y abrirla en el navegador
python main.py galeria "C:\Users\Tu\Pictures\MisFotos_organizados" --servir
python main.py galeria "C:\Users\Tu\Pictures\MisFotos_organizados" --servir --puerto 9000

# 5b. Solo generarla sin servidor (servirla después manualmente):
#     cd carpeta && python -m http.server 8080
python main.py galeria "C:\Users\Tu\Pictures\MisFotos_organizados"
```

### La galería web

`python main.py galeria <carpeta> --servir` levanta un servidor local
(`http://127.0.0.1:<puerto>/galeria.html`; solo accesible desde tu equipo) y abre el
navegador. La página es HTML+JavaScript puro, sin frameworks ni conexión a internet:

- **Buscador** por nombre de archivo, fecha o carpeta.
- **Filtros** Todas / Fotos / Vídeos.
- **Rejilla estilo mosaico** con miniaturas ligeras y carga diferida (*lazy loading*).
- **Visor a pantalla completa** con navegación por flechas del teclado o botones,
  reproducción de vídeo con controles nativos y cierre con `Esc`.

Importante: la galería debe verse **por HTTP** (con `--servir` o `http.server`); si se
abre el HTML con doble clic, el navegador bloquea el `fetch` del índice y las imágenes.

## Posibles ampliaciones

- Soporte HEIC instalando `pillow-heif`.
- Informe CSV de las operaciones realizadas.
- Regenerar la galería incrementalmente (detectar cambios por fecha de modificación).
