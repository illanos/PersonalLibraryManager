"""Importar las notas de Google Keep desde una exportación de Google Takeout.

Se lee el JSON de cada nota (el HTML dice lo mismo) y no se cambia nada del Takeout. Se conserva
todo lo que cabe en una nota: título, texto, listas con casillas, etiquetas (categorías), color,
fijada, archivada, papelera, fechas e imágenes y notas de voz; lo demás (enlaces, con quién se
compartió, si tenía recordatorio) va en sus `detalles`.

Las imágenes se reducen para verlas en pantalla (necesita Pillow; sin él se copian tal cual) y los
audios 3GP de Keep, que los navegadores no reproducen, pasan a M4A (necesita ffmpeg).

Cada nota se identifica por cuándo se creó, al microsegundo: repetir la importación solo añade
las que falten.
"""

import collections
import contextlib
import io
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import adjuntos as adj
from .cuaderno import HECHA, MAX_CATEGORIA, MAX_TITULO, PENDIENTE, Cuaderno, normalizar
from .errores import AdjuntoNoValido, ErrorNotas

FUENTE = "Google Keep"
LADO, CALIDAD = 1920, 80          # de sobra para verlas a pantalla completa
ARCHIVO_ETIQUETAS = "Labels.txt"
CAMPOS_KEEP = {"color", "isTrashed", "isPinned", "isArchived", "createdTimestampUsec"}
EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".avif"}
EXT_AUDIO = {".3gp", ".amr", ".aac", ".m4a", ".mp3", ".ogg", ".wav"}
# Keep tiene más colores que el cuaderno: el que no tiene pareja exacta se queda en sus detalles
COLORES_KEEP = {"DEFAULT": "", "RED": "coral", "ORANGE": "melocoton", "YELLOW": "limon",
                "GREEN": "menta", "TEAL": "menta", "BLUE": "cielo", "CERULEAN": "cielo",
                "PURPLE": "lavanda", "PINK": "rosa", "BROWN": "arena", "GRAY": "arena"}
COLORES_APROXIMADOS = {"TEAL", "CERULEAN", "GRAY"}
MARGEN_DIBUJO = timedelta(minutes=10)
IFD_EXIF, MAKER_NOTE = 0x8769, 0x927C      # lo que cada cámara apunta para sí: ocupa y no sirve fuera

# Los adjuntos se llaman como el momento en que se añadieron: milisegundos, en hexadecimal o no
_RE_MOMENTO = re.compile(r"(?:([0-9a-f]{11})|(\d{13}))\.[0-9a-f]+\.\w+")


@dataclass
class NotaKeep:
    """Una nota del Takeout, ya en el idioma del cuaderno."""
    origen: str
    datos: dict                                    # lo que recibe Cuaderno.importar
    archivos: list = field(default_factory=list)   # [(ruta, nombre para enseñar, creado)]

    @property
    def vacia(self) -> bool:
        d = self.datos
        return not (d["titulo"].strip() or d["texto"].strip() or self.archivos)


@dataclass
class Takeout:
    notas: list = field(default_factory=list)
    etiquetas: list = field(default_factory=list)
    avisos: list = field(default_factory=list)


@dataclass
class Resumen:
    """Qué ha pasado (o pasaría, al simular)."""
    importadas: int = 0
    repetidas: int = 0
    vacias: int = 0
    tipos: collections.Counter = field(default_factory=collections.Counter)
    bytes_origen: int = 0
    bytes_final: int = 0
    avisos: list = field(default_factory=list)


# --- leer el Takeout ---

def _momento(usec) -> datetime:
    return datetime.fromtimestamp(int(usec) / 1e6, timezone.utc)


def momento_adjunto(nombre: str):
    """Cuándo se añadió un adjunto, según el nombre que le pone Keep, o None si no lo dice."""
    m = _RE_MOMENTO.fullmatch(nombre)
    if not m:
        return None
    ms = int(m[1], 16) if m[1] else int(m[2])
    momento = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return momento if 2010 <= momento.year <= datetime.now().year + 1 else None


