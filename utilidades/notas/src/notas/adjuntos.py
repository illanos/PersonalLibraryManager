"""Imágenes y notas de voz: identificar el archivo, guardarlo y sacar su miniatura.

El tipo se decide por el contenido (los primeros bytes), no por el nombre ni por lo que
diga el navegador: así nunca se guarda ni se sirve como imagen algo que no lo es (un HTML
o un SVG con código, por ejemplo). Los archivos se copian tal cual, sin recomprimir.

Pillow es opcional: con él se guardan las medidas de las imágenes y se hacen miniaturas
para que la página vaya ligera; sin él se enseña la imagen original.
"""

import os
import secrets
from datetime import datetime
from pathlib import Path

from .errores import AdjuntoNoValido

CARPETA_ADJUNTOS = "adjuntos"
CARPETA_MINIATURAS = ".miniaturas"
LADO_MINIATURA = 720
MAX_BYTES = 500 * 1024 * 1024
TAM_BLOQUE = 256 * 1024
BYTES_CABECERA = 64

IMAGEN, VOZ = "imagen", "voz"

_EXT_AUDIO = {".m4a", ".mp4a", ".m4b", ".aac", ".weba", ".webm", ".mp4", ".oga"}


def _marca_iso(cabecera: bytes) -> str:
    """Marca principal de un contenedor ISO (MP4, M4A, AVIF, HEIC), o "" si no lo es."""
    return cabecera[8:12].decode("latin-1").lower() if cabecera[4:8] == b"ftyp" else ""


def identificar(cabecera: bytes, nombre: str = "", mime: str = "") -> tuple:
    """(tipo, mime, extensión) según los primeros bytes; AdjuntoNoValido si no se admite.

    `nombre` y `mime` solo desempatan los contenedores que pueden llevar audio o vídeo
    (WebM y MP4): se aceptan como nota de voz si se presentan como audio.
    """
    c, ext, mime = cabecera, Path(nombre).suffix.lower(), (mime or "").split(";")[0].lower()
    if c.startswith(b"\xff\xd8\xff"):
        return IMAGEN, "image/jpeg", ".jpg"
    if c.startswith(b"\x89PNG\r\n\x1a\n"):
        return IMAGEN, "image/png", ".png"
    if c[:6] in (b"GIF87a", b"GIF89a"):
        return IMAGEN, "image/gif", ".gif"
    if c[:4] == b"RIFF" and c[8:12] == b"WEBP":
        return IMAGEN, "image/webp", ".webp"
    if c[:2] == b"BM" and c[6:10] == b"\0\0\0\0":
        return IMAGEN, "image/bmp", ".bmp"
    if c[:4] == b"RIFF" and c[8:12] == b"WAVE":
        return VOZ, "audio/wav", ".wav"
    if c[:4] == b"OggS":
        return VOZ, "audio/ogg", ".opus" if ext == ".opus" else ".ogg"
    if c[:4] == b"fLaC":
        return VOZ, "audio/flac", ".flac"
    if c[:3] == b"ID3":
        return VOZ, "audio/mpeg", ".mp3"
    if len(c) > 1 and c[0] == 0xFF and c[1] & 0xF6 == 0xF0:          # ADTS (capa 0)
        return VOZ, "audio/aac", ".aac"
    if len(c) > 1 and c[0] == 0xFF and c[1] & 0xE0 == 0xE0 and c[1] & 0x06:
        return VOZ, "audio/mpeg", ".mp3"

    marca = _marca_iso(c)
    if marca in ("avif", "avis"):
        return IMAGEN, "image/avif", ".avif"
    if marca in ("heic", "heix", "hevc", "heim", "heis", "mif1", "msf1"):
        raise AdjuntoNoValido("Las imágenes HEIC del iPhone no se ven en el navegador: "
                              "guárdala como JPEG y vuelve a añadirla")
    se_presenta_como_audio = mime.startswith("audio/") or (
        ext in _EXT_AUDIO and not mime.startswith("video/"))
    if marca.startswith("m4a") or marca.startswith("m4b") or (marca and se_presenta_como_audio):
        return VOZ, "audio/mp4", ".m4a"
    if c[:4] == b"\x1a\x45\xdf\xa3" and se_presenta_como_audio:      # WebM / Matroska
        return VOZ, "audio/webm", ".webm"
    raise AdjuntoNoValido(f"«{nombre or 'El archivo'}» no es una imagen ni un audio admitido "
                          "(JPG, PNG, GIF, WebP, AVIF, BMP; MP3, M4A, AAC, OGG, OPUS, WAV, "
                          "FLAC, WebM)")


def limpiar_nombre(nombre: str, defecto: str) -> str:
    """Nombre para enseñar y descargar: sin rutas ni caracteres de control, acotado."""
    nombre = (nombre or "").replace("\\", "/").split("/")[-1]
    nombre = "".join(c for c in nombre if c.isprintable() and c not in '<>:"|?*').strip(" .")
    if len(nombre) > 120:
        raiz, punto, ext = nombre.rpartition(".")
        nombre = (raiz[:110] + punto + ext[:9]) if punto and raiz else nombre[:120]
    return nombre or defecto


