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
la miniatura EXIF interna, los mapas de profundidad/ganancia HDR (MPF) y el vídeo
incrustado de las fotos con movimiento (también su anuncio en el XMP).

Metadatos externos (`MetadatosExtra`, p. ej. el JSON de Google Fotos): se añaden al
exportar. Fecha y GPS van al EXIF solo si la foto no los trae; álbumes (dc:subject),
personas (Iptc4xmpExt:PersonInImage), descripción y favorita (xmp:Rating) van al XMP.
"""

import io
import math
import re
import struct
import threading
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from PIL import Image, IptcImagePlugin

from .media_utils import MetadatosExtra, fecha_desde_nombre, fecha_mtime, fecha_plausible

# --- Etiquetas EXIF ---
IFD_EXIF, IFD_GPS = 0x8769, 0x8825
TAG_DESCRIPCION, TAG_MARCA, TAG_MODELO, TAG_ORIENTACION = 270, 271, 272, 274
TAG_FECHA, TAG_AUTOR, TAG_VALORACION = 306, 315, 18246
TAG_XP_TITULO, TAG_XP_COMENTARIO, TAG_XP_AUTOR, TAG_XP_ETIQUETAS = 0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E
TAG_EXPOSICION, TAG_APERTURA, TAG_ISO = 33434, 33437, 34855
TAG_FECHA_ORIGINAL, TAG_FECHA_DIGITALIZADA = 36867, 36868
TAG_ZONA_ORIGINAL, TAG_ZONA_DIGITALIZADA = 0x9011, 0x9012   # OffsetTime*: "+02:00"
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
    "x": "adobe:ns:meta/",
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


def _fragmento_xmp(xmp):
    """El x:xmpmeta (o rdf:RDF) del paquete, sin las instrucciones <?xpacket?>; None si
    no es XML aceptable (nada de DOCTYPE ni entidades)."""
    texto = xmp.decode("utf-8", "replace") if isinstance(xmp, bytes) else xmp
    if "<!DOCTYPE" in texto or "<!ENTITY" in texto:
        return None
    for apertura, cierre in (("<x:xmpmeta", "</x:xmpmeta>"), ("<rdf:RDF", "</rdf:RDF>")):
        inicio, fin = texto.find(apertura), texto.rfind(cierre)
        if inicio >= 0 and fin > inicio:
            return texto[inicio:fin + len(cierre)]
    return texto


def leer_xmp(xmp) -> dict:
    datos = {"etiquetas": [], "personas": [], "titulo": "", "descripcion": "", "valoracion": 0}
    if not xmp:
        return datos
    texto = _fragmento_xmp(xmp)
    if texto is None:
        return datos
    try:
        raiz = ET.fromstring(texto)
    except ET.ParseError:
        return datos

    li = _q("rdf", "li")

    def lista(elemento):
        return [x.text for x in elemento.iter(li) if x.text and x.text.strip()]

    def alternativa(elemento):
        opciones = [x for x in elemento.iter(li) if x.text and x.text.strip()]
        # Ojo: un Element sin hijos es "falso"; hay que comparar con None
        preferida = next((x for x in opciones if x.get(XML_LANG) == "x-default"), None)
        if preferida is None:
            preferida = opciones[0] if opciones else elemento
        return preferida.text or ""

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
    orientados), animado y gps. Con `completo`, además: camara, objetivo, exposicion,
    etiquetas, personas, titulo, descripcion, autor y valoracion (0-5).
    """
    with Image.open(ruta) as im:
        exif = im.getexif()
        ancho, alto = im.size
        if exif.get(TAG_ORIENTACION) in (5, 6, 7, 8):
            ancho, alto = alto, ancho
        datos = {"fecha": fecha_exif(exif), "fuente": "exif", "ancho": ancho, "alto": alto,
                 # MPO (JPEG de Sony, Fujifilm… con vista previa o par 3D) tiene varias
                 # imágenes pero no es una animación: se trata como un JPEG normal
                 "animado": bool(getattr(im, "is_animated", False)) and im.format != "MPO",
                 "gps": gps_exif(exif)}
        if completo:
            sub = exif.get_ifd(IFD_EXIF)
            xmp, iptc = leer_xmp(xmp_de(im)), leer_iptc(im)
            datos.update(
                camara=camara_exif(exif),
                objetivo=_texto(sub.get(TAG_OBJETIVO)),
                exposicion=exposicion_exif(exif),
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
# Fotos con movimiento (Pixel, Samsung): el XMP anuncia un vídeo al final del JPEG y lo
# localiza con Container:Directory. Al recomprimir ese vídeo desaparece: el anuncio
# también, o un visor buscaría el vídeo en datos que ya no lo son.
_RE_FOTO_MOVIMIENTO = (
    re.compile(r'\s+GCamera:(?:MotionPhoto|MicroVideo)\w*\s*=\s*"[^"]*"'),
    re.compile(r"<(GCamera:(?:MotionPhoto|MicroVideo)\w*)>[^<]*</\1>"),
    re.compile(r"<Container:Directory>.*?</Container:Directory>", re.DOTALL),
)


def _xmp_para_guardar(xmp: bytes, formato_pil: str, avisos: list):
    texto = xmp.decode("utf-8", "replace")
    for regex, reemplazo in _RE_ORIENTACION_XMP:   # los píxeles ya están girados
        texto = regex.sub(reemplazo, texto)
    for regex in _RE_FOTO_MOVIMIENTO:
        texto = regex.sub("", texto)
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


def parametros_guardado(original, im, formato_pil: str, avisos: list = None,
                        extra: MetadatosExtra = None) -> dict:
    """Argumentos para `im.save()` que trasladan los metadatos de `original`.

    `original` es la imagen tal como se abrió; `im`, la ya girada con
    ImageOps.exif_transpose (su EXIF ya no lleva orientación). `extra` (opcional) son
    metadatos externos que se añaden a los de la foto (ver `MetadatosExtra`).
    """
    avisos = avisos if avisos is not None else []
    kwargs = {}

    exif = im.getexif()
    exif.pop(TAG_ORIENTACION, None)   # ya aplicada: evitar doble giro
    # Ojo: en una foto sin EXIF, la fecha añadida va al sub-IFD y len(exif) sigue a 0
    if completar_exif(exif, extra) or len(exif):
        kwargs["exif"] = exif

    icc = original.info.get("icc_profile")
    if icc and original.mode != "CMYK":   # un perfil CMYK no vale tras pasar a RGB
        kwargs["icc_profile"] = icc

    xmp = completar_xmp(xmp_de(original), extra)
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


# ============================= Metadatos externos =============================

def _grados_minutos_segundos(valor: float) -> tuple:
    valor = abs(valor)
    grados = int(valor)
    minutos = int((valor - grados) * 60)
    segundos = round(((valor - grados) * 60 - minutos) * 60, 4)
    return (float(grados), float(minutos), segundos)


def completar_exif(exif, extra: MetadatosExtra = None) -> bool:
    """Añade al EXIF la fecha y el GPS de `extra` si la foto no los trae, y las etiquetas
    sueltas de `extra.exif` que no tenga (el GPS, entero y solo si no tiene). ¿Ha cambiado?

    La descripción no va al EXIF (ImageDescription es ASCII y perdería los acentos):
    va al XMP, que es lo primero que se lee.
    """
    if extra is None:
        return False
    cambiado = False
    if extra.exif:   # etiquetas sueltas de otra copia de la foto (fusion_metadatos.py)
        gps_nuevo = {tag: valor for (ifd, tag), valor in extra.exif.items() if ifd == IFD_GPS}
        if gps_nuevo and gps_exif(exif) is None:
            gps = exif.get_ifd(IFD_GPS)
            gps.clear()
            gps.update(gps_nuevo)
            cambiado = True
        for (ifd, tag), valor in extra.exif.items():
            if ifd == IFD_GPS:
                continue
            destino = exif if ifd == 0 else exif.get_ifd(ifd)
            if tag not in destino:
                destino[tag] = valor
                cambiado = True
    if extra.fecha and fecha_exif(exif) is None:
        texto = extra.fecha.strftime("%Y:%m:%d %H:%M:%S")
        sub = exif.get_ifd(IFD_EXIF)
        sub[TAG_FECHA_ORIGINAL] = sub[TAG_FECHA_DIGITALIZADA] = texto
        if extra.zona:
            sub[TAG_ZONA_ORIGINAL] = sub[TAG_ZONA_DIGITALIZADA] = extra.zona
        cambiado = True
    if extra.gps and gps_exif(exif) is None:
        lat, lon, altitud = (tuple(extra.gps) + (None,))[:3]
        gps = exif.get_ifd(IFD_GPS)
        gps.clear()
        gps.update({0: b"\x02\x03\x00\x00", 1: "N" if lat >= 0 else "S",
                    2: _grados_minutos_segundos(lat), 3: "E" if lon >= 0 else "W",
                    4: _grados_minutos_segundos(lon)})
        if altitud:
            gps[5], gps[6] = (b"\x00" if altitud >= 0 else b"\x01"), round(abs(altitud), 2)
        cambiado = True
    return cambiado


_XMP_VACIO = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="'
              + NS["rdf"] + '"><rdf:Description rdf:about=""/></rdf:RDF></x:xmpmeta>')
