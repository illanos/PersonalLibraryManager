"""Fusionar colecciones: añadir a una biblioteca las fotos y vídeos de otra colección
sin repetir lo que ya tiene, quedándose siempre con la copia de más calidad.

    python main.py fusionar <colección> --destino <biblioteca> [--simular]

La colección puede ser otra biblioteca del exportador (p. ej. la de Google Fotos) o
cualquier carpeta con fotos y vídeos. **Solo se lee**: nunca se modifica.

Cómo se decide, archivo a archivo:

  - Se compara **por días**: cada foto o vídeo de la colección solo se compara con los
    de la biblioteca del mismo día (± `margen_dias`, 1 por defecto, por las fotos de
    cerca de medianoche o con otra zona horaria).
  - **Fotos iguales**: dHash (similares.py) a `umbral` bits o menos (5 por defecto, lo
    que separa una foto de su copia recomprimida o reducida), proporción compatible y,
    si las dos tienen fecha EXIF, la misma: otra toma de una ráfaga se parece mucho,
    pero no es una copia y sí se añade. También son iguales las que vienen del mismo
    original (mismo MD5 en los dos catálogos) y los archivos idénticos.
  - **Vídeos iguales**: duración casi igual, proporción compatible y fotogramas
    parecidos en los mismos instantes (20, 50 y 80 % del vídeo), con FFmpeg.
  - De dos iguales se queda la de **más calidad** (ver `comparar`):
      · la de la biblioteca es igual o mejor -> la de la colección no se añade;
      · la de la colección es mejor -> entra en la biblioteca y la otra va a la
        papelera (.exportador/papelera; se restaura desde «Limpiar repetidas»).
  - Sin copia igual, se añade. Lo que ya está en un formato de la galería se copia tal
    cual (sin recomprimir: no pierde calidad); lo demás se convierte como al importar
    (JPEG, MP4) y las fotos de más de `max_lado` px se reducen, como en la biblioteca.
  - Dentro de la propia colección tampoco se repite nada: de varias copias, entra la mejor.
  - WhatsApp sigue aparte: lo de WhatsApp de la colección va a `WhatsApp/`.

Todo queda en el catálogo de la biblioteca: lo añadido no se vuelve a fusionar y lo
descartado no se vuelve a comparar mientras no cambie. Un informe CSV recoge cada
decisión (en simulación, en la carpeta temporal del sistema).
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePath

from PIL import Image, ImageOps

from catalogo import ESPERA_BLOQUEO, Catalogo, Informe, ruta_catalogo
from clasificacion import CARPETA_PEGATINAS, CARPETA_WHATSAPP, carpeta_destino, categoria, es_whatsapp
from fotos import CALIDAD, EXTENSIONES_FOTO, EXTENSIONES_HEIF, HEIF_DISPONIBLE, MAX_LADO, OpcionesFotos, \
    guardar_optimizada
from galeria import EXTENSIONES_FOTO as FOTO_GALERIA, EXTENSIONES_VIDEO as VIDEO_GALERIA, VERSION_INDICE
from media_utils import (
    CARPETA_GALERIA, CARPETA_INTERNA, fecha_desde_nombre, fecha_mtime, fecha_y_nombre,
    formato_bytes, hash_archivo, imprimir, listar_archivos, nombre_libre, progreso, ruta_temporal,
)
from metadatos import camara_exif, fecha_exif
from similares import UMBRAL, UMBRAL_COPIA, _proporciones_compatibles, con_detalle, dhash_imagen, distancia
from videos import EXTENSIONES_VIDEO, OpcionesVideos, comando_codificacion, detener_ffmpeg, \
    dimensiones_objetivo, ejecutar_ffmpeg, fecha_video, sondear

UMBRAL_MAX = UMBRAL                 # más de 12 bits ya no son copias, sino fotos distintas
TOLERANCIA_RESOLUCION = 0.05        # ±5 % de píxeles cuenta como la misma resolución
MARGEN_PESO = 0.10                  # pesar un 10 % más (misma resolución) = menos comprimida
SEGUNDOS_EXIF = 0                   # dos fechas EXIF distintas = otra toma (ráfaga), no una copia
DURACION_SEGUNDOS, DURACION_RELATIVA = 1.0, 0.02   # vídeos iguales: ±1 s o ±2 % de duración
INSTANTES_VIDEO = (0.2, 0.5, 0.8)   # fotogramas que se comparan (fracción de la duración)
UMBRAL_VIDEO = 8                    # bits (de 128) como máximo en cada fotograma
MAX_LADO_VIDEO = OpcionesVideos().max_lado
MOTIVO_DESCARTE = "fusion"          # en la tabla `descartes`: comparada y no añadida
_RE_SENT = re.compile(r"(^|[\\/])sent([\\/]|$)", re.IGNORECASE)
_RE_NOMBRE_BIBLIOTECA = re.compile(r"^\d{8}_")          # 20240512_102030, 20240512_WA0011
_RE_SUFIJO_RAFAGA = re.compile(r"^(\d{8}_\d{6})_\d{2}$")  # 20240512_102030_01 -> base sin _01
_RE_COPIA_TAKEOUT = re.compile(r"\(\d+\)$")             # IMG_1234(1): repetida en Takeout
MISMO_NOMBRE = "mismo original (nombre y hora)"


@dataclass
class OpcionesFusion:
    umbral: int = UMBRAL_COPIA      # bits para considerar dos fotos la misma (0-12)
    margen_dias: int = 1            # días antes y después con los que se compara
    max_lado: int = MAX_LADO        # fotos más grandes se reducen al añadirlas (0 = tal cual)
    calidad: int = CALIDAD          # al reducir o convertir una foto
    hilos: int = 0                  # 0 = según los núcleos
    galeria: bool = True            # actualizar la galería de la biblioteca al terminar


@dataclass(eq=False)
class Elemento:
    """Una foto o un vídeo de la biblioteca ('b'), de su papelera ('p') o de la colección ('c')."""
    lado: str
    tipo: str                       # 'foto' | 'video'
    ruta: Path
    rel: str                        # relativa a su carpeta, con '/'
    fecha: datetime = None
    fuente: str = ""                # de dónde salió la fecha: exif | metadatos | nombre | archivo...
    ancho: int = 0
    alto: int = 0
    bytes: int = 0
    dhash: str = None
    duracion: float = 0.0
    camara: bool = False            # EXIF / metadatos de cámara
    whatsapp: bool = False
    sent: bool = False
    hash_original: str = None       # MD5 del original según su catálogo
    nombre_original: str = ""       # nombre (sin extensión, en minúsculas) del archivo original
    animado: bool = False
    st: os.stat_result = None
    marcos: dict = field(default_factory=dict)   # vídeos: instante -> dHash del fotograma
    hashes: dict = field(default_factory=dict)   # fotos: giro -> dHash del propio archivo
    md5: str = None
    # Solo colección: qué se va a hacer con ella
    categoria: str = ""
    base: str = ""                  # nombre en la biblioteca, sin extensión
    convertir: bool = False         # al añadirla: reducir o pasar a un formato de la galería
    accion: str = ""                # anadir | sustituir | ya_esta | repetida | quitada | error
    pareja: "Elemento" = None       # la copia igual con la que se ha comparado
    como: str = ""                  # por qué son iguales: "N bits", "mismo original"...
    sustituye: "Elemento" = None    # la de la biblioteca que pasa a la papelera
    motivo: str = ""
    parecida: tuple = None          # (elemento, bits): parecida, pero no igual
    destino_rel: str = ""
    clave: str = None               # hash con el que se anota en el catálogo
    tmp: Path = None                # copia preparada (.part) antes de colocarla
    aviso: str = ""

    @property
    def dia(self) -> int:
        return self.fecha.toordinal()

    @property
    def proporcion(self):
        return self.ancho / self.alto if self.ancho and self.alto else None


# ----------------------------- Calidad -----------------------------

def pixeles(e: Elemento, max_lado: int = MAX_LADO) -> int:
    """Píxeles con los que quedaría en la biblioteca (lo que se reduce al añadir, reducido)."""
    ancho, alto = e.ancho or 0, e.alto or 0
    if e.lado == "c" and e.convertir:
        if e.tipo == "foto" and max_lado and max(ancho, alto) > max_lado:
            factor = max_lado / max(ancho, alto)
            ancho, alto = round(ancho * factor), round(alto * factor)
        elif e.tipo == "video":
            ancho, alto = dimensiones_objetivo(ancho, alto, MAX_LADO_VIDEO)
    return ancho * alto


def _peso_comparable(a: Elemento, b: Elemento) -> bool:
    """El peso solo dice algo si los dos archivos entran tal cual (no se recomprimen)."""
    return not (a.lado == "c" and a.convertir) and not (b.lado == "c" and b.convertir)


def comparar(a: Elemento, b: Elemento, max_lado: int = MAX_LADO) -> tuple:
    """(>0 si `a` es mejor que `b`, <0 si es peor, 0 si equivalen; motivo legible).

    Fotos: resolución, EXIF de cámara, no WhatsApp, no la enviada (Sent), peso.
    Vídeos: resolución, no WhatsApp, bitrate, metadatos de cámara.
    Las diferencias pequeñas (±5 % de píxeles, ±10 % de peso) no cuentan.
    """
    pa, pb = pixeles(a, max_lado), pixeles(b, max_lado)
    mayor = max(pa, pb)
    if mayor and abs(pa - pb) / mayor > TOLERANCIA_RESOLUCION:
        return (1 if pa > pb else -1), "más resolución"

    def bandera(clave, mejor_si):
        va, vb = getattr(a, clave), getattr(b, clave)
        return 0 if va == vb else (1 if va == mejor_si else -1)

    def mayor_con_margen(va, vb):
        if va > vb * (1 + MARGEN_PESO):
            return 1
        return -1 if vb > va * (1 + MARGEN_PESO) else 0

    if a.tipo == "foto":
        criterios = [
            ("tiene EXIF de cámara", lambda: bandera("camara", True)),
            ("no viene de WhatsApp", lambda: bandera("whatsapp", False)),
            ("no es la copia enviada (Sent)", lambda: bandera("sent", False)),
            ("más peso (menos comprimida)", lambda: mayor_con_margen(a.bytes, b.bytes)
             if _peso_comparable(a, b) else 0),
        ]
    else:
        criterios = [
            ("no viene de WhatsApp", lambda: bandera("whatsapp", False)),
            ("más bitrate (menos comprimido)", lambda: mayor_con_margen(
                a.bytes / a.duracion, b.bytes / b.duracion)
             if _peso_comparable(a, b) and a.duracion > 0 and b.duracion > 0 else 0),
            ("tiene metadatos de cámara", lambda: bandera("camara", True)),
        ]
    for motivo, criterio in criterios:
        signo = criterio()
        if signo:
            return signo, motivo
    return 0, "copias equivalentes"


def _clave_calidad(e: Elemento, max_lado: int) -> tuple:
    return (pixeles(e, max_lado), e.camara, not e.whatsapp, not e.sent, e.bytes)


# ----------------------------- Fotogramas -----------------------------

def hash_fotograma(ruta: Path, instante: float):
    """dHash del fotograma del vídeo en `instante` segundos (girado como se ve), o None."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{instante:.2f}",
           "-i", str(ruta), "-frames:v", "1", "-vf", "scale=128:-2",
           "-f", "image2pipe", "-c:v", "png", "-"]
    try:
        salida = subprocess.run(cmd, capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if salida.returncode != 0 or not salida.stdout:
        return None
    try:
        with Image.open(BytesIO(salida.stdout)) as im:
            return dhash_imagen(im)
    except Exception:
        return None


def _instantes(a: Elemento, b: Elemento) -> list:
    """Los mismos instantes en los dos vídeos (sobre el más corto)."""
    duracion = min(a.duracion, b.duracion)
    return [round(duracion * f, 1) for f in INSTANTES_VIDEO]


def _marco(e: Elemento, instante: float):
    if instante not in e.marcos:
        e.marcos[instante] = hash_fotograma(e.ruta, instante)
    return e.marcos[instante]


def distancia_video(a: Elemento, b: Elemento):
    """Mayor diferencia (bits) entre los fotogramas comparables, o None si no se puede saber
    (vídeos casi negros, FFmpeg falla...): ante la duda, no son iguales."""
    bits = []
    for t in _instantes(a, b):
        ha, hb = _marco(a, t), _marco(b, t)
        if ha and hb and con_detalle(ha) and con_detalle(hb):
            bits.append(distancia(ha, hb))
    return max(bits) if len(bits) >= 2 else None


def _duraciones_compatibles(a: float, b: float) -> bool:
    if not a or not b:
        return False
    return abs(a - b) <= max(DURACION_SEGUNDOS, DURACION_RELATIVA * max(a, b))


# ----------------------------- Buscar la copia igual -----------------------------

class Indice:
    """Elementos por tipo y día (los de la biblioteca y lo que ya va a entrar)."""

    def __init__(self, margen_dias: int):
        self.margen = margen_dias
        self.por_dia = {}
        self.por_hash = {}

    def anadir(self, e: Elemento):
        self.por_dia.setdefault((e.tipo, e.dia), []).append(e)
        if e.hash_original:
            self.por_hash.setdefault(e.hash_original, e)

    def quitar(self, e: Elemento):
        self.por_dia[(e.tipo, e.dia)].remove(e)
        if e.hash_original and self.por_hash.get(e.hash_original) is e:
            del self.por_hash[e.hash_original]

    def candidatos(self, e: Elemento):
        for d in range(-self.margen, self.margen + 1):
            yield from self.por_dia.get((e.tipo, e.dia + d), ())


def _md5(e: Elemento):
    if e.md5 is None:
        try:
            e.md5 = hash_archivo(e.ruta)
        except OSError:
            e.md5 = ""
    return e.md5


def _identicos(a: Elemento, b: Elemento) -> bool:
    return bool(a.bytes and a.bytes == b.bytes and _md5(a) and _md5(a) == _md5(b))


def _otra_toma(a: Elemento, b: Elemento) -> bool:
    """Las dos tienen fecha EXIF y no es la misma: otra toma (ráfaga), no una copia.
    (Las tomas de una ráfaga se separan 1 s y su dHash puede diferir solo 1-2 bits.)"""
    return (a.fuente == "exif" and b.fuente == "exif"
            and abs((a.fecha - b.fecha).total_seconds()) > SEGUNDOS_EXIF)


def normalizar_nombre(stem: str) -> str:
    """Nombre del original para compararlo: en minúsculas y sin el «(1)» que añade Takeout
    a los archivos con el mismo nombre (DSCN0169(1).JPG es DSCN0169.JPG)."""
    return _RE_COPIA_TAKEOUT.sub("", stem.strip().lower()).strip()


def hash_de_archivo(e: Elemento, giro: int = 0):
    """dHash calculado del propio archivo (girado `giro` grados), con caché.

    Los guardados salen del original (catálogo) o de la miniatura (galería), y entre dos
    bibliotecas casan algo peor; este es el mismo cálculo en las dos. Solo se usa para
    confirmar casos dudosos (tarda: hay que abrir la foto)."""
    if giro not in e.hashes:
        try:
            with Image.open(e.ruta) as im:
                im.draft("RGB", (128, 128))
                orientacion = im.getexif().get(274)
                imagen = im.copy() if orientacion in (None, 1) else ImageOps.exif_transpose(im)
            e.hashes[giro] = dhash_imagen(imagen.rotate(giro, expand=True) if giro else imagen)
        except Exception:
            e.hashes[giro] = None
    return e.hashes[giro]


def _mismo_nombre_y_hora(a: Elemento, b: Elemento) -> str:
    """Mismo archivo original (por nombre) y misma hora de captura: la misma foto o vídeo
    aunque cada colección lo haya reducido o recomprimido a su manera (su dHash puede
    diferir hasta ~10 bits), o girado 90° en una de las dos. Como comprobación, que se
    parezcan (≤ 12 bits, girando si hace falta) o, en vídeos, que duren lo mismo.
    Devuelve cómo se sabe, o "" si no lo son."""
    if not a.nombre_original or a.nombre_original != b.nombre_original or a.fecha != b.fecha:
        return ""
    if a.tipo == "video":
        return MISMO_NOMBRE if _duraciones_compatibles(a.duracion, b.duracion) else ""
    if _proporciones_compatibles(a.proporcion, b.proporcion):
        if a.dhash and b.dhash and distancia(a.dhash, b.dhash) <= UMBRAL:
            return MISMO_NOMBRE
        ha, hb = hash_de_archivo(a), hash_de_archivo(b)
        return MISMO_NOMBRE if ha and hb and distancia(ha, hb) <= UMBRAL else ""
    if a.proporcion and b.proporcion and _proporciones_compatibles(a.proporcion, 1 / b.proporcion):
        ha = hash_de_archivo(a)
        for giro in (90, 270):
            hb = hash_de_archivo(b, giro)
            if ha and hb and distancia(ha, hb) <= UMBRAL:
                return f"{MISMO_NOMBRE}, girada 90° en una de las dos"
    return ""


def buscar_pareja(c: Elemento, indice: Indice, umbral: int = UMBRAL_COPIA) -> tuple:
    """(copia igual a `c` en el índice o None, cómo se sabe). Anota en `c.parecida` la
    foto más parecida que no llega a ser igual (para el informe)."""
    mismo = indice.por_hash.get(c.hash_original) if c.hash_original else None
    if mismo is not None and mismo.tipo == c.tipo:
        return mismo, "mismo original"
    mejor, mejor_bits = None, None
    for e in indice.candidatos(c):
        como = _mismo_nombre_y_hora(c, e)
        if como:
            return e, como
        if not _proporciones_compatibles(c.proporcion, e.proporcion):
            continue
        if c.tipo == "video" and not _duraciones_compatibles(c.duracion, e.duracion):
            continue
        if _identicos(c, e):
            return e, "archivo idéntico"
        if c.tipo == "video":
            bits = distancia_video(c, e)
            if bits is None or bits > UMBRAL_VIDEO:
                continue
        else:
            if not (c.dhash and e.dhash and con_detalle(c.dhash) and con_detalle(e.dhash)):
                continue
            bits = distancia(c.dhash, e.dhash)
            if umbral < bits <= UMBRAL and not _otra_toma(c, e):
                # Cerca del umbral con hashes de distinto origen: lo dicen los archivos
                ha, hb = hash_de_archivo(c), hash_de_archivo(e)
                if ha and hb:
                    bits = distancia(ha, hb)
            if bits > umbral or _otra_toma(c, e):
                if bits <= UMBRAL and (c.parecida is None or bits < c.parecida[1]):
                    c.parecida = (e, bits)
                continue
        if mejor is None or bits < mejor_bits:
            mejor, mejor_bits = e, bits
    if mejor is None:
        return None, ""
    return mejor, f"{mejor_bits} bit{'s' if mejor_bits != 1 else ''} de diferencia"


def planificar(coleccion: list, biblioteca: list, papelera: list = (), descartadas=(),
               opciones: OpcionesFusion = None):
    """Decide qué hacer con cada elemento de la colección (rellena `accion`, `pareja`...).

    Se recorre de mejor a peor calidad, así que de varias copias en la colección entra
    la mejor; si aun así llega después una mejor, ocupa el sitio de la anterior.
    """
    opciones = opciones or OpcionesFusion()
    indice, quitadas = Indice(opciones.margen_dias), Indice(opciones.margen_dias)
    for e in biblioteca:
        indice.anadir(e)
    for e in papelera:
        quitadas.anadir(e)
    descartadas = set(descartadas)
    orden = sorted(coleccion, key=lambda e: (_clave_calidad(e, opciones.max_lado), e.rel),
                   reverse=True)
    for n, c in enumerate(orden, 1):
        if n % 200 == 0 or n == len(orden):
            progreso("avance", "fusionar", paso="Comparando por días", hecho=n, total=len(orden),
                     archivo=c.rel)
        if c.accion:           # error al leerla
            continue
        if c.hash_original and c.hash_original in descartadas:
            c.accion, c.motivo = "quitada", "quitada antes con «Limpiar repetidas»"
            continue
        pareja, como = buscar_pareja(c, indice, opciones.umbral)
        if pareja is None:
            parecida = c.parecida   # la de la biblioteca, no la de la papelera
            quitada, como = buscar_pareja(c, quitadas, opciones.umbral)
            c.parecida = parecida
            if quitada is not None:
                c.accion, c.pareja, c.como = "quitada", quitada, como
                c.motivo = f"igual que {quitada.rel}, quitada antes con «Limpiar repetidas»"
                continue
            c.accion = "anadir"
            indice.anadir(c)
            continue
        c.pareja, c.como = pareja, como
        signo, motivo = comparar(c, pareja, opciones.max_lado)
        if signo <= 0:
            c.accion = "ya_esta" if pareja.lado == "b" else "repetida"
            c.motivo = motivo
            continue
        c.motivo = motivo
        if pareja.lado == "b":
            c.accion, c.sustituye = "sustituir", pareja
        else:   # otra copia de la colección que iba a entrar: entra esta en su lugar
            c.accion, c.sustituye = pareja.accion, pareja.sustituye
            pareja.accion, pareja.pareja, pareja.sustituye = "repetida", c, None
            pareja.como, pareja.motivo = como, motivo
            pareja.parecida = None
        indice.quitar(pareja)
        indice.anadir(c)
    return coleccion


# ----------------------------- Lectura -----------------------------

def _fecha_iso(texto):
    try:
        return datetime.fromisoformat(texto) if texto else None
    except (TypeError, ValueError):
        return None


def _leer_foto(ruta: Path, con_hash: bool = True) -> dict:
    """Dimensiones (ya giradas), fecha EXIF, cámara, animada y dHash, abriendo la foto una vez."""
    with Image.open(ruta) as im:
        exif = im.getexif()
        ancho, alto = im.size
        orientacion = exif.get(274)
        if orientacion in (5, 6, 7, 8):
            ancho, alto = alto, ancho
        datos = {"ancho": ancho, "alto": alto, "fecha": fecha_exif(exif),
                 "camara": bool(camara_exif(exif)),
                 "animado": bool(getattr(im, "is_animated", False)) and im.format != "MPO"}
        if con_hash:
            im.draft("RGB", (128, 128))   # JPEG: decodifica ya reducida
            imagen = im.copy() if orientacion in (None, 1) else ImageOps.exif_transpose(im)
            datos["dhash"] = dhash_imagen(imagen)
    return datos


def _indice_galeria(carpeta: Path) -> dict:
    """{src: elemento} de galeria.json (vacío si no hay o es de otra versión)."""
    try:
        datos = json.loads((carpeta / "galeria.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(datos, dict) or datos.get("version") != VERSION_INDICE:
        return {}
    return {e["src"]: e for e in datos.get("elementos", []) if isinstance(e, dict) and "src" in e}


def leer_elemento(ruta: Path, carpeta: Path, lado: str, fila=None, previo: dict = None,
                  hay_ffmpeg: bool = True, max_lado: int = MAX_LADO) -> Elemento:
    """Elemento de un archivo, con lo que ya saben su catálogo (`fila`) y su galería
    (`previo`, si el archivo no ha cambiado); solo lee el archivo para lo que falte."""
    st = ruta.stat()
    rel = ruta.relative_to(carpeta).as_posix()
    tipo = "video" if ruta.suffix.lower() in EXTENSIONES_VIDEO else "foto"
    e = Elemento(lado, tipo, ruta, rel, st=st, bytes=st.st_size)
    fila = dict(fila) if fila else {}
    origen = fila.get("origen") or ""
    e.hash_original = fila.get("hash")
    e.nombre_original = normalizar_nombre(Path(origen).stem if origen else ruta.stem)
    e.fecha, e.fuente = _fecha_iso(fila.get("fecha")), fila.get("fuente_fecha") or ""
    if not e.fecha:
        e.fuente = ""

    if (previo and previo.get("tipo") == tipo and previo.get("bytes") == st.st_size
            and previo.get("mtime") == int(st.st_mtime)):
        e.ancho, e.alto = int(previo.get("ancho") or 0), int(previo.get("alto") or 0)
        # El del catálogo sale del original, como el de otra biblioteca: se parecen más
        # entre sí que con el de la galería, que sale de la miniatura
        e.dhash = fila.get("phash") or previo.get("dhash")
        e.duracion = float(previo.get("duracion") or 0)
        e.camara = bool(previo.get("camara"))
        e.whatsapp = previo.get("ambito") == "whatsapp"
        if e.fecha is None:
            e.fecha = _fecha_iso(previo.get("fecha"))
            e.fuente = previo.get("fuente_fecha") or ""
        if lado == "c" and tipo == "foto" and ruta.suffix.lower() in (".gif", ".webp"):
            e.animado = _leer_foto(ruta, con_hash=False)["animado"]
    elif tipo == "foto":
        datos = _leer_foto(ruta, con_hash=not fila.get("phash"))
        e.ancho, e.alto, e.camara, e.animado = datos["ancho"], datos["alto"], datos["camara"], \
            datos["animado"]
        e.dhash = fila.get("phash") or datos.get("dhash")
        if e.fecha is None and datos["fecha"]:
            e.fecha, e.fuente = datos["fecha"], "exif"
    else:
        info = (sondear(ruta) if hay_ffmpeg else None) or {}
        e.ancho, e.alto = info.get("ancho", 0), info.get("alto", 0)
        e.duracion, e.camara = info.get("duracion", 0.0), bool(info.get("camara"))
        if e.fecha is None:
            e.fecha, e.fuente = fecha_video(ruta, info)
    if e.fecha is None:
        fecha = fecha_desde_nombre(ruta.stem)
        e.fecha, e.fuente = (fecha, "nombre") if fecha else (fecha_mtime(ruta), "archivo")

    if tipo == "foto" and e.fuente == "exif":
        e.camara = True
    final_origen = PurePath(*Path(origen).parts[-4:]) if origen else None
    e.whatsapp = e.whatsapp or es_whatsapp(rel) or bool(final_origen and es_whatsapp(final_origen))
    e.sent = bool(_RE_SENT.search(rel) or _RE_SENT.search(origen))

    if lado == "c":
        e.categoria = categoria(PurePath(rel), e.ancho, e.alto)
        if not e.categoria and final_origen:
            e.categoria = categoria(final_origen, e.ancho, e.alto)
        if e.categoria == "" and e.whatsapp:
            e.categoria = "whatsapp"
        if _RE_NOMBRE_BIBLIOTECA.match(ruta.stem):    # ya tiene el nombre de una biblioteca
            e.base = _RE_SUFIJO_RAFAGA.sub(r"\1", ruta.stem)
        else:
            e.fecha, e.fuente, e.base = fecha_y_nombre(ruta, e.fecha, e.fuente)
        ext = ruta.suffix.lower()
        if tipo == "foto":
            grande = bool(max_lado and max(e.ancho, e.alto) > max_lado)
            e.convertir = ext not in FOTO_GALERIA or (
                grande and not e.animado and e.categoria != "pegatina")
        else:
            e.convertir = ext not in VIDEO_GALERIA
    return e


def _leer_papelera(biblioteca: Path) -> tuple:
    """(elementos de la papelera de la biblioteca, hashes de `descartadas`), sin escribir."""
    ruta = ruta_catalogo(biblioteca)
    if not ruta.exists():
        return [], set()
    try:
        db = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True, timeout=ESPERA_BLOQUEO)
        try:
            tablas = {f[0] for f in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            descartadas = ({f[0] for f in db.execute("SELECT hash FROM descartadas")}
                           if "descartadas" in tablas else set())
            filas = (db.execute("SELECT src, en_papelera, elemento, hash FROM papelera").fetchall()
                     if "papelera" in tablas else [])
        finally:
            db.close()
    except sqlite3.Error:
        return [], set()
    from limpieza import CARPETA_PAPELERA
    elementos = []
    for src, en_papelera, elemento, digest in filas:
        try:
            datos = json.loads(elemento) if elemento else {}
        except ValueError:
            continue
        fecha = _fecha_iso(datos.get("fecha")) if isinstance(datos, dict) else None
        if not fecha or datos.get("tipo") not in ("foto", "video"):
            continue
        elementos.append(Elemento(
            "p", datos["tipo"], biblioteca / CARPETA_INTERNA / CARPETA_PAPELERA / en_papelera, src,
            fecha=fecha, fuente=datos.get("fuente_fecha") or "",
            ancho=int(datos.get("ancho") or 0), alto=int(datos.get("alto") or 0),
            bytes=int(datos.get("bytes") or 0), dhash=datos.get("dhash"),
            duracion=float(datos.get("duracion") or 0), hash_original=digest,
            nombre_original=normalizar_nombre(Path(datos.get("nombre_original") or src).stem)))
    return elementos, descartadas


def _leer_todos(rutas, carpeta, lado, filas, indice, pool, hay_ffmpeg, max_lado, nombre) -> tuple:
    """(elementos, [(ruta, error)]) de muchos archivos en paralelo, con progreso."""
    def leer(ruta):
        rel = ruta.relative_to(carpeta).as_posix()
        try:
            return leer_elemento(ruta, carpeta, lado, filas.get(rel), indice.get(rel),
                                 hay_ffmpeg, max_lado), None
        except Exception as exc:
            return ruta, exc

    print(f"Leyendo {nombre}: {len(rutas)} archivo(s)…")
    elementos, errores = [], []
    for n, (resultado, error) in enumerate(pool.map(leer, rutas), 1):
        if error is None:
            elementos.append(resultado)
        else:
            errores.append((resultado, error))
        if n % 5000 == 0:
            imprimir(f"  … {n}/{len(rutas)}")
        if n % 100 == 0 or n == len(rutas):
            progreso("avance", "fusionar", paso=f"Leyendo {nombre}", hecho=n, total=len(rutas),
                     archivo=Path(ruta_de(resultado)).name)
    return elementos, errores


def ruta_de(resultado) -> Path:
    return resultado.ruta if isinstance(resultado, Elemento) else resultado


def _precalcular_fotogramas(coleccion: list, biblioteca: list, margen: int, pool):
    """Fotogramas de los vídeos que hay que comparar, en paralelo (FFmpeg tarda)."""
    indice = Indice(margen)
    for e in biblioteca:
        if e.tipo == "video":
            indice.anadir(e)
    tareas = {}
    for c in coleccion:
        if c.tipo != "video" or c.accion:
            continue
        for e in indice.candidatos(c):
            if (_duraciones_compatibles(c.duracion, e.duracion)
                    and _proporciones_compatibles(c.proporcion, e.proporcion)):
                for t in _instantes(c, e):
                    tareas[(id(c), t)] = (c, t)
                    tareas[(id(e), t)] = (e, t)
    if tareas:
        print(f"Comparando fotogramas de vídeo ({len(tareas)})…")
        for n, _ in enumerate(pool.map(lambda par: _marco(*par), tareas.values()), 1):
            if n % 10 == 0 or n == len(tareas):
                progreso("avance", "fusionar", paso="Comparando vídeos", hecho=n, total=len(tareas))


# ----------------------------- Escritura -----------------------------

def extension_final(c: Elemento) -> str:
    if c.convertir:
        return ".jpg" if c.tipo == "foto" else ".mp4"   # JPEG y H.264, como al importar
    return c.ruta.suffix.lower()


def _preparar(c: Elemento, biblioteca: Path, opciones: OpcionesFusion) -> str:
    """En un hilo: deja la copia (o la conversión) en `c.tmp`, junto a su destino, para
    colocarla después de una vez (ver `_colocar`). 'COPIADA' | 'CONVERTIDA'."""
    destino = biblioteca / c.destino_rel
    destino.parent.mkdir(parents=True, exist_ok=True)
    c.tmp = ruta_temporal(destino)
    try:
        if c.convertir and c.tipo == "foto":
            guardar_optimizada(c.ruta, c.tmp, OpcionesFotos(max_lado=opciones.max_lado,
                                                            calidad=opciones.calidad))
            modo = "CONVERTIDA"
        elif c.convertir:
            ok, error = ejecutar_ffmpeg(comando_codificacion(c.ruta, c.tmp, OpcionesVideos()),
                                        c.duracion)
            if not ok or not c.tmp.exists() or c.tmp.stat().st_size == 0:
                raise RuntimeError((error or "FFmpeg no generó salida").splitlines()[-1][:300])
            modo = "CONVERTIDA"
        else:
            shutil.copy2(c.ruta, c.tmp)   # sin recomprimir: no pierde calidad
            modo = "COPIADA"
        marca = c.fecha.timestamp()       # como al importar: fecha del archivo = de captura
        os.utime(c.tmp, (marca, marca))
        if c.clave is None:
            c.clave = _md5(c) or hash_archivo(c.ruta)
    except BaseException:
        c.tmp.unlink(missing_ok=True)
        raise
    return modo


def _colocar(c: Elemento, biblioteca: Path, limpieza, decision: str, catalogo: Catalogo,
             galeria_bib: dict) -> tuple:
    """En el hilo principal: pone `c` en su sitio y manda la peor copia a la papelera.

    Si la nueva va al mismo sitio que la peor (misma carpeta y extensión: conserva el
    nombre, los favoritos y el enlace), la peor se aparta antes como «…_sustituida» y
    así va a la papelera (y vuelve con ese nombre si se restaura).
    Devuelve (ruta en la biblioteca de lo que ha ido a la papelera o None, bytes).
    """
    destino = biblioteca / c.destino_rel
    vieja = c.sustituye
    if vieja is not None and vieja.rel == c.destino_rel:
        apartada = nombre_libre(destino.parent, f"{destino.stem}_sustituida", destino.suffix)
        apartada_rel = apartada.relative_to(biblioteca).as_posix()
        os.replace(destino, apartada)
        catalogo.cambiar_destino(vieja.rel, apartada_rel)
        elemento = dict(galeria_bib.get(vieja.rel) or {}) or None
        if elemento:   # su miniatura es la de esa ruta: la nueva la regenera al restaurar
            elemento.update(src=apartada_rel, nombre=apartada.stem, thumb="")
        try:
            liberado = limpieza.mover_a_papelera(apartada_rel, decision, elemento)
        except BaseException:
            os.replace(apartada, destino)
            catalogo.cambiar_destino(apartada_rel, vieja.rel)
            raise
        try:
            os.replace(c.tmp, destino)
        except OSError:
            limpieza.restaurar([apartada_rel])   # que no falten las dos
            raise
        return apartada_rel, liberado
    os.replace(c.tmp, destino)
    if vieja is None:
        return None, 0
    try:
        return vieja.rel, limpieza.mover_a_papelera(vieja.rel, decision, galeria_bib.get(vieja.rel))
    except (OSError, ValueError) as exc:   # la nueva ya está: solo queda la peor de más
        c.aviso = f"{vieja.rel} no se ha podido mover a la papelera: {exc}"
        return None, 0


def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _escribir_json(ruta: Path, datos, **kwargs):
    tmp = ruta.with_name(ruta.name + ".part")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, **kwargs), encoding="utf-8")
    os.replace(tmp, ruta)


def _pasar_favoritos(biblioteca: Path, cambios: dict):
    """La que entra en lugar de una favorita también es favorita."""
    ruta = biblioteca / CARPETA_GALERIA / "favoritos.json"
    favoritos = _leer_json(ruta, [])
    if not isinstance(favoritos, list) or not any(f in cambios for f in favoritos):
        return
    _escribir_json(ruta, sorted({cambios.get(f, f) for f in favoritos}), indent=1)


def _quitar_de_galeria(biblioteca: Path, movidas: list):
    """Sin regenerar la galería: al menos que no muestre lo que ya está en la papelera."""
    from galeria import _escribir, actualizar_parecidas
    ruta = biblioteca / "galeria.json"
    datos = _leer_json(ruta, None)
    if not isinstance(datos, dict) or not isinstance(datos.get("elementos"), list):
        return
    movidas = set(movidas)
    numeros = {e.get("parecidas") for e in datos["elementos"]
               if isinstance(e, dict) and e.get("src") in movidas}
    datos["elementos"] = [e for e in datos["elementos"]
                          if not isinstance(e, dict) or e.get("src") not in movidas]
    actualizar_parecidas(datos["elementos"], numeros)
    _escribir(ruta, json.dumps(datos, ensure_ascii=False, separators=(",", ":")))


# ----------------------------- Fusión -----------------------------

# acción -> (en el informe CSV, en la consola)
ETIQUETAS = {
    "anadir": ("ANADIDA", "AÑADIR"), "sustituir": ("SUSTITUYE", "SUSTITUIR"),
    "ya_esta": ("YA_ESTA", "YA ESTÁ"), "repetida": ("REPETIDA", "REPETIDA"),
    "quitada": ("QUITADA_ANTES", "QUITADA"), "error": ("ERROR", "ERROR"),
}


def _referencia(c: Elemento):
    """La copia que se queda en lugar de `c` (siguiendo las repetidas de la colección)."""
    r = c.pareja
    while r is not None and r.lado == "c" and r.accion == "repetida":
        r = r.pareja
    if r is None:
        return None
    return r.destino_rel if r.lado == "c" else r.rel


def _detalle(c: Elemento) -> str:
    if c.accion == "anadir":
        partes = []
        if c.convertir:
            partes.append("se reduce" if c.ruta.suffix.lower() in
                          (FOTO_GALERIA | VIDEO_GALERIA) else "se convierte")
        if c.parecida:
            otra, bits = c.parecida
            partes.append(f"parecida a {otra.rel if otra.lado != 'c' else otra.destino_rel} "
                          f"({bits} bits), pero no igual")
        return "; ".join(partes)
    if c.accion == "sustituir":
        return (f"mejor que {c.sustituye.rel} ({c.motivo}; {c.como}), "
                "que va a la papelera")
    if c.accion in ("ya_esta", "repetida"):
        donde = "la de la biblioteca" if c.accion == "ya_esta" else "la otra de la colección"
        if c.motivo == "copias equivalentes":
            return f"igual que {c.pareja.rel} ({c.como}); son equivalentes: se queda {donde}"
        return f"igual que {c.pareja.rel} ({c.como}); es mejor {donde}: {c.motivo}"
    return c.motivo


def nuevas_estadisticas() -> dict:
    return {"fotos": 0, "videos": 0, "anadidas": 0, "sustituidas": 0, "ya_estaban": 0,
            "repetidas": 0, "quitadas": 0, "ya_fusionadas": 0, "ya_comparadas": 0,
            "parecidas": 0, "convertidas": 0, "errores": 0, "omitidos": 0,
            "bytes_anadidos": 0, "bytes_papelera": 0}


def fusionar(coleccion: Path, biblioteca: Path, simular: bool = False,
             opciones: OpcionesFusion = None) -> dict:
    """Añade a `biblioteca` lo de `coleccion` que no tiene (ver el docstring del módulo)."""
    opciones = opciones or OpcionesFusion()
    coleccion, biblioteca = Path(coleccion).resolve(), Path(biblioteca).resolve()
    stats = nuevas_estadisticas()
    hay_ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    hilos = opciones.hilos or min(8, os.cpu_count() or 2)

    archivos = listar_archivos(coleccion, EXTENSIONES_FOTO | EXTENSIONES_VIDEO)
    if not archivos:
        print(f"No se encontraron fotos ni vídeos en {coleccion}")
        return stats
    if not HEIF_DISPONIBLE:
        heif = [a for a in archivos if a.suffix.lower() in EXTENSIONES_HEIF]
        if heif:
            print(f"AVISO: se omiten {len(heif)} foto(s) HEIC/HEIF. "
                  "Para incluirlas:  pip install pillow-heif")
            archivos = [a for a in archivos if a.suffix.lower() not in EXTENSIONES_HEIF]
            stats["omitidos"] += len(heif)
    if not hay_ffmpeg:
        videos = [a for a in archivos if a.suffix.lower() in EXTENSIONES_VIDEO]
        if videos:
            print(f"AVISO: se omiten {len(videos)} vídeo(s): para compararlos hace falta FFmpeg "
                  "(winget install Gyan.FFmpeg).")
            archivos = [a for a in archivos if a.suffix.lower() not in EXTENSIONES_VIDEO]
            stats["omitidos"] += len(videos)

    print(f"\n{'SIMULACIÓN' if simular else 'FUSIONANDO'} — {len(archivos)} archivo(s) de "
          f"{coleccion}\n  en {biblioteca}\n  se compara por días (±{opciones.margen_dias}); "
          f"fotos iguales a ≤ {opciones.umbral} bits — {hilos} hilo(s)\n")

    with Catalogo(biblioteca, simular) as catalogo, Catalogo(coleccion, simular=True) as cat_col, \
            Informe(biblioteca, "fusion", simular) as informe, ThreadPoolExecutor(hilos) as pool:
        if simular:   # el plan, para revisarlo en Excel, fuera de la biblioteca
            marca = datetime.now().strftime("%Y%m%d_%H%M%S")
            informe.ruta = Path(tempfile.gettempdir()) / f"exportador_fusion_simulacion_{marca}.csv"
        try:
            # Lo ya fusionado (o comparado) en otra ejecución no se vuelve a leer
            pendientes = []
            for ruta in archivos:
                st = ruta.stat()
                if catalogo.buscar_por_origen(ruta, st) is not None:
                    stats["ya_fusionadas"] += 1
                    continue
                descarte = catalogo.buscar_descarte(ruta, st)
                if (descarte is not None and descarte["motivo"] == MOTIVO_DESCARTE
                        and descarte["referencia"] and (biblioteca / descarte["referencia"]).exists()):
                    stats["ya_comparadas"] += 1
                    continue
                pendientes.append(ruta)
            if not pendientes:
                print("Nada nuevo: todo lo de la colección se fusionó o comparó antes.")
                _imprimir_resumen(stats, simular, None)
                return stats

            filas_bib = catalogo.filas()
            hashes_bib = {f["hash"] for f in filas_bib}
            galeria_bib = _indice_galeria(biblioteca)
            bib, errores_bib = _leer_todos(
                listar_archivos(biblioteca, EXTENSIONES_FOTO | EXTENSIONES_VIDEO), biblioteca, "b",
                {f["destino"]: f for f in filas_bib}, galeria_bib, pool, hay_ffmpeg,
                opciones.max_lado, "la biblioteca")
            if errores_bib:
                print(f"AVISO: {len(errores_bib)} archivo(s) de la biblioteca no se pueden leer "
                      "(no se comparan con ellos).")
            col, errores_col = _leer_todos(
                pendientes, coleccion, "c", {f["destino"]: f for f in cat_col.filas()},
                _indice_galeria(coleccion), pool, hay_ffmpeg, opciones.max_lado, "la colección")
            for ruta, error in errores_col:
                e = Elemento("c", "video" if ruta.suffix.lower() in EXTENSIONES_VIDEO else "foto",
                             ruta, ruta.relative_to(coleccion).as_posix())
                e.accion, e.motivo = "error", f"no se puede leer: {error}"
                col.append(e)
            papelera, descartadas = _leer_papelera(biblioteca)

            if any(c.tipo == "video" for c in col):
                _precalcular_fotogramas(col, bib, opciones.margen_dias, pool)
            planificar(col, bib, papelera, descartadas, opciones)

            # Nombres en la biblioteca, en orden cronológico (ráfagas -> _01, _02...)
            pegatinas_aparte = (biblioteca / CARPETA_WHATSAPP / CARPETA_PEGATINAS).is_dir()
            col.sort(key=lambda e: (e.fecha or datetime.min, e.rel))
            reservados = set()
            for c in col:
                if c.accion not in ("anadir", "sustituir"):
                    continue
                aparte = pegatinas_aparte or f"/{CARPETA_PEGATINAS}/" in f"/{c.rel}"
                carpeta_rel = carpeta_destino(c.fecha, c.categoria, c.tipo, aparte)
                ext = extension_final(c)
                vieja = PurePath(c.sustituye.rel) if c.sustituye is not None else None
                if vieja is not None and (vieja.parent.as_posix(), vieja.suffix.lower()) == \
                        (carpeta_rel, ext):
                    c.destino_rel = c.sustituye.rel   # ocupa el sitio de la peor (mismo nombre)
                else:
                    destino = nombre_libre(biblioteca / carpeta_rel, c.base, ext, reservados)
                    c.destino_rel = destino.relative_to(biblioteca).as_posix()
                c.clave = (c.hash_original if c.hash_original and c.hash_original not in hashes_bib
                           else None)

            # Lo que no entra: al informe (y al catálogo, para no volver a compararlo)
            escribir = []
            for c in col:
                stats["fotos" if c.tipo == "foto" else "videos"] += 1
                etiqueta, texto = ETIQUETAS[c.accion]
                detalle = _detalle(c)
                if c.accion in ("anadir", "sustituir"):
                    if simular:
                        imprimir(f"  {texto:<10} {c.rel}  ->  {c.destino_rel}"
                                 + (f"  ({detalle})" if detalle else ""))
                        informe.anotar(etiqueta, c.ruta, c.destino_rel, c.fecha, c.fuente,
                                       c.bytes, "", detalle, _referencia(c) or "")
                        _contar(stats, c)
                    else:
                        escribir.append(c)
                    continue
                imprimir(f"  {texto:<10} {c.rel}  ({detalle})")
                informe.anotar(etiqueta, c.ruta, "", c.fecha, c.fuente, c.bytes, "", detalle,
                               _referencia(c) or "")
                if c.accion == "error":
                    stats["errores"] += 1
                    continue
                stats[{"ya_esta": "ya_estaban", "repetida": "repetidas",
                       "quitada": "quitadas"}[c.accion]] += 1
                catalogo.descartar(c.ruta, c.st.st_size, c.st.st_mtime_ns, c.tipo,
                                   MOTIVO_DESCARTE, detalle=detalle, referencia=_referencia(c))

            if not simular and escribir:
                _ejecutar(escribir, biblioteca, opciones, catalogo, informe, pool, hashes_bib,
                          galeria_bib, stats)
        except KeyboardInterrupt:
            pool.shutdown(wait=True, cancel_futures=True)
            imprimir("\nInterrumpido. Lo ya terminado queda registrado; "
                     "vuelve a ejecutar para continuar.")
            raise

    _imprimir_resumen(stats, simular, informe.ruta if informe.filas else None)
    if informe.filas:   # el panel ofrece abrir su carpeta
        stats["informe"] = str(informe.ruta)
    return stats


def _contar(stats: dict, c: Elemento, despues: int = None):
    stats["anadidas" if c.accion == "anadir" else "sustituidas"] += 1
    stats["convertidas"] += c.convertir
    stats["parecidas"] += bool(c.parecida)
    stats["bytes_anadidos"] += c.bytes if despues is None else despues


def _ejecutar(escribir, biblioteca, opciones, catalogo, informe, pool, hashes_bib, galeria_bib,
              stats):
    """Copia o convierte lo que entra; lo sustituido va a la papelera. Al final, galería."""
    from limpieza import Limpieza
    limpieza = Limpieza(biblioteca)
    decision = f"fusion-{os.urandom(4).hex()}"
    cambios_favoritos, movidas = {}, []
    pool_videos = ThreadPoolExecutor(1)   # convertir vídeos: uno a uno (FFmpeg ya usa la CPU)
    try:
        futuros = {}
        for c in escribir:
            ejecutor = pool_videos if (c.tipo == "video" and c.convertir) else pool
            futuros[ejecutor.submit(_preparar, c, biblioteca, opciones)] = c
        progreso("avance", "fusionar", paso="Copiando a la biblioteca", hecho=0, total=len(futuros))
        for n, futuro in enumerate(as_completed(futuros), 1):
            c = futuros[futuro]
            prefijo = f"  [{n}/{len(futuros)}]"
            progreso("avance", "fusionar", paso="Copiando a la biblioteca", hecho=n,
                     total=len(futuros), archivo=c.rel)
            detalle = _detalle(c)
            try:
                modo = futuro.result()
                movida, liberado = _colocar(c, biblioteca, limpieza, decision, catalogo,
                                            galeria_bib)
            except Exception as exc:
                if c.tmp:
                    c.tmp.unlink(missing_ok=True)
                imprimir(f"{prefijo} ERROR  {c.rel}: {exc}")
                informe.anotar("ERROR", c.ruta, c.destino_rel, detalle=str(exc))
                stats["errores"] += 1
                continue
            final = biblioteca / c.destino_rel
            despues = final.stat().st_size
            catalogo.registrar(
                hash=c.clave, tipo=c.tipo, origen=str(c.ruta), tamano=c.st.st_size,
                mtime_ns=c.st.st_mtime_ns, destino=c.destino_rel, original=None,
                fecha=c.fecha.isoformat(), fuente_fecha=c.fuente, bytes_antes=c.bytes,
                bytes_despues=despues, phash=c.dhash if c.tipo == "foto" else None,
                ancho=c.ancho or None, alto=c.alto or None)
            hashes_bib.add(c.clave)
            if c.aviso:
                detalle = f"{detalle}; AVISO: {c.aviso}"
            if movida:
                stats["bytes_papelera"] += liberado
                if movida == c.sustituye.rel:   # en otro sitio: la galería y los favoritos cambian
                    movidas.append(movida)
                    cambios_favoritos[movida] = c.destino_rel
            etiqueta, texto = ETIQUETAS[c.accion]
            imprimir(f"{prefijo} {texto:<10} {c.rel}  ->  {c.destino_rel}"
                     + (f"  ({detalle})" if detalle else ""))
            informe.anotar(etiqueta, c.ruta, c.destino_rel, c.fecha, c.fuente, c.bytes, despues,
                           f"{detalle}; {modo.lower()}" if detalle else modo.lower(),
                           _referencia(c) or "")
            _contar(stats, c, despues)
    except KeyboardInterrupt:
        pool_videos.shutdown(wait=False, cancel_futures=True)
        pool.shutdown(wait=False, cancel_futures=True)
        detener_ffmpeg()
        raise
    finally:
        pool_videos.shutdown(wait=True)
        pool.shutdown(wait=True)
        for c in escribir:   # copias preparadas que no se llegaron a colocar
            if c.tmp is not None:
                c.tmp.unlink(missing_ok=True)
        if cambios_favoritos:
            _pasar_favoritos(biblioteca, cambios_favoritos)

    hubo_cambios = stats["anadidas"] or stats["sustituidas"]
    if (biblioteca / "galeria.json").exists() and hubo_cambios:
        if opciones.galeria:
            print()
            from galeria import generar_galeria
            progreso("fin", "fusionar", resumen=stats)   # en el panel, la galería va aparte
            progreso("inicio", "galeria")
            generar_galeria(biblioteca)
            progreso("fin", "galeria")
        elif movidas:
            _quitar_de_galeria(biblioteca, movidas)
    elif hubo_cambios and opciones.galeria:
        print("\nPara ver la biblioteca en la galería:  python main.py galeria "
              f"\"{biblioteca}\" --servir")


def _imprimir_resumen(stats: dict, simular: bool, informe):
    a = "a añadir" if simular else "añadidas"
    filas = [
        ("Fotos de la colección", stats["fotos"]),
        ("Vídeos de la colección", stats["videos"]),
        (f"Nuevas ({a})", stats["anadidas"]),
        ("Mejores (sustituyen a otra)", stats["sustituidas"]),
        ("  de ellas convertidas/reducidas", stats["convertidas"]),
        ("  parecidas a otra, no iguales", stats["parecidas"]),
        ("Ya estaban (igual o mejor)", stats["ya_estaban"]),
        ("Repetidas en la colección", stats["repetidas"]),
        ("Quitadas antes a mano", stats["quitadas"]),
        ("Ya fusionadas antes", stats["ya_fusionadas"]),
        ("Ya comparadas antes", stats["ya_comparadas"]),
        ("Omitidos", stats["omitidos"]),
        ("Errores", stats["errores"]),
    ]
    print("\n----------- RESUMEN -----------")
    for etiqueta, valor in filas:
        if valor or etiqueta in ("Errores", f"Nuevas ({a})"):
            print(f"{etiqueta:<32}: {valor}")
    if stats["bytes_anadidos"]:
        print(f"{'Espacio añadido' if not simular else 'Espacio a añadir (aprox.)':<32}: "
              f"{formato_bytes(stats['bytes_anadidos'])}")
    if stats["bytes_papelera"]:
        print(f"{'A la papelera (restaurable)':<32}: {formato_bytes(stats['bytes_papelera'])}")
    if stats["parecidas"]:
        print("Las parecidas son otras tomas (ráfagas) o fotos editadas: se han añadido; "
              "revísalas en «Limpiar repetidas» de la galería.")
    if informe:
        print(f"{'Informe CSV':<32}: {informe}")
