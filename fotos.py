"""Tratamiento de fotos: fecha de captura, organización Año/Mes y optimización.

Requiere:  pip install Pillow
Opcional:  pip install pillow-heif   (fotos HEIC/HEIF del iPhone)
"""

import math
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from catalogo import Catalogo, Informe
from media_utils import (
    NOMBRE_ORIGINALES, copiar_atomico, fecha_desde_nombre, fecha_mtime, fecha_plausible,
    hash_archivo, imprimir, imprimir_resumen, listar_archivos, nombre_libre,
    nuevas_estadisticas, ruta_temporal, subcarpeta_fecha,
)

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_DISPONIBLE = True
except ImportError:
    HEIF_DISPONIBLE = False

EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif",
                    ".tif", ".tiff", ".bmp", ".gif"}
EXTENSIONES_HEIF = {".heic", ".heif"}

# formato -> (nombre en Pillow, extensión de salida, extensiones "ya en ese formato")
FORMATOS = {
    "jpeg": ("JPEG", ".jpg", {".jpg", ".jpeg"}),
    "webp": ("WEBP", ".webp", {".webp"}),
}

MAX_LADO = 2560   # píxeles máximos en el lado largo (0 = no redimensionar)
CALIDAD = 88      # 80-92 = buen equilibrio calidad/peso

# Etiquetas EXIF
IFD_EXIF, IFD_GPS = 0x8769, 0x8825
TAG_FECHA_ORIGINAL, TAG_FECHA_DIGITALIZADA, TAG_FECHA = 36867, 36868, 306
TAG_MARCA, TAG_MODELO, TAG_ORIENTACION = 271, 272, 274


@dataclass
class OpcionesFotos:
    max_lado: int = MAX_LADO
    calidad: int = CALIDAD
    formato: str = "jpeg"
    conservar_originales: bool = True
    hilos: int = 0          # 0 = automático


# ----------------------------- Metadatos -----------------------------

def _parsear_fecha_exif(valor):
    if not isinstance(valor, str):
        return None
    texto = valor.strip().strip("\x00").strip()[:19]
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
    con get_ifd(); `exif.get(36867)` a secas devuelve siempre None.
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


def _gps(exif):
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


def _texto_exif(valor) -> str:
    return str(valor or "").strip("\x00 ").strip()


def _camara(exif) -> str:
    marca, modelo = _texto_exif(exif.get(TAG_MARCA)), _texto_exif(exif.get(TAG_MODELO))
    # "Canon" + "Canon EOS 5D" -> "Canon EOS 5D"
    if marca and modelo.lower().startswith(marca.split()[0].lower()):
        return modelo
    return f"{marca} {modelo}".strip()


def leer_metadatos(ruta: Path) -> dict:
    """Fecha (y su origen), dimensiones ya orientadas, cámara, GPS y si es animada.

    Lanza excepción si el archivo no se puede abrir como imagen.
    """
    with Image.open(ruta) as im:
        exif = im.getexif()
        ancho, alto = im.size
        if exif.get(TAG_ORIENTACION) in (5, 6, 7, 8):
            ancho, alto = alto, ancho
        datos = {
            "fecha": fecha_exif(exif), "fuente": "exif",
            "ancho": ancho, "alto": alto,
            "camara": _camara(exif), "gps": _gps(exif),
            "animado": bool(getattr(im, "is_animated", False)),
        }
    if datos["fecha"] is None:
        datos["fecha"] = fecha_desde_nombre(ruta.stem)
        datos["fuente"] = "nombre"
    if datos["fecha"] is None:
        datos["fecha"], datos["fuente"] = fecha_mtime(ruta), "archivo"
    return datos


def obtener_fecha(ruta: Path):
    """(fecha, fuente): EXIF > nombre del archivo > fecha de modificación."""
    try:
        datos = leer_metadatos(ruta)
        return datos["fecha"], datos["fuente"]
    except Exception:
        fecha = fecha_desde_nombre(ruta.stem)
        return (fecha, "nombre") if fecha else (fecha_mtime(ruta), "archivo")


# ----------------------------- Optimización -----------------------------

