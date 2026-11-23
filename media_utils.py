"""Utilidades compartidas entre fotos, vídeos y galería."""

import hashlib
import json
import os
import re
import shutil
import sys
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOMBRE_ORIGINALES = "originales"   # copias intactas de los archivos de origen
CARPETA_INTERNA = ".exportador"     # catálogo SQLite e informes CSV
CARPETA_GALERIA = "_galeria"        # miniaturas y favoritos de la galería

# Carpetas que nunca se recorren al buscar archivos (además de las ocultas ".algo")
CARPETAS_EXCLUIDAS = {
    NOMBRE_ORIGINALES, CARPETA_GALERIA,
    "$RECYCLE.BIN", "System Volume Information", "@eaDir",
}

MESES_ES = {
    1: "01-Enero", 2: "02-Febrero", 3: "03-Marzo", 4: "04-Abril",
    5: "05-Mayo", 6: "06-Junio", 7: "07-Julio", 8: "08-Agosto",
    9: "09-Septiembre", 10: "10-Octubre", 11: "11-Noviembre", 12: "12-Diciembre",
}

FECHA_MINIMA = datetime(1971, 1, 1)  # descarta fechas "a cero" (1904, 1970) de cámaras sin hora

_LOCK_CONSOLA = threading.Lock()


# ----------------------------- Consola -----------------------------

