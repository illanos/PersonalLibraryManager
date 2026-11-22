"""Metadatos de fotos: lectura (para buscar y filtrar) y conservación al exportar.

Al exportar una foto se conservan:
  - EXIF completo: fecha, cámara, objetivo, exposición, GPS y las etiquetas,
    título y comentarios que escribe el Explorador de Windows (XPKeywords...).
  - XMP: etiquetas/palabras clave, valoración, título, descripción y personas
    (Lightroom, digiKam, Windows Fotos, Google, Apple...).
  - IPTC: palabras clave, pie de foto, autor (solo si la salida es JPEG; WebP no lo admite).
  - Perfil de color ICC y comentario JPEG.
La rotación se aplica a los píxeles y la orientación queda como "normal" en EXIF y XMP.

Lo único que se descarta es lo que deja de tener sentido tras recomprimir:
la miniatura EXIF interna y los mapas de profundidad/ganancia HDR (MPF).
"""

import math
import re
import struct
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from PIL import Image, IptcImagePlugin

from media_utils import fecha_desde_nombre, fecha_mtime, fecha_plausible

# --- Etiquetas EXIF ---
IFD_EXIF, IFD_GPS = 0x8769, 0x8825
TAG_DESCRIPCION, TAG_MARCA, TAG_MODELO, TAG_ORIENTACION = 270, 271, 272, 274
TAG_FECHA, TAG_AUTOR, TAG_VALORACION = 306, 315, 18246
TAG_XP_TITULO, TAG_XP_COMENTARIO, TAG_XP_AUTOR, TAG_XP_ETIQUETAS = 0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E
TAG_EXPOSICION, TAG_APERTURA, TAG_ISO = 33434, 33437, 34855
TAG_FECHA_ORIGINAL, TAG_FECHA_DIGITALIZADA = 36867, 36868
TAG_FOCAL, TAG_COMENTARIO_USUARIO, TAG_FOCAL_35MM, TAG_OBJETIVO = 37386, 37510, 41989, 42036

# Descripciones "basura" que algunas cámaras escriben por defecto
DESCRIPCIONES_VACIAS = {"olympus digital camera", "sony dsc", "digital camera", "default",
                        "exif_jpeg_picture", "image", "samsung", "lg", "huawei",
                        "camera", "picture", "photo", "<no description>"}

# --- XMP ---
NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "lr": "http://ns.adobe.com/lightroom/1.0/",
    "mwg-rs": "http://www.metadataworkinggroup.com/schemas/regions/",
    "MPReg": "http://ns.microsoft.com/photo/1.2/t/Region#",
    "Iptc4xmpExt": "http://iptc.org/std/Iptc4xmpExt/2008-02-29/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
CABECERA_XMP_JPEG = b"http://ns.adobe.com/xap/1.0/\x00"
MAX_XMP_JPEG = 65533 - len(CABECERA_XMP_JPEG)   # un único segmento APP1


def _q(prefijo: str, nombre: str) -> str:
    return f"{{{NS[prefijo]}}}{nombre}"


# ============================= Lectura =============================

def _texto(valor) -> str:
    if isinstance(valor, bytes):
        for codificacion in ("utf-8", "cp1252"):
            try:
                valor = valor.decode(codificacion)
                break
            except UnicodeDecodeError:
                continue
        else:
            return ""
    return str(valor or "").strip("\x00 \t\r\n").strip()


def _unicos(valores) -> list:
    """Sin vacíos ni repetidos (sin distinguir mayúsculas), en el orden original."""
    vistos, resultado = set(), []
    for valor in valores:
        valor = _texto(valor)
        if valor and valor.lower() not in vistos:
            vistos.add(valor.lower())
            resultado.append(valor)
    return resultado