_lock_xml = threading.Lock()   # register_namespace es global: no mezclar hilos


def completar_xmp(xmp, extra: MetadatosExtra = None):
    """Paquete XMP con los álbumes, personas, descripción y favorita de `extra` añadidos.

    Etiquetas y personas se suman a las que ya hubiera (sin repetir); la descripción
    sustituye a la anterior (es la que se escribió en Google Fotos), y el título igual;
    la favorita es xmp:Rating = 5 si no tenía valoración; `valoracion`, la que se pone
    si la que tiene es menor. El resto del XMP se conserva. Sin nada que añadir, o si el
    XMP no se puede interpretar, devuelve `xmp` sin tocar.
    """
    if extra is None or not extra.aporta_xmp():
        return xmp
    fragmento = _fragmento_xmp(xmp) if xmp else _XMP_VACIO
    if fragmento is None:
        return xmp
    try:
        prefijos = {}
        for _, (prefijo, uri) in ET.iterparse(io.StringIO(fragmento), events=("start-ns",)):
            prefijos.setdefault(prefijo, uri)
        raiz = ET.fromstring(fragmento)
    except ET.ParseError:
        return xmp
    rdf = raiz if raiz.tag == _q("rdf", "RDF") else raiz.find(_q("rdf", "RDF"))
    if rdf is None:
        return xmp
    descripcion = rdf.find(_q("rdf", "Description"))
    if descripcion is None:
        descripcion = ET.SubElement(rdf, _q("rdf", "Description"), {_q("rdf", "about"): ""})

    def anadir(propiedad, valores):
        valores = [v.strip() for v in valores if v and v.strip()]
        if not valores:
            return
        elemento = next(raiz.iter(propiedad), None)
        if elemento is None:
            elemento = ET.SubElement(descripcion, propiedad)
        bolsa = next((h for h in elemento if h.tag in (_q("rdf", "Bag"), _q("rdf", "Seq"))),
                     None)
        if bolsa is None:
            bolsa = ET.SubElement(elemento, _q("rdf", "Bag"))
        vistos = {(li.text or "").strip().lower() for li in bolsa.iter(_q("rdf", "li"))}
        for valor in valores:
            if valor.lower() not in vistos:
                vistos.add(valor.lower())
                ET.SubElement(bolsa, _q("rdf", "li")).text = valor

    def texto_alternativo(propiedad, texto):   # dc:description, dc:title: sustituyen al suyo
        elemento = next(raiz.iter(propiedad), None)
        if elemento is None:
            elemento = ET.SubElement(descripcion, propiedad)
        for hijo in list(elemento):
            elemento.remove(hijo)
        elemento.text = None
        alternativa = ET.SubElement(elemento, _q("rdf", "Alt"))
        ET.SubElement(alternativa, _q("rdf", "li"), {XML_LANG: "x-default"}).text = texto

    anadir(_q("dc", "subject"), extra.etiquetas)
    anadir(_q("Iptc4xmpExt", "PersonInImage"), extra.personas)
    if extra.descripcion:
        texto_alternativo(_q("dc", "description"), extra.descripcion)
    if extra.titulo:
        texto_alternativo(_q("dc", "title"), extra.titulo)
    valoracion = _q("xmp", "Rating")
    actuales = [e for e in raiz.iter() if e.tag == valoracion or valoracion in e.attrib]
    if extra.favorita and not actuales:
        descripcion.set(valoracion, "5")
    elif extra.valoracion:
        def valor(e):
            try:
                return float(e.text if e.tag == valoracion else e.get(valoracion))
            except (TypeError, ValueError):
                return 0
        if not actuales:
            descripcion.set(valoracion, str(extra.valoracion))
        for e in actuales:
            if valor(e) < extra.valoracion:
                if e.tag == valoracion:
                    e.text = str(extra.valoracion)
                else:
                    e.set(valoracion, str(extra.valoracion))

    with _lock_xml:
        for prefijo, uri in list(prefijos.items()) + list(NS.items()):
            if prefijo:
                try:
                    ET.register_namespace(prefijo, uri)
                except ValueError:
                    pass   # prefijos "ns0"... reservados: ElementTree pone uno propio
        cuerpo = ET.tostring(raiz, encoding="unicode")
    return ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            f'{cuerpo}\n<?xpacket end="w"?>').encode("utf-8")