def guardar(carpeta: Path, flujo, nombre: str = "", mime: str = "", longitud: int = None,
            ahora: datetime = None) -> dict:
    """Copia `flujo` en `carpeta`/adjuntos/AAAA/MM/ y devuelve los datos del adjunto.

    Escribe primero un `.part` y lo renombra al final: si algo falla a medias no queda un
    adjunto incompleto. Con `longitud` lee exactamente esos bytes (cuerpo de una petición).
    """
    ahora = ahora or datetime.now()
    pendiente = longitud
    if longitud is not None and longitud > MAX_BYTES:
        raise AdjuntoNoValido(f"El archivo pesa más de {MAX_BYTES // 1024 // 1024} MB")

    def leer(n):
        nonlocal pendiente
        if pendiente is None:
            return flujo.read(n)
        datos = flujo.read(min(n, pendiente))
        pendiente -= len(datos)
        return datos

    cabecera = leer(BYTES_CABECERA)
    if not cabecera:
        raise AdjuntoNoValido("El archivo está vacío")
    tipo, mime_real, ext = identificar(cabecera, nombre, mime)

    relativa = (f"{CARPETA_ADJUNTOS}/{ahora:%Y}/{ahora:%m}/"
                f"{ahora:%Y%m%d_%H%M%S}_{secrets.token_hex(4)}{ext}")
    final = carpeta / relativa
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(final.name + ".part")
    total = 0
    try:
        with open(tmp, "wb") as f:
            bloque = cabecera
            while bloque:
                total += len(bloque)
                if total > MAX_BYTES:
                    raise AdjuntoNoValido(f"El archivo pesa más de {MAX_BYTES // 1024 // 1024} MB")
                f.write(bloque)
                bloque = leer(TAM_BLOQUE)
        if pendiente:
            raise AdjuntoNoValido("El archivo ha llegado incompleto: vuelve a intentarlo")
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    defecto = f"{'Imagen' if tipo == IMAGEN else 'Nota de voz'} {ahora:%Y-%m-%d %H.%M.%S}{ext}"
    ancho, alto = medidas(final) if tipo == IMAGEN else (None, None)
    return {"tipo": tipo, "archivo": relativa, "nombre": limpiar_nombre(nombre, defecto),
            "mime": mime_real, "bytes": total, "ancho": ancho, "alto": alto}


def ruta_segura(carpeta: Path, relativa: str) -> Path:
    """Ruta absoluta de un adjunto, comprobando que no se sale de la carpeta de adjuntos."""
    raiz = (carpeta / CARPETA_ADJUNTOS).resolve()
    ruta = (carpeta / relativa).resolve()
    if raiz not in ruta.parents:
        raise AdjuntoNoValido("Ruta de adjunto no válida")
    return ruta


def medidas(ruta: Path) -> tuple:
    """(ancho, alto) ya girada según su EXIF, o (None, None) sin Pillow o si no se puede leer."""
    try:
        from PIL import Image
        with Image.open(ruta) as im:
            ancho, alto = im.size
            if im.getexif().get(274) in (5, 6, 7, 8):
                ancho, alto = alto, ancho
            return ancho, alto
    except Exception:            # sin Pillow, formato que no conoce, archivo dañado…
        return None, None


def miniatura(carpeta: Path, relativa: str):
    """Ruta de la miniatura WebP (se crea la primera vez) o None si no se puede o no hace falta."""
    original = ruta_segura(carpeta, relativa)
    destino = carpeta / CARPETA_ADJUNTOS / CARPETA_MINIATURAS / (original.stem + ".webp")
    if destino.is_file():
        return destino
    try:
        from PIL import Image, ImageOps
        with Image.open(original) as im:
            if getattr(im, "is_animated", False) or max(im.size) <= LADO_MINIATURA:
                return None
            im = ImageOps.exif_transpose(im)
            im.thumbnail((LADO_MINIATURA, LADO_MINIATURA))
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "transparency" in im.info or "A" in im.mode else "RGB")
            destino.parent.mkdir(parents=True, exist_ok=True)
            # Nombre propio por hilo: dos pestañas pueden pedir la misma miniatura a la vez
            tmp = destino.with_name(f"{destino.name}.{secrets.token_hex(3)}.part")
            try:
                im.save(tmp, "WEBP", quality=82)
                os.replace(tmp, destino)
            finally:
                tmp.unlink(missing_ok=True)
        return destino
    except Exception:
        return destino if destino.is_file() else None


def borrar_archivos(carpeta: Path, relativas):
    """Borra de verdad los archivos de adjuntos ya eliminados de la base de datos."""
    for relativa in relativas:
        try:
            ruta = ruta_segura(carpeta, relativa)
            ruta.unlink(missing_ok=True)
            mini = carpeta / CARPETA_ADJUNTOS / CARPETA_MINIATURAS / (ruta.stem + ".webp")
            mini.unlink(missing_ok=True)
        except (OSError, AdjuntoNoValido):
            pass         # un archivo suelto no es grave: ya no pertenece a ninguna nota