def guardar_optimizada(ruta: Path, destino: Path, opciones: OpcionesFotos = None):
    """Escribe en `destino` la versión reducida y recomprimida (de forma atómica).

    Conserva EXIF (fecha, cámara, GPS) y el perfil de color ICC: sin él, las fotos
    de móviles en Display P3 se ven apagadas.
    """
    opciones = opciones or OpcionesFotos()
    formato_pil = FORMATOS[opciones.formato][0]

    with Image.open(ruta) as original:
        modo_original = original.mode
        icc = original.info.get("icc_profile")
        im = ImageOps.exif_transpose(original)   # aplica la rotación EXIF
        exif = im.getexif()
        exif.pop(TAG_ORIENTACION, None)          # ya aplicada: evitar doble giro

    if opciones.max_lado and max(im.size) > opciones.max_lado:
        factor = opciones.max_lado / max(im.size)
        nuevo = (max(1, round(im.width * factor)), max(1, round(im.height * factor)))
        im = im.resize(nuevo, Image.Resampling.LANCZOS, reducing_gap=3.0)

    transparente = im.mode in ("RGBA", "LA", "PA") or (
        im.mode == "P" and "transparency" in im.info)
    if transparente and formato_pil == "WEBP":
        im = im.convert("RGBA")
    elif transparente:
        rgba = im.convert("RGBA")
        im = Image.new("RGB", im.size, (255, 255, 255))
        im.paste(rgba, mask=rgba.getchannel("A"))
    elif im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if modo_original == "CMYK":
        icc = None   # el perfil CMYK no vale para la imagen ya convertida a RGB

    kwargs = {"quality": opciones.calidad}
    if formato_pil == "JPEG":
        kwargs.update(optimize=True, progressive=True)
    if icc:
        kwargs["icc_profile"] = icc
    if len(exif):
        kwargs["exif"] = exif

    tmp = ruta_temporal(destino)
    try:
        im.save(tmp, formato_pil, **kwargs)
        os.replace(tmp, destino)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ----------------------------- Procesamiento -----------------------------

@dataclass
class _Tarea:
    ruta: Path
    estado: str = "pendiente"      # pendiente | ya_importado | error
    detalle: str = ""
    tamano: int = 0
    mtime_ns: int = 0
    hash: str = ""
    fecha: datetime = None
    fuente: str = ""
    dimensiones: tuple = (0, 0)
    animado: bool = False
    destino: Path = None
    original: Path = None


def _analizar(ruta: Path, catalogo: Catalogo) -> _Tarea:
    """Fase 1 (en paralelo): ¿ya importada? hash, fecha y propiedades."""
    t = _Tarea(ruta)
    try:
        st = ruta.stat()
        t.tamano, t.mtime_ns = st.st_size, st.st_mtime_ns
        # Mismo archivo de una ejecución anterior: ni siquiera hace falta leerlo entero
        fila = catalogo.buscar_por_origen(ruta, st)
        if fila is None:
            t.hash = hash_archivo(ruta)
            fila = catalogo.buscar_por_hash(t.hash)   # mismo contenido, otra ruta
        if fila is not None:
            t.estado, t.detalle = "ya_importado", fila["destino"]
            return t
        datos = leer_metadatos(ruta)
        t.fecha, t.fuente = datos["fecha"], datos["fuente"]
        t.dimensiones = (datos["ancho"], datos["alto"])
        t.animado = datos["animado"]
    except Exception as exc:
        t.estado, t.detalle = "error", f"no se puede leer: {exc}"
    return t


def _ejecutar(t: _Tarea, opciones: OpcionesFotos, extensiones_mismo_formato: set) -> str:
    """Fase 3 (en paralelo): escribe la foto final y la copia del original."""
    t.destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        if t.animado:
            copiar_atomico(t.ruta, t.destino)   # GIF/WebP animados: no perder la animación
            accion = "COPIADO_ANIMADO"
        else:
            guardar_optimizada(t.ruta, t.destino, opciones)
            sin_redimensionar = not opciones.max_lado or max(t.dimensiones) <= opciones.max_lado
            if (sin_redimensionar and t.ruta.suffix.lower() in extensiones_mismo_formato
                    and t.destino.stat().st_size >= t.tamano):
                copiar_atomico(t.ruta, t.destino)   # recomprimir no compensa
                accion = "SIN_CAMBIOS"
            else:
                accion = "OK"
        if t.original:
            t.original.parent.mkdir(parents=True, exist_ok=True)
            copiar_atomico(t.ruta, t.original)
    except BaseException:
        t.destino.unlink(missing_ok=True)   # no dejar una foto sin su original
        raise
    return accion