# --- JPEG sin recomprimir ---

_SOS, _EOI, _APP0, _APP1, _APP2 = 0xDA, 0xD9, 0xE0, 0xE1, 0xE2
CABECERA_EXIF_JPEG = b"Exif\x00\x00"


def _segmentos_jpeg(datos: bytes):
    """([(marcador, inicio, fin)] de los segmentos previos a la imagen, inicio de SOS)."""
    if datos[:2] != b"\xff\xd8":
        raise ValueError("no es un JPEG")
    segmentos, pos = [], 2
    while pos + 4 <= len(datos):
        if datos[pos] != 0xFF:
            raise ValueError("estructura JPEG no reconocida")
        marcador = datos[pos + 1]
        if marcador == 0xFF:          # relleno
            pos += 1
            continue
        if marcador in (_SOS, _EOI):
            return segmentos, pos
        if 0xD0 <= marcador <= 0xD7 or marcador == 0x01:   # sin longitud
            pos += 2
            continue
        fin = pos + 2 + struct.unpack(">H", datos[pos + 2:pos + 4])[0]
        if fin > len(datos):
            raise ValueError("JPEG truncado")
        segmentos.append((marcador, pos, fin))
        pos = fin
    raise ValueError("JPEG sin imagen")


def _segmento(marcador: int, cuerpo: bytes) -> bytes:
    return b"\xff" + bytes([marcador]) + struct.pack(">H", len(cuerpo) + 2) + cuerpo