def _es_nota(datos) -> bool:
    return isinstance(datos, dict) and CAMPOS_KEEP <= set(datos)


def leer(carpeta: Path) -> Takeout:
    """Las notas de Keep que hay en `carpeta` (la del Takeout, o la de Keep dentro de él)."""
    carpeta = Path(carpeta)
    if carpeta.suffix.lower() == ".zip":
        raise ErrorNotas("Descomprime antes el ZIP del Takeout e indica la carpeta")
    if not carpeta.is_dir():
        raise ErrorNotas(f"No existe la carpeta {carpeta}")
    takeout, por_carpeta = Takeout(), collections.defaultdict(list)
    for ruta in sorted(carpeta.rglob("*.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            takeout.avisos.append(f"{ruta.name}: no se puede leer ({exc})")
            continue
        if _es_nota(datos):
            por_carpeta[ruta.parent].append((ruta, datos))
    if not por_carpeta:
        raise ErrorNotas(f"No hay notas de Google Keep en {carpeta}")
    for donde, notas in por_carpeta.items():
        _leer_carpeta(takeout, donde, notas)
    return takeout


def _leer_carpeta(takeout: Takeout, carpeta: Path, notas: list):
    archivos = {r.name: r for r in carpeta.iterdir()
                if r.suffix.lower() in EXT_IMAGEN | EXT_AUDIO}
    por_raiz = {r.stem: r for r in archivos.values()}
    usados, leidas = set(), []
    for ruta, datos in notas:
        nota = _convertir(ruta.name, datos)
        faltan = []
        for i, a in enumerate(datos.get("attachments") or [], 1):
            nombre = Path(a.get("filePath", "")).name
            # Keep a veces dice .jpeg y el archivo es .jpg
            archivo = archivos.get(nombre) or por_raiz.get(Path(nombre).stem)
            if archivo is None:
                faltan.append(nombre)
                continue
            usados.add(archivo.name)
            _poner_archivo(nota, archivo)
        if faltan:
            nota.datos["detalles"]["faltan"] = faltan
            takeout.avisos.append(f"{ruta.name}: no está en el Takeout {', '.join(faltan)}")
        leidas.append(nota)
    for archivo in sorted(set(archivos) - usados):
        leidas += _colocar_suelta(archivos[archivo], leidas)
    takeout.notas += leidas
    etiquetas = carpeta / ARCHIVO_ETIQUETAS
    if etiquetas.is_file():
        lineas = etiquetas.read_text(encoding="utf-8-sig").splitlines()
        takeout.etiquetas += [_etiqueta(l) for l in lineas if l.strip()]


def _poner_archivo(nota: NotaKeep, archivo: Path, que: str = ""):
    momento = momento_adjunto(archivo.name)
    creado = momento or nota.datos["creada"]
    if not que:
        que = ("Nota de voz" if archivo.suffix.lower() in EXT_AUDIO
               else "Imagen" if momento else "Dibujo")
    nombre = f"{que} {creado.astimezone():%Y-%m-%d %H.%M.%S}"
    repetidos = sum(n == nombre or n.startswith(nombre + " (") for _, n, _ in nota.archivos)
    nota.archivos.append((archivo, f"{nombre} ({repetidos + 1})" if repetidos else nombre, creado))


def _colocar_suelta(archivo: Path, notas: list) -> list:
    """Un archivo que no cita ninguna nota: casi siempre, la imagen sobre la que se dibujó.

    Al dibujar sobre una imagen, la nota se queda con el dibujo (cuyo nombre no es una fecha) y la
    original sigue en el Takeout sin dueño. Si no se sabe de quién es, va en una nota aparte.
    """
    momento = momento_adjunto(archivo.name)
    if momento:
        cerca = [(abs(n.datos["creada"] - momento), i) for i, n in enumerate(notas)
                 if any(momento_adjunto(r.name) is None for r, _, _ in n.archivos)]
        distancia, i = min(cerca, default=(None, None))
        if distancia is not None and distancia <= MARGEN_DIBUJO:
            _poner_archivo(notas[i], archivo, "Original sin dibujar")
            return []
    creada = momento or datetime.fromtimestamp(archivo.stat().st_mtime, timezone.utc)
    nota = NotaKeep(f"keep:{archivo.name}", {
        "titulo": "Archivo suelto de Google Keep", "texto": "", "creada": creada,
        "modificada": creada, "archivada": True, "detalles": {"fuente": FUENTE}})
    _poner_archivo(nota, archivo)
    return [nota]


def _etiqueta(nombre: str) -> str:
    return " ".join(nombre.split())[:MAX_CATEGORIA].strip()


def _linea_lista(item: dict) -> str:
    """Una casilla por línea; si el elemento tiene varias, las siguientes van sangradas."""
    texto = (item.get("text") or "").strip().replace("\r\n", "\n").replace("\n", "\n   ")
    return f"{HECHA if item.get('isChecked') else PENDIENTE} {texto}" if texto else ""


def _convertir(archivo: str, d: dict) -> NotaKeep:
    creada = _momento(d["createdTimestampUsec"])
    modificada = max(creada, _momento(d.get("userEditedTimestampUsec") or d["createdTimestampUsec"]))
    titulo = " ".join((d.get("title") or "").splitlines())
    lineas = [(d.get("textContent") or "").rstrip()]
    if len(titulo) > MAX_TITULO:                   # no se pierde: entero, al principio del texto
        lineas.insert(0, titulo)
        titulo = titulo[:MAX_TITULO - 1] + "…"
    lineas += [_linea_lista(x) for x in d.get("listContent") or []]
    color = d.get("color") or "DEFAULT"
    return NotaKeep(f"keep:{int(d['createdTimestampUsec'])}", {
        "titulo": titulo, "texto": "\n".join(l for l in lineas if l),
        "color": COLORES_KEEP.get(color, ""), "fijada": bool(d.get("isPinned")),
        "archivada": bool(d.get("isArchived")),
        "papelera": modificada if d.get("isTrashed") else None,
        "creada": creada, "modificada": modificada,
        "categorias": [_etiqueta(e["name"]) for e in d.get("labels") or []
                       if (e.get("name") or "").strip()],
        "detalles": _detalles(archivo, color, d)})


def _detalles(archivo: str, color: str, d: dict) -> dict:
    """Lo que trae la nota y no es texto. Solo lo que haya."""
    enlaces = {}
    for a in d.get("annotations") or []:
        url = a.get("url") or ""
        if re.match(r"https?://", url):
            enlaces.setdefault(url, {"url": url, "titulo": " ".join((a.get("title") or "").split()),
                                     "descripcion": " ".join((a.get("description") or "").split())})
    personas = [s for s in d.get("sharees") or [] if s.get("email")]
    detalles = {
        "fuente": FUENTE, "archivo": archivo, "enlaces": list(enlaces.values()),
        "compartida": [s["email"] for s in personas],
        "propietario": next((s["email"] for s in personas if s.get("isOwner")), ""),
        "recordatorio": bool(d.get("tasks") or d.get("reminders")),
        "color": color if color in COLORES_APROXIMADOS or color not in COLORES_KEEP else ""}
    return {clave: valor for clave, valor in detalles.items() if valor}


# --- preparar los adjuntos ---

def reducir_imagen(ruta: Path, lado: int = LADO, calidad: int = CALIDAD) -> bytes:
    """La imagen a tamaño de pantalla, o la original si ya ocupa menos o no hay Pillow.

    Se guarda ya girada y conserva la fecha, la cámara y el lugar de su EXIF.
    """
    original = ruta.read_bytes()
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return original
    try:
        with Image.open(io.BytesIO(original)) as abierta:
            if getattr(abierta, "is_animated", False):
                return original
            valida = abierta.format in ("JPEG", "PNG", "GIF", "WEBP", "BMP", "AVIF")
            im = ImageOps.exif_transpose(abierta)
            icc = abierta.info.get("icc_profile")
            exif = im.getexif()
            exif.get_ifd(IFD_EXIF).pop(MAKER_NOTE, None)
            im.thumbnail((lado, lado), Image.Resampling.LANCZOS)
            salida = io.BytesIO()
            if _transparente(im):
                im.convert("RGBA").save(salida, "PNG", optimize=True)
            else:
                im.convert("RGB").save(salida, "JPEG", quality=calidad, optimize=True,
                                       progressive=True, exif=exif.tobytes() if len(exif) else b"",
                                       icc_profile=icc)
    except Exception as exc:              # dañada o de un formato que Pillow no conoce
        raise AdjuntoNoValido(f"la imagen no se puede leer ({exc})") from exc
    reducida = salida.getvalue()
    return original if valida and len(original) <= len(reducida) else reducida


def _transparente(im) -> bool:
    if im.mode not in ("RGBA", "LA", "PA") and "transparency" not in im.info:
        return False
    return im.convert("RGBA").getchannel("A").getextrema()[0] < 255


def convertir_audio(ruta: Path) -> tuple:
    """(datos, extensión, segundos) de una nota de voz: tal cual, o en M4A si es 3GP o AMR."""
    datos, ext = ruta.read_bytes(), ruta.suffix.lower()
    with contextlib.suppress(AdjuntoNoValido):
        if ext not in (".3gp", ".amr"):
            adj.identificar(datos[:adj.BYTES_CABECERA], ruta.name)
            return datos, ext, _duracion(ruta)
    with tempfile.TemporaryDirectory() as tmp:
        salida = Path(tmp) / "voz.m4a"
        orden = ["ffmpeg", "-v", "error", "-y", "-i", str(ruta), "-vn", "-c:a", "aac", "-b:a", "64k",
                 "-ar", "16000", "-movflags", "+faststart", str(salida)]
        try:
            hecho = subprocess.run(orden, capture_output=True, timeout=300, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdjuntoNoValido(f"la nota de voz no se puede convertir ({exc})") from exc
        if hecho.returncode or not salida.is_file():
            raise AdjuntoNoValido("la nota de voz no se puede convertir")
        # La del original no vale: en AMR ffprobe la calcula a ojo, por lo que ocupa
        return salida.read_bytes(), ".m4a", _duracion(salida)


def _duracion(ruta: Path):
    orden = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)]
    try:
        hecho = subprocess.run(orden, capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        return float(hecho.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _hay_pillow() -> bool:
    try:
        import PIL.Image                                     # noqa: F401
        return True
    except ImportError:
        return False


# --- importar ---

def importar(carpeta_cuaderno: Path, takeout: Takeout, simular: bool = False, lado: int = LADO,
             calidad: int = CALIDAD, progreso=None) -> Resumen:
    """Añade al cuaderno las notas del Takeout que aún no tenga; con `simular`, solo las cuenta.

    `lado` 0 deja las imágenes tal cual. Un archivo dañado no deja fuera su nota: se apunta en los
    avisos y en sus detalles. Las notas cuyo audio necesita ffmpeg y no está, se dejan para después.
    """
    resumen = Resumen(avisos=list(takeout.avisos))
    cuaderno = None
    if not simular:
        cuaderno = Cuaderno(carpeta_cuaderno)
    else:
        with contextlib.suppress(ErrorNotas):
            cuaderno = Cuaderno(carpeta_cuaderno, crear=False)
    ya = cuaderno.importadas() if cuaderno else set()
    hay_ffmpeg = bool(shutil.which("ffmpeg"))
    if lado and not _hay_pillow() and any(n.archivos for n in takeout.notas):
        resumen.avisos.append("Sin Pillow las imágenes no se reducen (pip install Pillow)")

    for i, nota in enumerate(takeout.notas, 1):
        if nota.vacia:
            resumen.vacias += 1
        elif nota.origen in ya:
            resumen.repetidas += 1
        elif not hay_ffmpeg and any(r.suffix.lower() in (".3gp", ".amr") for r, _, _ in nota.archivos):
            resumen.avisos.append(f"{_nombre(nota)}: se deja para después, hace falta ffmpeg para su "
                                  "nota de voz (winget install ffmpeg)")
        else:
            ya.add(nota.origen)
            if not simular:
                _importar_nota(cuaderno, nota, lado, calidad, resumen)
            _contar(resumen, nota)
        if progreso:
            progreso(i, len(takeout.notas))
    if cuaderno and not simular:
        existentes = {normalizar(c["nombre"]) for c in cuaderno.categorias()}
        for etiqueta in takeout.etiquetas:               # también las que no usa ninguna nota
            if normalizar(etiqueta) not in existentes:
                cuaderno.crear_categoria(etiqueta)
                existentes.add(normalizar(etiqueta))
    return resumen


def _nombre(nota: NotaKeep) -> str:
    return nota.datos["detalles"].get("archivo") or nota.datos["titulo"]


def _contar(resumen: Resumen, nota: NotaKeep):
    d, t = nota.datos, resumen.tipos
    resumen.importadas += 1
    voces = sum(r.suffix.lower() in EXT_AUDIO for r, _, _ in nota.archivos)
    t["imagenes"] += len(nota.archivos) - voces
    t["audios"] += voces
    for clave, si in (("texto", not nota.archivos), ("lista", re.search(f"^[{PENDIENTE}{HECHA}]", d["texto"], re.M)),
                      ("imagen", len(nota.archivos) > voces), ("voz", voces),
                      ("activas", not d.get("archivada") and not d.get("papelera")),
                      ("archivadas", d.get("archivada")), ("papelera", d.get("papelera")),
                      ("fijadas", d.get("fijada")), ("color", d.get("color")),
                      ("etiquetadas", d.get("categorias")), ("enlaces", d["detalles"].get("enlaces")),
                      ("compartidas", d["detalles"].get("compartida")),
                      ("recordatorio", d["detalles"].get("recordatorio"))):
        t[clave] += bool(si)
    resumen.bytes_origen += sum(r.stat().st_size for r, _, _ in nota.archivos)


def _importar_nota(cuaderno: Cuaderno, nota: NotaKeep, lado: int, calidad: int, resumen: Resumen):
    adjuntos, fallos = [], []
    for ruta, nombre, creado in nota.archivos:
        try:
            duracion = None
            if ruta.suffix.lower() in EXT_AUDIO:
                datos, ext, duracion = convertir_audio(ruta)
            else:
                datos = reducir_imagen(ruta, lado, calidad) if lado else ruta.read_bytes()
                ext = adj.identificar(datos[:adj.BYTES_CABECERA], ruta.name)[2]
        except (OSError, AdjuntoNoValido) as exc:
            fallos.append(ruta.name)
            resumen.avisos.append(f"{_nombre(nota)}: {ruta.name} no se ha podido guardar: {exc}")
            continue
        resumen.bytes_final += len(datos)
        adjuntos.append({"flujo": io.BytesIO(datos), "nombre": nombre + ext, "creado": creado,
                         "duracion": duracion})
    datos = dict(nota.datos)
    if fallos:
        datos["detalles"] = {**datos["detalles"],
                             "faltan": datos["detalles"].get("faltan", []) + fallos}
    cuaderno.importar(nota.origen, adjuntos=adjuntos, **datos)