def _numero(valor):
    try:
        if isinstance(valor, (tuple, list)):
            valor = valor[0]
        numero = float(valor)
    except (TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    return numero if math.isfinite(numero) and numero > 0 else None


# --- EXIF ---

def _parsear_fecha_exif(valor):
    texto = _texto(valor)[:19]
    for formato in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            fecha = datetime.strptime(texto, formato)
        except ValueError:
            continue
        return fecha if fecha_plausible(fecha) else None
    return None


def fecha_exif(exif):
    """DateTimeOriginal > DateTimeDigitized > DateTime.

    Las dos primeras están en el sub-IFD Exif, no en el principal: hay que pedirlas
    con get_ifd(); `exif.get(36867)` a secas devuelve None en casi todas las fotos.
    """
    sub = exif.get_ifd(IFD_EXIF)
    for valor in (sub.get(TAG_FECHA_ORIGINAL), sub.get(TAG_FECHA_DIGITALIZADA),
                  exif.get(TAG_FECHA_ORIGINAL), exif.get(TAG_FECHA)):
        fecha = _parsear_fecha_exif(valor)
        if fecha:
            return fecha
    return None


def _a_grados(valor) -> float:
    grados, minutos, segundos = (float(x) for x in valor)
    return grados + minutos / 60 + segundos / 3600


def gps_exif(exif):
    """[lat, lon] en grados decimales, o None."""
    gps = exif.get_ifd(IFD_GPS)
    if not gps:
        return None
    try:
        lat = _a_grados(gps[2]) * (-1 if str(gps.get(1, "N")).upper().startswith("S") else 1)
        lon = _a_grados(gps[4]) * (-1 if str(gps.get(3, "E")).upper().startswith("W") else 1)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)) or (lat == 0 and lon == 0):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return [round(lat, 6), round(lon, 6)]


def camara_exif(exif) -> str:
    marca, modelo = _texto(exif.get(TAG_MARCA)), _texto(exif.get(TAG_MODELO))
    if marca and modelo.lower().startswith(marca.split()[0].lower()):
        return modelo   # "Canon" + "Canon EOS 5D" -> "Canon EOS 5D"
    return f"{marca} {modelo}".strip()


def _xp(exif, tag) -> str:
    """Campos XP* de Windows: UTF-16LE guardado como bytes."""
    valor = exif.get(tag)
    if valor is None:
        return ""
    if isinstance(valor, str):
        return _texto(valor)
    try:
        return bytes(valor).decode("utf-16-le", "replace").strip("\x00 ").strip()
    except (TypeError, ValueError):
        return ""


def _comentario_usuario(valor) -> str:
    """UserComment: 8 bytes indican la codificación y luego va el texto."""
    if isinstance(valor, str):
        return _texto(valor)
    if not isinstance(valor, bytes) or len(valor) <= 8:
        return ""
    cabecera, cuerpo = valor[:8], valor[8:]
    if cabecera.startswith(b"UNICODE"):
        codificacion = "utf-16-be" if cuerpo[:1] == b"\x00" else "utf-16-le"
        return cuerpo.decode(codificacion, "replace").strip("\x00 ").strip()
    if cabecera.startswith(b"ASCII"):
        return _texto(cuerpo)
    return ""


def _descripcion_util(texto: str) -> str:
    return "" if texto.lower() in DESCRIPCIONES_VACIAS else texto


def exposicion_exif(exif) -> str:
    """Ej.: '1/120 s · f/1.8 · ISO 100 · 26 mm'."""
    sub = exif.get_ifd(IFD_EXIF)
    partes = []
    tiempo = _numero(sub.get(TAG_EXPOSICION))
    if tiempo:
        partes.append(f"{tiempo:g} s" if tiempo >= 0.5 else f"1/{round(1 / tiempo)} s")
    apertura = _numero(sub.get(TAG_APERTURA))
    if apertura:
        partes.append(f"f/{apertura:.1f}".replace(".0", ""))
    iso = _numero(sub.get(TAG_ISO))
    if iso:
        partes.append(f"ISO {iso:.0f}")
    focal = _numero(sub.get(TAG_FOCAL_35MM)) or _numero(sub.get(TAG_FOCAL))
    if focal:
        partes.append(f"{focal:.0f} mm")
    return " · ".join(partes)


# --- XMP ---

def xmp_de(im):
    """Paquete XMP de la imagen (bytes) o None. JPEG/WebP/HEIF usan 'xmp'; PNG otra clave."""
    for clave in ("xmp", "XML:com.adobe.xmp"):
        valor = im.info.get(clave)
        if valor:
            return valor.encode("utf-8") if isinstance(valor, str) else bytes(valor)
    return None