def configurar_consola():
    """Evita que un carácter no representable en la consola de Windows aborte el programa."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def imprimir(mensaje: str = ""):
    """print() seguro entre hilos."""
    with _LOCK_CONSOLA:
        print(mensaje, flush=True)


# El panel web lanza el exportador con EXPORTADOR_PROGRESO=1 y lee de su salida las
# líneas que empiezan por MARCA_PROGRESO (JSON). En la terminal no se emite nada.
VARIABLE_PROGRESO = "EXPORTADOR_PROGRESO"
MARCA_PROGRESO = "@@progreso "


def progreso(evento: str, fase: str, **datos):
    """Evento de progreso para el panel: inicio/fin de una fase, avance (hecho/total)...

    No hace nada si el programa no lo ha lanzado el panel.
    """
    if os.environ.get(VARIABLE_PROGRESO) != "1":
        return
    linea = json.dumps({"evento": evento, "fase": fase, **datos},
                       ensure_ascii=False, default=str)
    with _LOCK_CONSOLA:
        print(MARCA_PROGRESO + linea, flush=True)


def formato_bytes(n: float) -> str:
    for unidad in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.0f} {unidad}" if unidad == "B" else f"{n:.1f} {unidad}"
        n /= 1024
    return f"{n:.2f} TB"


# ----------------------------- Archivos -----------------------------

def hash_archivo(ruta: Path) -> str:
    """MD5 del contenido (detección de duplicados, no seguridad)."""
    h = hashlib.md5()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def listar_archivos(origen: Path, extensiones: set) -> list:
    """Archivos con esas extensiones, sin entrar en carpetas internas ni ocultas.

    También descarta los "._archivo" que macOS deja en tarjetas y discos externos.
    """
    encontrados = []
    for raiz, carpetas, archivos in os.walk(origen):
        carpetas[:] = [c for c in carpetas
                       if c not in CARPETAS_EXCLUIDAS and not c.startswith(".")]
        for nombre in archivos:
            if nombre.startswith("._"):
                continue
            if os.path.splitext(nombre)[1].lower() in extensiones:
                encontrados.append(Path(raiz) / nombre)
    return sorted(encontrados)


def nombre_libre(carpeta: Path, base: str, extension: str, reservados: set = None) -> Path:
    """Ruta no ocupada: base.ext, base_01.ext, base_02.ext...

    `reservados` (opcional) guarda los nombres ya asignados en esta ejecución que
    aún no existen en disco (simulación, procesamiento en paralelo).
    """
    def ocupada(ruta: Path) -> bool:
        return ruta.exists() or (reservados is not None and str(ruta).lower() in reservados)

    candidata = carpeta / f"{base}{extension}"
    contador = 1
    while ocupada(candidata):
        candidata = carpeta / f"{base}_{contador:02d}{extension}"
        contador += 1
    if reservados is not None:
        reservados.add(str(candidata).lower())
    return candidata


def ruta_temporal(destino: Path) -> Path:
    """Archivo temporal junto al destino; se renombra al terminar (escritura atómica)."""
    return destino.with_name(destino.name + ".part")


def copiar_atomico(origen: Path, destino: Path):
    """Copia (con metadatos) sin dejar nunca un archivo a medias en `destino`."""
    tmp = ruta_temporal(destino)
    try:
        shutil.copy2(origen, tmp)
        os.replace(tmp, destino)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def subcarpeta_fecha(fecha: datetime) -> str:
    """Subcarpeta relativa Año/Mes, ej.: '2024/05-Mayo'."""
    return f"{fecha.year}/{MESES_ES[fecha.month]}"


# ----------------------------- Fechas -----------------------------

def fecha_plausible(fecha: datetime) -> bool:
    return FECHA_MINIMA <= fecha <= datetime.now() + timedelta(days=2)


def fecha_mtime(ruta: Path) -> datetime:
    return datetime.fromtimestamp(ruta.stat().st_mtime)


# IMG_20240512_102030, VID-20240512-102030, PXL_20240512_102030123,
# Screenshot_2024-05-12-10-20-30, "Captura de pantalla 2024-05-12 102030",
# "2024-05-12 10.20.30" (Dropbox), "Screenshot 2024-05-12 at 10.20.30"...
_RE_FECHA_HORA = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])"
    r"[-_ T.]{0,3}(?:at[ _]?)?([01]\d|2[0-3])[-_.:h]?([0-5]\d)[-_.:m]?([0-5]\d)",
    re.IGNORECASE,
)
# IMG-20240512-WA0001 (WhatsApp), 2024-05-12... (solo fecha)
_RE_FECHA = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)")


def fecha_desde_nombre(nombre: str):
    """Fecha deducida del nombre del archivo (móviles, WhatsApp, capturas...) o None."""
    for regex in (_RE_FECHA_HORA, _RE_FECHA):
        for coincidencia in regex.finditer(nombre):
            try:
                fecha = datetime(*(int(g) for g in coincidencia.groups()))
            except ValueError:
                continue
            if fecha_plausible(fecha):
                return fecha
    return None


FORMATO_NOMBRE = "%Y%m%d_%H%M%S"
_RE_CONTADOR_WA = re.compile(r"-(WA\d+)", re.IGNORECASE)


def nombre_tiene_hora(nombre: str) -> bool:
    """¿El nombre trae fecha *y hora* (IMG_20240512_102030) y no solo fecha (IMG-20240512-WA0001)?"""
    for m in _RE_FECHA_HORA.finditer(nombre):
        try:
            if fecha_plausible(datetime(*(int(g) for g in m.groups()))):
                return True
        except ValueError:
            continue
    return False


def _sufijo_legible(stem: str) -> str:
    m = _RE_CONTADOR_WA.search(stem)
    if m:
        return m.group(1).upper()
    sin_fecha = _RE_FECHA.sub("", stem)
    limpio = re.sub(r"[^0-9A-Za-z]+", "-", sin_fecha).strip("-")[:24]
    return limpio or "sinhora"


def fecha_aproximada(ruta: Path, fecha: datetime, mtime: datetime = None):
    """Fecha deducida de un nombre *sin hora* (WhatsApp): (fecha, fuente, base_del_nombre).

    - Si la fecha de modificación del archivo es del mismo día, se toma su hora
      (fuente 'nombre+hora_archivo'): 20260121_183012.
    - Si no, la fecha se queda a las 00:00 y el nombre lo dice claramente en vez de
      inventar una hora: 20260121_WA0011 (o 20260121_<resto del nombre>).
    """
    mtime = mtime or fecha_mtime(ruta)
    if mtime.date() == fecha.date():
        return mtime.replace(microsecond=0), "nombre+hora_archivo", mtime.strftime(FORMATO_NOMBRE)
    return fecha, "nombre", f"{fecha:%Y%m%d}_{_sufijo_legible(Path(ruta).stem)}"


def fecha_y_nombre(ruta: Path, fecha: datetime, fuente: str):
    """(fecha, fuente, base) para un archivo nuevo. Solo cambia las fechas sacadas del
    nombre sin hora; el resto se nombra AAAAMMDD_HHMMSS como siempre."""
    if (fuente == "nombre" and fecha.time() == datetime.min.time()
            and not nombre_tiene_hora(Path(ruta).stem)):
        return fecha_aproximada(ruta, fecha)
    return fecha, fuente, fecha.strftime(FORMATO_NOMBRE)


_RE_ISO = re.compile(
    r"^\s*(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,]\d+)?\s*"
    r"(Z|[+-]\d{2}:?\d{2})?\s*$", re.IGNORECASE)


def parsear_fecha_iso(texto):
    """Fecha ISO 8601 de metadatos de vídeo -> datetime local sin zona, o None.

    - Con zona UTC ("Z", "+00:00"), lo habitual en `creation_time`: se convierte a
      la hora local de este equipo.
    - Con otra zona (p. ej. iPhone: "2024-05-12T10:20:30+0200"): se conserva la hora
      de reloj tal cual, que es la que vio quien grabó y la que ponen las fotos EXIF.
    """
    if not texto:
        return None
    texto = str(texto)
    if ";" in texto:
        # FFmpeg repite la etiqueta al exportar con use_metadata_tags: "A;A"
        return next(filter(None, map(parsear_fecha_iso, texto.split(";"))), None)
    m = _RE_ISO.match(texto)
    if not m:
        return None
    *partes, zona = m.groups()
    try:
        fecha = datetime(*(int(p) for p in partes))
    except ValueError:
        return None
    if zona:
        zona = zona.upper().replace(":", "")
        if zona in ("Z", "+0000", "-0000"):
            try:
                fecha = fecha.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
            except (OverflowError, OSError, ValueError):
                return None
    return fecha if fecha_plausible(fecha) else None


# ----------------------------- Metadatos externos -----------------------------

@dataclass
class MetadatosExtra:
    """Metadatos que vienen aparte del archivo (p. ej. el JSON de Google Fotos).

    Al exportar se añade a la foto o al vídeo lo que le falte: la fecha y el GPS solo
    si no los trae; etiquetas y personas se suman; la descripción manda sobre la suya.
    """
    fecha: datetime = None           # hora local de captura
    zona: str = ""                   # desfase de `fecha` respecto a UTC ("+02:00"); "" = no se sabe
    fuente: str = "google"           # cómo se anota la fecha en el catálogo y el informe
    fecha_prioritaria: bool = False  # manda sobre la del propio archivo (clip de una foto con movimiento)
    fecha_dudosa: bool = False       # no es la de captura (p. ej. la de subida): no se graba
    gps: tuple = None                # (latitud, longitud, altitud en m o None)
    descripcion: str = ""
    etiquetas: list = field(default_factory=list)   # álbumes de Google Fotos
    personas: list = field(default_factory=list)
    favorita: bool = False

    def aporta_xmp(self) -> bool:
        return bool(self.etiquetas or self.personas or self.descripcion or self.favorita)

    def combinar(self, otro: "MetadatosExtra") -> "MetadatosExtra":
        """Junta los de dos copias idénticas del mismo archivo (p. ej. la de un álbum y la
        de «Fotos del AAAA»): álbumes y personas de las dos; lo demás, el de `self` si lo
        tiene. La fecha no se toca: ya se eligió con el archivo que se importa."""
        if otro is None:
            return self
        def unir(a, b):
            vistos = {x.lower() for x in a}
            return a + [x for x in b if x.lower() not in vistos and not vistos.add(x.lower())]
        return replace(self, gps=self.gps or otro.gps,
                       descripcion=self.descripcion or otro.descripcion,
                       etiquetas=unir(self.etiquetas, otro.etiquetas),
                       personas=unir(self.personas, otro.personas),
                       favorita=self.favorita or otro.favorita)


def elegir_fecha(ruta: Path, fecha: datetime, fuente: str, extra: MetadatosExtra = None):
    """(fecha, fuente) combinando la del archivo con la de unos metadatos externos.

    Orden: la del propio archivo (EXIF, metadatos del vídeo) > nombre con hora > externa >
    nombre sin hora > fecha del archivo. En Google Fotos, la fecha del JSON de una foto sin
    EXIF suele ser la de subida: un nombre con hora (PANO_20120714_124817) manda sobre ella,
    y uno con solo el día (IMG-20240512-WA0001) solo la acepta si es del mismo día.
    """
    if extra is None or extra.fecha is None:
        return fecha, fuente
    if extra.fecha_prioritaria:
        return extra.fecha, extra.fuente
    if fuente in ("exif", "metadatos"):
        return fecha, fuente
    if fuente == "nombre" and (nombre_tiene_hora(Path(ruta).stem)
                               or fecha.date() != extra.fecha.date()):
        return fecha, fuente
    return extra.fecha, extra.fuente


def metadatos_para_escribir(ruta: Path, extra: MetadatosExtra, fecha: datetime, fuente: str):
    """`extra` con la fecha que debe grabarse en el archivo exportado: la elegida por
    `elegir_fecha`, salvo que salga del nombre sin hora o de la fecha del archivo (no se
    inventa una hora). Solo se graba si el archivo no trae ya la suya."""
    if extra is None:
        return None
    fiable = ((fuente == extra.fuente and not extra.fecha_dudosa)
              or (fuente == "nombre" and nombre_tiene_hora(Path(ruta).stem)))
    return replace(extra, fecha=fecha if fiable else None,
                   zona=extra.zona if fuente == extra.fuente else "")


def resumen_extra(extra: MetadatosExtra, externos, copia: bool = False) -> str:
    """'  [añade: fecha, GPS, 2 álbum(es)…]': lo que se graba en el archivo exportado
    (para la consola y el informe). `copia`: se copia tal cual (GIF animado, pegatina)."""
    if not externos:
        return ""
    if extra is None:
        return "  [sin JSON]"
    if copia:
        return "  [copia tal cual: sin metadatos añadidos]"
    partes = [nombre for nombre, hay in (
        ("fecha", extra.fecha), ("GPS", extra.gps), ("descripción", extra.descripcion),
        (f"{len(extra.etiquetas)} álbum(es)", extra.etiquetas),
        (f"{len(extra.personas)} persona(s)", extra.personas),
        ("favorita", extra.favorita)) if hay]
    return f"  [añade: {', '.join(partes)}]" if partes else "  [nada que añadir]"


def contar_extra(stats: dict, extra: MetadatosExtra, externos):
    if externos:
        stats["con_json" if extra is not None else "sin_json"] += 1


# ----------------------------- Estadísticas -----------------------------

def nuevas_estadisticas() -> dict:
    return {"procesados": 0, "sin_cambios": 0, "ya_importados": 0, "duplicados": 0,
            "omitidos": 0, "errores": 0, "bytes_antes": 0, "bytes_despues": 0,
            "parecidas": 0, "parecidas_omitidas": 0, "danados": 0,
            "editadas": 0, "con_json": 0, "sin_json": 0}


def imprimir_resumen(stats: dict, sustantivo: str, simular: bool,
                     carpeta_originales: Path = None, informe: Path = None):
    verbo = "a procesar" if simular else (
        "procesadas" if sustantivo == "fotos" else "procesados")
    filas = [
        (f"{sustantivo.capitalize()} {verbo}", stats["procesados"]),
        ("  de ellos sin recomprimir", stats["sin_cambios"]),
        ("Ya estaban en la biblioteca", stats["ya_importados"]),
        ("Duplicados (no se tocan)", stats["duplicados"]),
        ("Parecidas a otra foto", stats.get("parecidas", 0)),
        ("Parecidas no importadas", stats.get("parecidas_omitidas", 0)),
        ("Quitadas antes a mano", stats.get("descartadas", 0)),
        ("Dañados (ver informe)", stats.get("danados", 0)),
        ("Editadas (va el original)", stats.get("editadas", 0)),
        ("Con metadatos de Google", stats.get("con_json", 0)),
        ("Sin JSON de Google", stats.get("sin_json", 0)),
        ("Omitidos", stats["omitidos"]),
        ("Errores", stats["errores"]),
    ]
    print("\n----------- RESUMEN -----------")
    for etiqueta, valor in filas:
        if valor or etiqueta.startswith(sustantivo.capitalize()) or etiqueta == "Errores":
            print(f"{etiqueta:<28}: {valor}")
    if not simular and stats["bytes_antes"]:
        ahorro = (1 - stats["bytes_despues"] / stats["bytes_antes"]) * 100
        print(f"{'Peso original':<28}: {formato_bytes(stats['bytes_antes'])}")
        print(f"{'Peso final':<28}: {formato_bytes(stats['bytes_despues'])}"
              f"  (ahorro {ahorro:.0f} %)")
    if not simular and carpeta_originales and carpeta_originales.exists():
        print(f"{'Originales en':<28}: {carpeta_originales}")
    if informe:
        print(f"{'Informe CSV':<28}: {informe}")
