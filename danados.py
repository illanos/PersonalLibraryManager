"""Archivos dañados: vacíos, sin cabecera válida o truncados.

No se importan (no hay nada aprovechable) y se listan en un CSV aparte,
`.exportador/informes/danados_<tipo>_<fecha>.csv`, con un resumen final por carpeta.
Quedan anotados en el catálogo (tabla `descartes`): mientras no cambien, la siguiente
ejecución no los vuelve a leer, pero los sigue listando (columna «ya_conocido»).
"""

import csv
import threading
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from media_utils import CARPETA_INTERNA, imprimir

VACIO, SIN_CABECERA, TRUNCADO, ILEGIBLE = "vacío", "sin cabecera válida", "truncado", "ilegible"



def _ftyp(cab: bytes) -> bool:
    return cab[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot")


def _mp3(cab: bytes) -> bool:
    return cab.startswith(b"ID3") or (len(cab) > 1 and cab[0] == 0xFF and cab[1] & 0xE0 == 0xE0)


def _aac(cab: bytes) -> bool:
    return cab.startswith((b"ADIF", b"ID3")) or (
        len(cab) > 1 and cab[0] == 0xFF and cab[1] & 0xF6 == 0xF0)


def _ts(cab: bytes) -> bool:
    return cab[:1] == b"\x47" or cab[4:5] == b"\x47"


FIRMAS = {
    ".jpg": lambda c: c.startswith(b"\xff\xd8\xff"),
    ".png": lambda c: c.startswith(b"\x89PNG\r\n\x1a\n"),
    ".gif": lambda c: c.startswith((b"GIF87a", b"GIF89a")),
    ".webp": lambda c: c[:4] == b"RIFF" and c[8:12] == b"WEBP",
    ".bmp": lambda c: c.startswith(b"BM"),
    ".tif": lambda c: c.startswith((b"II*\x00", b"MM\x00*")),
    ".heic": _ftyp, ".avif": _ftyp,
    ".mp4": _ftyp, ".mov": _ftyp, ".m4v": _ftyp, ".3gp": _ftyp, ".m4a": _ftyp,
    ".mkv": lambda c: c.startswith(b"\x1a\x45\xdf\xa3"),
    ".avi": lambda c: c[:4] == b"RIFF" and c[8:11] == b"AVI",
    ".wmv": lambda c: c.startswith(b"\x30\x26\xb2\x75"),
    ".flv": lambda c: c.startswith(b"FLV"),
    ".mpg": lambda c: c.startswith((b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3")),
    ".mts": _ts,
    ".opus": lambda c: c.startswith(b"OggS"), ".ogg": lambda c: c.startswith(b"OggS"),
    ".mp3": _mp3, ".aac": _aac,
    ".wav": lambda c: c[:4] == b"RIFF" and c[8:12] == b"WAVE",
}
SINONIMOS = {".jpeg": ".jpg", ".tiff": ".tif", ".heif": ".heic", ".webm": ".mkv",
             ".mpeg": ".mpg", ".m2ts": ".mts"}
COLA = 64 * 1024


def firma_valida(ruta: Path, cabecera: bytes) -> bool:
    ext = ruta.suffix.lower()
    comprobar = FIRMAS.get(SINONIMOS.get(ext, ext))
    return comprobar is None or comprobar(cabecera)


def _parece_truncada(ruta: Path, tamano: int) -> bool:
    """Comprobación barata: un JPEG termina en FFD9 y un PNG en IEND."""
    ext = SINONIMOS.get(ruta.suffix.lower(), ruta.suffix.lower())
    if ext not in (".jpg", ".png"):
        return False
    with open(ruta, "rb") as f:
        f.seek(max(0, tamano - COLA))
        cola = f.read()
    if ext == ".jpg":
        return b"\xff\xd9" not in cola
    return b"IEND" not in cola[-16:]


def _decodifica(ruta: Path):
    """None si Pillow puede decodificar la imagen entera; si no, el error."""
    from PIL import Image
    try:
        with Image.open(ruta) as im:
            im.load()
    except Exception as exc:
        return str(exc) or exc.__class__.__name__
    return None


def diagnosticar(ruta: Path, tamano: int, imagen: bool = False):
    """(problema, detalle) si el archivo está dañado; None si parece sano.

    Lee solo la cabecera y, en JPEG/PNG, el final del archivo; únicamente si el final
    no es el esperado decodifica la imagen entera para confirmarlo (hay JPEG válidos
    con datos añadidos tras el final).
    """
    if tamano == 0:
        return VACIO, "0 bytes"
    with open(ruta, "rb") as f:
        cabecera = f.read(16)
    if cabecera.strip(b"\x00") == b"":
        return VACIO, "solo ceros"
    if not firma_valida(ruta, cabecera):
        return SIN_CABECERA, f"empieza por {cabecera[:8].hex(' ')}"
    if imagen and _parece_truncada(ruta, tamano):
        error = _decodifica(ruta)
        if error:
            return TRUNCADO, error
    return None


def problema_de_excepcion(exc: BaseException):
    """Clasifica un error de lectura/decodificación de Pillow o FFmpeg, o None."""
    texto = str(exc).lower()
    if "truncat" in texto or "broken data stream" in texto or "moov atom not found" in texto \
            or "premature end" in texto or "end of file" in texto:
        return TRUNCADO
    if "cannot identify image file" in texto or "invalid data found" in texto:
        return ILEGIBLE
    return None


class RegistroDanados:
    """Acumula los dañados de una ejecución; CSV aparte y resumen por carpeta al final."""

    CAMPOS = ["origen", "carpeta", "problema", "detalle", "bytes", "ya_conocido"]

    def __init__(self, biblioteca: Path, origen: Path, tipo: str, simular: bool = False):
        self.biblioteca, self.origen, self.tipo, self.simular = biblioteca, origen, tipo, simular
        self.filas = []
        self.ruta = None
        self._lock = threading.Lock()

    def anotar(self, ruta: Path, problema: str, detalle: str = "", tamano: int = 0,
               conocido: bool = False):
        try:
            carpeta = ruta.parent.relative_to(self.origen).as_posix()
        except ValueError:
            carpeta = str(ruta.parent)
        with self._lock:
            self.filas.append([str(ruta), "." if carpeta == "" else carpeta, problema,
                               detalle, tamano, "sí" if conocido else ""])

    def __len__(self):
        return len(self.filas)

    def cerrar(self):
        """Escribe el CSV (si hay dañados y no es simulación) e imprime el resumen."""
        if not self.filas:
            return
        self.filas.sort(key=lambda f: (f[1], f[0]))
        if not self.simular:
            marca = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.ruta = (self.biblioteca / CARPETA_INTERNA / "informes"
                         / f"danados_{self.tipo}_{marca}.csv")
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ruta, "w", newline="", encoding="utf-8-sig") as f:
                escritor = csv.writer(f, delimiter=";")
                escritor.writerow(self.CAMPOS)
                escritor.writerows(self.filas)
        imprimir_resumen_danados(self.filas, self.ruta)


def imprimir_resumen_danados(filas: list, ruta_csv: Path = None):
    por_carpeta = defaultdict(Counter)
    for _, carpeta, problema, *_ in filas:
        por_carpeta[carpeta][problema] += 1
    imprimir(f"\n------ ARCHIVOS DAÑADOS ({len(filas)}) ------")
    for carpeta in sorted(por_carpeta, key=lambda c: (-sum(por_carpeta[c].values()), c)):
        cuenta = por_carpeta[carpeta]
        detalle = ", ".join(f"{n} {p}" for p, n in cuenta.most_common())
        imprimir(f"  {carpeta:<40} {sum(cuenta.values()):>5}  ({detalle})")
    if ruta_csv:
        imprimir(f"  Lista completa: {ruta_csv}")
    imprimir("  (no se importan; el origen no se ha tocado)")