def leer_xmp(xmp) -> dict:
    datos = {"etiquetas": [], "personas": [], "titulo": "", "descripcion": "", "valoracion": 0}
    if not xmp:
        return datos
    texto = xmp.decode("utf-8", "replace") if isinstance(xmp, bytes) else xmp
    if "<!DOCTYPE" in texto or "<!ENTITY" in texto:   # nada de entidades XML
        return datos
    for apertura, cierre in (("<x:xmpmeta", "</x:xmpmeta>"), ("<rdf:RDF", "</rdf:RDF>")):
        inicio, fin = texto.find(apertura), texto.rfind(cierre)
        if inicio >= 0 and fin > inicio:
            texto = texto[inicio:fin + len(cierre)]
            break
    try:
        raiz = ET.fromstring(texto)
    except ET.ParseError:
        return datos

    li = _q("rdf", "li")

    def lista(elemento):
        return [x.text for x in elemento.iter(li) if x.text and x.text.strip()]

    def alternativa(elemento):
        opciones = [x for x in elemento.iter(li) if x.text and x.text.strip()]
        preferida = next((x for x in opciones if x.get(XML_LANG) == "x-default"), None)
        return (preferida or (opciones[0] if opciones else elemento)).text or ""

    def valoracion(valor):
        try:
            return max(0, min(5, int(float(valor))))
        except (TypeError, ValueError):
            return 0

    nombres_persona = {_q("mwg-rs", "Name"), _q("MPReg", "PersonDisplayName")}
    for elemento in raiz.iter():
        etiqueta = elemento.tag
        if etiqueta == _q("dc", "subject"):
            datos["etiquetas"] += lista(elemento)
        elif etiqueta == _q("lr", "hierarchicalSubject"):
            # "Lugares|España|Cádiz" -> "Cádiz"
            datos["etiquetas"] += [h.split("|")[-1] for h in lista(elemento)]
        elif etiqueta == _q("dc", "title"):
            datos["titulo"] = datos["titulo"] or alternativa(elemento)
        elif etiqueta == _q("dc", "description"):
            datos["descripcion"] = datos["descripcion"] or alternativa(elemento)
        elif etiqueta == _q("xmp", "Rating"):
            datos["valoracion"] = valoracion(elemento.text)
        elif etiqueta in nombres_persona and elemento.text:
            datos["personas"].append(elemento.text)
        elif etiqueta == _q("Iptc4xmpExt", "PersonInImage"):
            datos["personas"] += lista(elemento)
        for atributo, valor in elemento.attrib.items():
            if atributo == _q("xmp", "Rating"):
                datos["valoracion"] = valoracion(valor)
            elif atributo in nombres_persona:
                datos["personas"].append(valor)
    return datos


# --- IPTC ---

def leer_iptc(im) -> dict:
    try:
        info = IptcImagePlugin.getiptcinfo(im) or {}
    except Exception:
        return {}

    def valores(clave):
        valor = info.get(clave)
        if valor is None:
            return []
        return valor if isinstance(valor, list) else [valor]

    def primero(clave):
        return next((_texto(v) for v in valores(clave) if _texto(v)), "")

    return {"etiquetas": valores((2, 25)), "titulo": primero((2, 5)),
            "descripcion": primero((2, 120)), "autor": primero((2, 80))}


# --- Todo junto ---

def leer_metadatos(ruta: Path, completo: bool = True) -> dict:
    """Metadatos de una foto. Lanza excepción si no se puede abrir como imagen.

    Siempre: fecha (y su fuente: exif | nombre | archivo), ancho, alto (ya
    orientados) y animado. Con `completo`, además: camara, objetivo, exposicion,
    gps, etiquetas, personas, titulo, descripcion, autor y valoracion (0-5).
    """
    with Image.open(ruta) as im:
        exif = im.getexif()
        ancho, alto = im.size
        if exif.get(TAG_ORIENTACION) in (5, 6, 7, 8):
            ancho, alto = alto, ancho
        datos = {"fecha": fecha_exif(exif), "fuente": "exif", "ancho": ancho, "alto": alto,
                 "animado": bool(getattr(im, "is_animated", False))}
        if completo:
            sub = exif.get_ifd(IFD_EXIF)
            xmp, iptc = leer_xmp(xmp_de(im)), leer_iptc(im)
            datos.update(
                camara=camara_exif(exif),
                objetivo=_texto(sub.get(TAG_OBJETIVO)),
                exposicion=exposicion_exif(exif),
                gps=gps_exif(exif),
                etiquetas=_unicos(xmp["etiquetas"] + iptc.get("etiquetas", [])
                                  + _xp(exif, TAG_XP_ETIQUETAS).split(";")),
                personas=_unicos(xmp["personas"]),
                titulo=next(filter(None, (_texto(xmp["titulo"]), iptc.get("titulo"),
                                          _xp(exif, TAG_XP_TITULO))), ""),
                descripcion=next(filter(None, (
                    _texto(xmp["descripcion"]), iptc.get("descripcion"),
                    _descripcion_util(_texto(exif.get(TAG_DESCRIPCION))),
                    _xp(exif, TAG_XP_COMENTARIO),
                    _comentario_usuario(sub.get(TAG_COMENTARIO_USUARIO)))), ""),
                autor=next(filter(None, (iptc.get("autor"), _texto(exif.get(TAG_AUTOR)),
                                         _xp(exif, TAG_XP_AUTOR))), ""),
                valoracion=xmp["valoracion"] or max(0, min(5, int(_numero(
                    exif.get(TAG_VALORACION)) or 0))),
            )
    if datos["fecha"] is None:
        datos["fecha"], datos["fuente"] = fecha_desde_nombre(ruta.stem), "nombre"
    if datos["fecha"] is None:
        datos["fecha"], datos["fuente"] = fecha_mtime(ruta), "archivo"
    return datos