def jpeg_con_extra(datos: bytes, extra: MetadatosExtra) -> bytes:
    """El mismo JPEG, sin recomprimir, con el EXIF y el XMP completados con `extra`.

    Solo se sustituyen (o añaden) los segmentos EXIF y XMP; píxeles, ICC, IPTC, MPF y lo
    que vaya detrás de la imagen (el vídeo de una foto con movimiento) quedan byte a byte.
    Lanza ValueError si no se puede hacer sin riesgo.
    """
    segmentos, inicio_sos = _segmentos_jpeg(datos)
    with Image.open(io.BytesIO(datos)) as im:
        exif, xmp = im.getexif(), xmp_de(im)
    nuevo_exif = exif.tobytes() if completar_exif(exif, extra) else None
    nuevo_xmp = completar_xmp(xmp, extra)
    nuevo_xmp = None if nuevo_xmp == xmp else nuevo_xmp
    if nuevo_exif is None and nuevo_xmp is None:
        return datos
    if nuevo_exif is not None and len(nuevo_exif) > 65533:
        raise ValueError("EXIF demasiado grande para un segmento JPEG")
    if nuevo_xmp is not None and len(nuevo_xmp) > MAX_XMP_JPEG:
        raise ValueError("XMP demasiado grande para un segmento JPEG")

    def tipo(marcador, inicio):
        cuerpo = datos[inicio + 4:inicio + 4 + len(CABECERA_XMP_JPEG)]
        if marcador == _APP1 and cuerpo.startswith(CABECERA_EXIF_JPEG):
            return "exif"
        if marcador == _APP1 and cuerpo.startswith(CABECERA_XMP_JPEG):
            return "xmp"
        if marcador == _APP2 and cuerpo.startswith(b"MPF\x00"):
            return "mpf"
        return ""

    tipos = [tipo(m, i) for m, i, _ in segmentos]
    nuevos = {"exif": nuevo_exif and _segmento(_APP1, nuevo_exif),
              "xmp": nuevo_xmp and _segmento(_APP1, CABECERA_XMP_JPEG + nuevo_xmp)}
    # Los que no existían se insertan tras el APP0 (JFIF): primero EXIF, luego XMP
    por_insertar = [nuevos[t] for t in ("exif", "xmp") if nuevos[t] and t not in tipos]
    salida, mpf_visto, cambio_tras_mpf = [datos[:2]], False, False
    for (marcador, inicio, fin), t in zip(segmentos, tipos):
        if por_insertar and marcador != _APP0:
            salida += por_insertar
            por_insertar = []
            cambio_tras_mpf |= mpf_visto
        if nuevos.get(t):
            salida.append(nuevos[t])
            nuevos[t] = None   # solo el primero (el XMP extendido, si lo hay, se queda)
            cambio_tras_mpf |= mpf_visto
        else:
            salida.append(datos[inicio:fin])
        mpf_visto |= t == "mpf"
    salida += por_insertar
    if cambio_tras_mpf:
        # MPF guarda la posición de sus imágenes relativa a su propio segmento
        raise ValueError("JPEG con imágenes MPF antes del EXIF/XMP")
    salida.append(datos[inicio_sos:])
    return b"".join(salida)