def procesar_fotos(origen: Path, destino: Path, simular: bool,
                   opciones: OpcionesFotos = None) -> dict:
    opciones = opciones or OpcionesFotos()
    formato_pil, ext_salida, mismo_formato = FORMATOS[opciones.formato]
    carpeta_originales = destino / NOMBRE_ORIGINALES
    stats = nuevas_estadisticas()

    archivos = listar_archivos(origen, EXTENSIONES_FOTO)
    if not archivos:
        print(f"No se encontraron fotos en {origen}")
        return stats

    if not HEIF_DISPONIBLE:
        heif = [a for a in archivos if a.suffix.lower() in EXTENSIONES_HEIF]
        if heif:
            print(f"AVISO: se omiten {len(heif)} foto(s) HEIC/HEIF. "
                  "Para incluirlas:  pip install pillow-heif")
            archivos = [a for a in archivos if a.suffix.lower() not in EXTENSIONES_HEIF]
            stats["omitidos"] = len(heif)

    hilos = opciones.hilos or min(8, os.cpu_count() or 2)
    print(f"\n{'SIMULACIÓN' if simular else 'PROCESANDO'} — {len(archivos)} foto(s) — "
          f"{formato_pil}, calidad {opciones.calidad}, "
          f"máx. {opciones.max_lado or 'sin límite'} px — {hilos} hilo(s)\n")

    with Catalogo(destino, simular) as catalogo, \
            Informe(destino, "fotos", simular) as informe, \
            ThreadPoolExecutor(hilos) as pool:
        try:
            # Fase 1: análisis en paralelo
            tareas = list(pool.map(lambda r: _analizar(r, catalogo), archivos))

            # Fase 2: duplicados y nombres, en orden cronológico (ráfagas -> _01, _02...)
            reservados, vistos, pendientes = set(), {}, []
            tareas.sort(key=lambda t: (t.fecha or datetime.min, str(t.ruta)))
            for t in tareas:
                rel = t.ruta.relative_to(origen)
                if t.estado == "ya_importado":
                    stats["ya_importados"] += 1
                    continue
                if t.estado == "error":
                    imprimir(f"  ERROR      {rel}: {t.detalle}")
                    informe.anotar("ERROR", t.ruta, detalle=t.detalle)
                    stats["errores"] += 1
                    continue
                if t.hash in vistos:
                    t.detalle = f"igual que {vistos[t.hash]}"
                    imprimir(f"  DUPLICADO  {rel}  ({t.detalle})")
                    informe.anotar("DUPLICADO", t.ruta, detalle=t.detalle)
                    stats["duplicados"] += 1
                    continue

                vistos[t.hash] = rel
                carpeta_rel = subcarpeta_fecha(t.fecha)
                ext = t.ruta.suffix.lower() if t.animado else ext_salida
                t.destino = nombre_libre(destino / carpeta_rel,
                                         t.fecha.strftime("%Y%m%d_%H%M%S"), ext, reservados)
                if opciones.conservar_originales:
                    t.original = nombre_libre(carpeta_originales / carpeta_rel,
                                              t.ruta.stem, t.ruta.suffix, reservados)
                if simular:
                    imprimir(f"  {rel}  ->  {carpeta_rel}/{t.destino.name}  "
                             f"[fecha: {t.fuente}]")
                    stats["procesados"] += 1
                else:
                    pendientes.append(t)

            # Fase 3: escritura en paralelo
            futuros = {pool.submit(_ejecutar, t, opciones, mismo_formato): t
                       for t in pendientes}
            for n, futuro in enumerate(as_completed(futuros), 1):
                t = futuros[futuro]
                rel = t.ruta.relative_to(origen)
                destino_rel = t.destino.relative_to(destino).as_posix()
                prefijo = f"  [{n}/{len(pendientes)}]"
                try:
                    accion = futuro.result()
                except Exception as exc:
                    imprimir(f"{prefijo} ERROR {rel}: {exc}")
                    informe.anotar("ERROR", t.ruta, detalle=str(exc))
                    stats["errores"] += 1
                    continue
                despues = t.destino.stat().st_size
                original_rel = t.original.relative_to(destino).as_posix() if t.original else None
                catalogo.registrar(
                    hash=t.hash, tipo="foto", origen=str(t.ruta), tamano=t.tamano,
                    mtime_ns=t.mtime_ns, destino=destino_rel, original=original_rel,
                    fecha=t.fecha.isoformat(), fuente_fecha=t.fuente,
                    bytes_antes=t.tamano, bytes_despues=despues)
                informe.anotar(accion, t.ruta, destino_rel, t.fecha, t.fuente,
                               t.tamano, despues)
                etiqueta = {"OK": "OK", "SIN_CAMBIOS": "SIN CAMBIOS",
                            "COPIADO_ANIMADO": "ANIMADA"}[accion]
                imprimir(f"{prefijo} {etiqueta}  {rel}  ->  {destino_rel}")
                stats["procesados"] += 1
                stats["sin_cambios"] += accion != "OK"
                stats["bytes_antes"] += t.tamano
                stats["bytes_despues"] += despues
        except KeyboardInterrupt:
            pool.shutdown(wait=True, cancel_futures=True)
            imprimir("\nInterrumpido. Lo ya terminado queda registrado; "
                     "vuelve a ejecutar para continuar.")
            raise

    imprimir_resumen(stats, "fotos", simular,
                     carpeta_originales if opciones.conservar_originales else None,
                     informe.ruta if informe.filas else None)
    return stats