# ============================= Conservación =============================

_RE_ORIENTACION_XMP = (
    (re.compile(r'(tiff:Orientation\s*=\s*["\'])\d(["\'])'), r"\g<1>1\g<2>"),
    (re.compile(r"(<tiff:Orientation>)\s*\d\s*(</tiff:Orientation>)"), r"\g<1>1\g<2>"),
)
_RE_ANCESTROS = re.compile(
    rb"<photoshop:DocumentAncestors>.*?</photoshop:DocumentAncestors>", re.DOTALL)


def _xmp_para_guardar(xmp: bytes, formato_pil: str, avisos: list):
    texto = xmp.decode("utf-8", "replace")
    for regex, reemplazo in _RE_ORIENTACION_XMP:   # los píxeles ya están girados
        texto = regex.sub(reemplazo, texto)
    xmp = texto.encode("utf-8")
    if formato_pil == "JPEG" and len(xmp) > MAX_XMP_JPEG:
        xmp = _RE_ANCESTROS.sub(b"", xmp)   # historial de Photoshop: suele ser lo que sobra
        if len(xmp) > MAX_XMP_JPEG:
            avisos.append(f"XMP de {len(xmp) // 1024} KB demasiado grande para JPEG: descartado")
            return None
    return xmp


def _segmentos_iptc(im) -> bytes:
    """Segmentos APP13 (Photoshop/IPTC) originales de un JPEG, listos para reinsertar."""
    resultado = b""
    for marcador, datos in getattr(im, "applist", []):
        if marcador == "APP13" and datos.startswith(b"Photoshop 3.0\x00"):
            resultado += b"\xff\xed" + struct.pack(">H", len(datos) + 2) + datos
    return resultado


def parametros_guardado(original, im, formato_pil: str, avisos: list = None) -> dict:
    """Argumentos para `im.save()` que trasladan los metadatos de `original`.

    `original` es la imagen tal como se abrió; `im`, la ya girada con
    ImageOps.exif_transpose (su EXIF ya no lleva orientación).
    """
    avisos = avisos if avisos is not None else []
    kwargs = {}

    exif = im.getexif()
    exif.pop(TAG_ORIENTACION, None)   # ya aplicada: evitar doble giro
    if len(exif):
        kwargs["exif"] = exif

    icc = original.info.get("icc_profile")
    if icc and original.mode != "CMYK":   # un perfil CMYK no vale tras pasar a RGB
        kwargs["icc_profile"] = icc

    xmp = xmp_de(original)
    if xmp:
        xmp = _xmp_para_guardar(xmp, formato_pil, avisos)
        if xmp:
            kwargs["xmp"] = xmp

    if formato_pil == "JPEG":
        if original.info.get("comment"):
            kwargs["comment"] = original.info["comment"]
        iptc = _segmentos_iptc(original)
        if iptc:
            kwargs["extra"] = iptc
        elif leer_iptc(original).get("etiquetas"):
            avisos.append("IPTC de un formato no JPEG: no se ha podido conservar")
    elif _segmentos_iptc(original):
        avisos.append("IPTC no se puede guardar en WebP (las etiquetas XMP sí se conservan)")
    return kwargs
