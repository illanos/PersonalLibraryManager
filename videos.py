"""Tratamiento de vídeos: fecha de grabación, organización Año/Mes y recodificación.

Requiere FFmpeg y ffprobe accesibles en la terminal:
    winget install Gyan.FFmpeg
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from catalogo import Catalogo, Informe
from clasificacion import carpeta_destino, categoria
from media_utils import (
    NOMBRE_ORIGINALES, copiar_atomico, fecha_desde_nombre, fecha_mtime, formato_bytes, hash_archivo,
    imprimir_resumen, listar_archivos, nombre_libre, nuevas_estadisticas,
    parsear_fecha_iso, ruta_temporal, subcarpeta_fecha,
)

EXTENSIONES_VIDEO = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v",
    ".mpg", ".mpeg", ".mts", ".m2ts", ".3gp", ".webm", ".flv",
}

AUDIO = ["-b:a", "128k"]

PERFILES = {
    # H.264 + AAC en MP4: se reproduce en cualquier sitio.
    "h264": {"ext": ".mp4", "formato": "mp4", "crf": 23,
             "video": ["-c:v", "libx264", "-preset", "{preset}", "-pix_fmt", "yuv420p"],
             "audio": ["-c:a", "aac", *AUDIO],
             "extra": ["-movflags", "+faststart+use_metadata_tags"]},
    # H.265/HEVC: ~40 % menos peso que H.264; algunos navegadores antiguos no lo reproducen.
    "h265": {"ext": ".mp4", "formato": "mp4", "crf": 28,
             "video": ["-c:v", "libx265", "-preset", "{preset}", "-pix_fmt", "yuv420p",
                       "-tag:v", "hvc1", "-x265-params", "log-level=error"],
             "audio": ["-c:a", "aac", *AUDIO],
             "extra": ["-movflags", "+faststart+use_metadata_tags"]},
    # VP9 + Opus en WebM: libre de patentes, más lento de codificar.
    "vp9": {"ext": ".webm", "formato": "webm", "crf": 32,
            "video": ["-c:v", "libvpx-vp9", "-b:v", "0", "-row-mt", "1",
                      "-deadline", "good", "-cpu-used", "2"],
            "audio": ["-c:a", "libopus", *AUDIO],
            "extra": []},
}

CLAVES_FECHA = ("com.apple.quicktime.creationdate", "creation_time", "date")


@dataclass
class OpcionesVideos:
    codec: str = "h264"
    max_lado: int = 1920     # 0 = mantener resolución
    crf: int = None          # None = el del perfil
    preset: str = "medium"   # h264/h265: ultrafast ... veryslow
    conservar_originales: bool = False   # copia extra en originales/ (el origen nunca se toca)


# ----------------------------- Metadatos -----------------------------

def _rotacion(stream: dict) -> int:
    """Giro del vídeo (los móviles graban en horizontal y marcan el giro)."""
    rotacion = (stream.get("tags") or {}).get("rotate")
    for datos in stream.get("side_data_list") or []:
        if "rotation" in datos:
            rotacion = datos["rotation"]
    try:
        return int(float(rotacion or 0))
    except ValueError:
        return 0


def _fecha_metadatos(datos: dict):
    """Fecha de grabación según los metadatos del contenedor o de las pistas."""
    grupos = [datos.get("format", {}).get("tags") or {}]
    grupos += [s.get("tags") or {} for s in datos.get("streams", [])]
    grupos = [{k.lower(): v for k, v in g.items()} for g in grupos]
    for clave in CLAVES_FECHA:   # la de Apple lleva la hora local: es la más fiable
        for tags in grupos:
            fecha = parsear_fecha_iso(tags.get(clave))
            if fecha:
                return fecha
    return None


_RE_ISO6709 = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def _tags_contenedor(datos: dict) -> dict:
    return {k.lower(): v for k, v in (datos.get("format", {}).get("tags") or {}).items()}


def _gps_video(tags: dict):
    """Ubicación ISO 6709 ("+40.4168-003.7038+650/") de iPhone y Android."""
    for clave in ("com.apple.quicktime.location.iso6709", "location", "location-eng"):
        m = _RE_ISO6709.match(str(tags.get(clave) or ""))
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat or lon):
                return [round(lat, 6), round(lon, 6)]
    return None


def _camara_video(tags: dict) -> str:
    def primero(*claves):
        return next((str(tags[c]).strip() for c in claves if tags.get(c)), "")

    marca = primero("com.apple.quicktime.make", "make", "com.android.manufacturer")
    modelo = primero("com.apple.quicktime.model", "model", "com.android.model")
    if marca and modelo.lower().startswith(marca.split()[0].lower()):
        return modelo
    return f"{marca} {modelo}".strip()


def sondear(ruta: Path):
    """Metadatos vía ffprobe (fecha, dimensiones de visualización, duración...) o None."""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(ruta)]
    try:
        salida = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=60, stdin=subprocess.DEVNULL)
        if salida.returncode != 0:
            return None
        datos = json.loads(salida.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None

    video = next((s for s in datos.get("streams", [])
                  if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), {})
    ancho, alto = int(video.get("width") or 0), int(video.get("height") or 0)
    rotacion = _rotacion(video)
    if abs(rotacion) % 180 == 90:
        ancho, alto = alto, ancho   # se ve en vertical
    formato = datos.get("format", {})
    try:
        duracion = float(formato.get("duration") or video.get("duration") or 0)
    except ValueError:
        duracion = 0.0
    return {
        "fecha": _fecha_metadatos(datos),
        "ancho": ancho, "alto": alto, "rotacion": rotacion,
        "duracion": duracion,
        "codec": video.get("codec_name", ""),
        "camara": _camara_video(_tags_contenedor(datos)),
        "gps": _gps_video(_tags_contenedor(datos)),
    }


def fecha_video(ruta: Path, info: dict = None):
    """(fecha, fuente): metadatos > nombre del archivo > fecha de modificación."""
    if info and info.get("fecha"):
        return info["fecha"], "metadatos"
    fecha = fecha_desde_nombre(ruta.stem)
    if fecha:
        return fecha, "nombre"
    return fecha_mtime(ruta), "archivo"


def obtener_fecha(ruta: Path):
    return fecha_video(ruta, sondear(ruta))[0]


def dimensiones_objetivo(ancho: int, alto: int, max_lado: int):
    """Dimensiones finales previstas (pares) manteniendo la proporción."""
    if not ancho or not alto:
        return ancho, alto
    factor = min(1.0, max_lado / max(ancho, alto)) if max_lado else 1.0
    return (max(2, int(ancho * factor) // 2 * 2), max(2, int(alto * factor) // 2 * 2))


# ----------------------------- Codificación -----------------------------

def filtro_escala(max_lado: int) -> str:
    """Filtro de escalado que FFmpeg evalúa sobre la imagen YA girada.

    No usa las dimensiones de ffprobe: en vídeos verticales de móvil vienen sin
    girar y forzarlas deformaría la imagen. Limita el lado largo a `max_lado`,
    mantiene la proporción y deja dimensiones pares (requisito de H.264).
    """
    if not max_lado:
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    m = int(max_lado)
    return (f"scale=w='if(gte(iw,ih),trunc(min(iw,{m})/2)*2,-2)'"
            f":h='if(gte(iw,ih),-2,trunc(min(ih,{m})/2)*2)'")


def comando_codificacion(entrada: Path, salida: Path, opciones: OpcionesVideos) -> list:
    perfil = PERFILES[opciones.codec]
    crf = opciones.crf if opciones.crf is not None else perfil["crf"]
    video = [a.replace("{preset}", opciones.preset) for a in perfil["video"]]
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(entrada),
        "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0",
        "-vf", filtro_escala(opciones.max_lado),
        *video, "-crf", str(crf), *perfil["audio"], *perfil["extra"],
        "-loglevel", "error", "-progress", "pipe:1", "-nostats",
        "-f", perfil["formato"], str(salida),
    ]


def _mostrar_progreso(etiqueta: str, porcentaje: float):
    if sys.stdout.isatty():
        sys.stdout.write(f"\r{etiqueta}  {porcentaje:5.1f} %")
        sys.stdout.flush()


def _borrar_progreso(etiqueta: str):
    if sys.stdout.isatty():
        sys.stdout.write("\r" + " " * (len(etiqueta) + 10) + "\r")
        sys.stdout.flush()


def ejecutar_ffmpeg(cmd: list, duracion: float = 0, etiqueta: str = ""):
    """Ejecuta FFmpeg mostrando el porcentaje. Devuelve (ok, mensaje_de_error).

    Si se interrumpe (Ctrl+C), mata FFmpeg antes de propagar la interrupción.
    """
    with tempfile.TemporaryFile() as errores:
        proceso = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errores,
                                   stdin=subprocess.DEVNULL, text=True,
                                   encoding="utf-8", errors="replace")
        try:
            for linea in proceso.stdout:
                clave, _, valor = linea.strip().partition("=")
                # out_time_ms está en microsegundos (error histórico de FFmpeg)
                if clave in ("out_time_us", "out_time_ms") and valor.isdigit() and duracion > 0:
                    _mostrar_progreso(etiqueta, min(100.0, int(valor) / 1e6 / duracion * 100))
            proceso.wait()
        except BaseException:
            proceso.kill()
            proceso.wait()
            raise
        finally:
            _borrar_progreso(etiqueta)
        errores.seek(0)
        mensaje = errores.read().decode("utf-8", "replace").strip()
    return proceso.returncode == 0, mensaje


# ----------------------------- Procesamiento -----------------------------

def procesar_videos(origen: Path, destino: Path, simular: bool,
                    opciones: OpcionesVideos = None) -> dict:
    """Recodifica y organiza. El origen solo se lee: nunca se mueve, modifica ni borra.

    - Codificación correcta y más ligera: la versión nueva entra en la biblioteca (y, con
      `conservar_originales`, una copia del original en originales/Año/Mes).
    - Codificación correcta pero no más ligera: se copia el original a la biblioteca tal cual.
    - Error o interrupción: no queda ningún archivo a medias en el destino.
    """
    opciones = opciones or OpcionesVideos()
    perfil = PERFILES[opciones.codec]
    carpeta_originales = destino / NOMBRE_ORIGINALES
    stats = nuevas_estadisticas()

    archivos = listar_archivos(origen, EXTENSIONES_VIDEO)
    if not archivos:
        print(f"No se encontraron vídeos en {origen}")
        return stats

    print(f"\n{'SIMULACIÓN' if simular else 'PROCESANDO'} — {len(archivos)} vídeo(s)"
          f" — codec: {opciones.codec.upper()}, "
          f"máx. {opciones.max_lado or 'sin límite'} px\n")

    reservados, vistos = set(), {}
    with Catalogo(destino, simular) as catalogo, Informe(destino, "videos", simular) as informe:
        for n, ruta in enumerate(archivos, 1):
            rel = ruta.relative_to(origen)
            prefijo = f"  [{n}/{len(archivos)}]"
            tmp = None
            try:
                st = ruta.stat()
                fila = catalogo.buscar_por_origen(ruta, st)
                digest = None
                if fila is None:
                    digest = hash_archivo(ruta)
                    fila = catalogo.buscar_por_hash(digest)
                if fila is not None:
                    stats["ya_importados"] += 1
                    continue
                if digest in vistos:
                    print(f"{prefijo} DUPLICADO  {rel}  (igual que {vistos[digest]})")
                    informe.anotar("DUPLICADO", ruta, detalle=f"igual que {vistos[digest]}")
                    stats["duplicados"] += 1
                    continue

                info = sondear(ruta) or {}
                fecha, fuente = fecha_video(ruta, info)
                cat = categoria(rel)
                carpeta_rel = carpeta_destino(fecha, "" if cat == "captura" else cat, "video")
                base = fecha.strftime("%Y%m%d_%H%M%S")
                destino_video = nombre_libre(destino / carpeta_rel, base, perfil["ext"],
                                             reservados)
                ancho, alto = info.get("ancho", 0), info.get("alto", 0)
                nuevo = dimensiones_objetivo(ancho, alto, opciones.max_lado)
                cambio = f"  ({ancho}x{alto} -> {nuevo[0]}x{nuevo[1]})" \
                    if ancho and nuevo != (ancho, alto) else ""

                if simular:
                    print(f"{prefijo} {rel}  ->  {carpeta_rel}/{destino_video.name}{cambio}"
                          f"  [fecha: {fuente}]")
                    vistos[digest] = rel
                    stats["procesados"] += 1
                    continue

                destino_video.parent.mkdir(parents=True, exist_ok=True)
                tmp = ruta_temporal(destino_video)
                ok, error = ejecutar_ffmpeg(
                    comando_codificacion(ruta, tmp, opciones),
                    info.get("duracion", 0), f"{prefijo} codificando {rel}")

                if not ok or not tmp.exists() or tmp.stat().st_size == 0:
                    tmp.unlink(missing_ok=True)
                    detalle = (error or "FFmpeg no generó salida").splitlines()[-1][:300]
                    print(f"{prefijo} ERROR  {rel}: {detalle}")
                    informe.anotar("ERROR", ruta, detalle=detalle)
                    stats["errores"] += 1
                    continue

                if tmp.stat().st_size >= st.st_size:
                    # Recomprimir no compensa: el original entra en la biblioteca tal cual
                    tmp.unlink()
                    reservados.discard(str(destino_video).lower())
                    final = nombre_libre(destino / carpeta_rel, base, ruta.suffix.lower(),
                                         reservados)
                    copiar_atomico(ruta, final)
                    original_rel, accion = None, "SIN_CAMBIOS"
                    print(f"{prefijo} SIN CAMBIOS  {rel}  ->  {carpeta_rel}/{final.name}"
                          "  (ya estaba bien comprimido)")
                else:
                    os.replace(tmp, destino_video)
                    final = destino_video
                    original_rel, accion = None, "OK"
                    if opciones.conservar_originales:
                        original = nombre_libre(carpeta_originales / carpeta_rel, ruta.stem,
                                                ruta.suffix, reservados)
                        original.parent.mkdir(parents=True, exist_ok=True)
                        copiar_atomico(ruta, original)
                        original_rel = original.relative_to(destino).as_posix()
                    print(f"{prefijo} OK  {rel}  ->  {carpeta_rel}/{final.name}{cambio}"
                          f"  ({formato_bytes(st.st_size)} -> "
                          f"{formato_bytes(final.stat().st_size)})")

                despues = final.stat().st_size
                destino_rel = final.relative_to(destino).as_posix()
                catalogo.registrar(
                    hash=digest, tipo="video", origen=str(ruta), tamano=st.st_size,
                    mtime_ns=st.st_mtime_ns, destino=destino_rel, original=original_rel,
                    fecha=fecha.isoformat(), fuente_fecha=fuente,
                    bytes_antes=st.st_size, bytes_despues=despues)
                informe.anotar(accion, ruta, destino_rel, fecha, fuente, st.st_size, despues)
                vistos[digest] = rel
                stats["procesados"] += 1
                stats["sin_cambios"] += accion == "SIN_CAMBIOS"
                stats["bytes_antes"] += st.st_size
                stats["bytes_despues"] += despues

            except KeyboardInterrupt:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)
                print("\nInterrumpido. El vídeo en curso se ha descartado; "
                      "vuelve a ejecutar para continuar.")
                raise
            except Exception as exc:
                print(f"{prefijo} ERROR en {rel}: {exc}")
                informe.anotar("ERROR", ruta, detalle=str(exc))
                stats["errores"] += 1

    imprimir_resumen(stats, "vídeos", simular,
                     carpeta_originales if opciones.conservar_originales else None,
                     informe.ruta if informe.filas else None)
    return stats
