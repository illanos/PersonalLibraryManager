"""Clasificación del contenido: WhatsApp, pegatinas, capturas y fotos en movimiento.

El contenido de WhatsApp (fotos, vídeos, pegatinas, notas de voz) va **separado** del
resto de la biblioteca, en `WhatsApp/`, y la galería no lo mezcla con la línea de
tiempo: solo se ve eligiendo explícitamente la vista «WhatsApp».

    Biblioteca/2024/05-Mayo/...                 cámara y demás
    Biblioteca/WhatsApp/2024/05-Mayo/...        fotos y vídeos de WhatsApp
    Biblioteca/WhatsApp/Pegatinas/2024/05-Mayo  pegatinas (con --pegatinas-aparte)
    Biblioteca/WhatsApp/Audio/2024/05-Mayo      notas de voz y audios de WhatsApp
    Biblioteca/Audio/2024/05-Mayo               otros audios

Las capturas de pantalla se quedan en la línea de tiempo, con su etiqueta, y la
galería permite ocultarlas.

Los vídeos muy cortos son «fotos en movimiento»: sobre todo, los clips de las fotos con
movimiento del móvil. Es solo una clasificación de la galería, calculada de la duración:
ni cambian de carpeta ni de nombre.
"""

import re
from pathlib import Path, PurePath

from .media_utils import subcarpeta_fecha

CARPETA_WHATSAPP = "WhatsApp"
CARPETA_PEGATINAS = "Pegatinas"
CARPETA_AUDIO = "Audio"

# IMG-20240512-WA0001.jpg, VID-..., AUD-..., PTT-... (notas de voz), STK-... (pegatinas)
_RE_NOMBRE_WA = re.compile(r"^(IMG|VID|AUD|PTT|STK|DOC|GIF)-\d{8}-WA\d+", re.IGNORECASE)
_RE_PEGATINA = re.compile(r"^STK-", re.IGNORECASE)
RE_CAPTURA = re.compile(r"screen[ _-]?shot|screenrecord|captura|pantallazo", re.IGNORECASE)
LADO_MAX_PEGATINA = 512   # las pegatinas de WhatsApp son de 512x512
SEGUNDOS_MOVIMIENTO = 5   # un vídeo más corto es una «foto en movimiento»


def _carpetas(ruta: PurePath) -> list:
    return [p.lower() for p in ruta.parts[:-1]]


def es_whatsapp(ruta) -> bool:
    """Por el nombre (IMG-AAAAMMDD-WA0001) o por estar en una carpeta de WhatsApp."""
    ruta = PurePath(ruta)
    return bool(_RE_NOMBRE_WA.match(ruta.name)) or any("whatsapp" in c for c in _carpetas(ruta))


def es_pegatina(ruta, ancho: int = 0, alto: int = 0) -> bool:
    """STK-*.webp, o webp pequeño (≤ 512 px) dentro de WhatsApp / de una carpeta de pegatinas."""
    ruta = PurePath(ruta)
    if _RE_PEGATINA.match(ruta.name):
        return True
    if ruta.suffix.lower() != ".webp":
        return False
    en_carpeta = any("sticker" in c or "pegatina" in c for c in _carpetas(ruta))
    pequena = bool(ancho and alto and max(ancho, alto) <= LADO_MAX_PEGATINA)
    return en_carpeta or (pequena and es_whatsapp(ruta))


def es_captura(ruta) -> bool:
    ruta = PurePath(ruta)
    return bool(RE_CAPTURA.search(ruta.name)) or any(
        c in ("screenshots", "capturas", "capturas de pantalla") for c in _carpetas(ruta))


def es_foto_en_movimiento(tipo: str, duracion: float, whatsapp: bool = False) -> bool:
    """Vídeo de menos de SEGUNDOS_MOVIMIENTO. Sin duración conocida (0 o None) no se sabe y
    sigue siendo un vídeo; lo de WhatsApp va siempre aparte, por corto que sea."""
    return tipo == "video" and not whatsapp and 0 < (duracion or 0) < SEGUNDOS_MOVIMIENTO


def categoria(ruta, ancho: int = 0, alto: int = 0) -> str:
    """'pegatina' | 'whatsapp' | 'captura' | '' (contenido normal)."""
    if es_pegatina(ruta, ancho, alto):
        return "pegatina"
    if es_whatsapp(ruta):
        return "whatsapp"
    if es_captura(ruta):
        return "captura"
    return ""


def carpeta_destino(fecha, cat: str, tipo: str = "foto", pegatinas_aparte: bool = False) -> str:
    """Carpeta relativa dentro de la biblioteca (con '/')."""
    partes = []
    if cat in ("whatsapp", "pegatina"):
        partes.append(CARPETA_WHATSAPP)
        if cat == "pegatina" and pegatinas_aparte:
            partes.append(CARPETA_PEGATINAS)
    if tipo == "audio":
        partes.append(CARPETA_AUDIO)
    partes.append(subcarpeta_fecha(fecha))
    return "/".join(partes)


def en_carpeta_whatsapp(rel: str) -> bool:
    """¿Está ya dentro de WhatsApp/ en la biblioteca? (`rel` relativo, con '/')."""
    return rel.split("/", 1)[0] == CARPETA_WHATSAPP


def ambito(rel: str, origen: str = "") -> str:
    """'whatsapp' si el elemento de la galería es de WhatsApp (por su carpeta en la
    biblioteca o, en bibliotecas antiguas, por el archivo de origen); si no, ''."""
    if en_carpeta_whatsapp(rel):
        return "whatsapp"
    # Solo las últimas carpetas: la raíz del origen podría llamarse "WhatsApp..." sin serlo todo
    if origen and es_whatsapp(PurePath(*Path(origen).parts[-4:])):
        return "whatsapp"
    return "whatsapp" if _RE_NOMBRE_WA.match(PurePath(rel).name) else ""
