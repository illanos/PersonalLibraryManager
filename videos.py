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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from catalogo import Catalogo, Informe
from clasificacion import carpeta_destino, categoria
from danados import RegistroDanados, diagnosticar, problema_de_excepcion
from media_utils import (
    NOMBRE_ORIGINALES, copiar_atomico, fecha_desde_nombre, fecha_mtime, fecha_y_nombre,
    formato_bytes, hash_archivo,
    imprimir, imprimir_resumen, listar_archivos, nombre_libre, nuevas_estadisticas,
    parsear_fecha_iso, progreso, ruta_temporal, subcarpeta_fecha,
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
    hilos: int = 1           # vídeos codificándose a la vez
    hw: str = "no"           # aceleración por hardware: auto | nvenc | qsv | amf | no


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


# ----------------------------- Aceleración por hardware -----------------------------

# Codificadores de la GPU por familia y códec (VP9 por hardware apenas existe: software)
CODIFICADORES_HW = {
    "nvenc": {"h264": "h264_nvenc", "h265": "hevc_nvenc"},   # NVIDIA
    "qsv": {"h264": "h264_qsv", "h265": "hevc_qsv"},         # Intel Quick Sync
    "amf": {"h264": "h264_amf", "h265": "hevc_amf"},         # AMD
}
ORDEN_AUTO = ("nvenc", "qsv", "amf")
_cache_hw = {}
_lock_hw = threading.Lock()


def codificadores_ffmpeg() -> set:
    """Nombres de los codificadores que trae el FFmpeg instalado (`ffmpeg -encoders`)."""
    with _lock_hw:
        if "lista" not in _cache_hw:
            try:
                salida = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30,
                    stdin=subprocess.DEVNULL).stdout
            except (OSError, subprocess.TimeoutExpired):
                salida = ""
            _cache_hw["lista"] = {p[1] for p in (l.split() for l in salida.splitlines())
                                  if len(p) > 1 and len(p[0]) == 6}
        return _cache_hw["lista"]


def codificador_funciona(nombre: str) -> bool:
    """Que FFmpeg lo liste no basta (puede no haber GPU o driver): prueba 1 fotograma."""
    with _lock_hw:
        if nombre in _cache_hw:
            return _cache_hw[nombre]
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi",
           "-i", "color=c=black:s=256x256:d=0.2", "-frames:v", "3", "-c:v", nombre,
           "-f", "null", "-"]
    try:
        ok = subprocess.run(cmd, capture_output=True, timeout=60,
                            stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    with _lock_hw:
        _cache_hw[nombre] = ok
    return ok


def detectar_hw() -> list:
    """Familias de aceleración que funcionan en este equipo, p. ej. ['nvenc']."""
    disponibles = codificadores_ffmpeg()
    return [familia for familia in ORDEN_AUTO
            if CODIFICADORES_HW[familia]["h264"] in disponibles
            and codificador_funciona(CODIFICADORES_HW[familia]["h264"])]


def elegir_hw(preferencia: str, codec: str):
    """(familia o None, aviso). 'no' = software; 'auto' = la primera que funcione."""
    if preferencia in (None, "", "no"):
        return None, ""
    if codec not in ("h264", "h265"):
        return None, f"{codec.upper()} no se codifica por hardware: se usa el software"
    candidatas = ORDEN_AUTO if preferencia == "auto" else (preferencia,)
    disponibles = codificadores_ffmpeg()
    for familia in candidatas:
        nombre = CODIFICADORES_HW[familia][codec]
        if nombre in disponibles and codificador_funciona(nombre):
            return familia, ""
    if preferencia == "auto":
        return None, "no hay aceleración por hardware disponible: se usa el software"
    return None, (f"{preferencia} no está disponible en este FFmpeg o en esta GPU: "
                  "se usa el software")


def argumentos_hw(familia: str, codec: str, calidad: int) -> list:
    """Parámetros de vídeo del codificador por hardware, con calidad constante aproximada."""
    nombre = CODIFICADORES_HW[familia][codec]
    q = str(calidad)
    if familia == "nvenc":
        args = ["-c:v", nombre, "-preset", "p5", "-rc", "vbr", "-cq", q, "-b:v", "0",
                "-pix_fmt", "yuv420p"]
    elif familia == "qsv":
        args = ["-c:v", nombre, "-global_quality", q, "-pix_fmt", "nv12"]
    else:   # amf
        args = ["-c:v", nombre, "-quality", "balanced", "-rc", "cqp",
                "-qp_i", q, "-qp_p", q, "-pix_fmt", "nv12"]
    if codec == "h265":
        args += ["-tag:v", "hvc1"]
    return args


def comando_codificacion(entrada: Path, salida: Path, opciones: OpcionesVideos,
                         hw: str = None) -> list:
    perfil = PERFILES[opciones.codec]
    crf = opciones.crf if opciones.crf is not None else perfil["crf"]
    if hw:
        video = argumentos_hw(hw, opciones.codec, crf)
    else:
        video = [a.replace("{preset}", opciones.preset) for a in perfil["video"]]
        video += ["-crf", str(crf)]
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(entrada),
        "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0",
        "-vf", filtro_escala(opciones.max_lado),
        *video, *perfil["audio"], *perfil["extra"],
        "-loglevel", "error", "-progress", "pipe:1", "-nostats",
        "-f", perfil["formato"], str(salida),
    ]


def _mostrar_progreso(etiqueta: str, porcentaje: float):
    if etiqueta and sys.stdout.isatty():
        sys.stdout.write(f"\r{etiqueta}  {porcentaje:5.1f} %")
        sys.stdout.flush()


def _borrar_progreso(etiqueta: str):
    if etiqueta and sys.stdout.isatty():
        sys.stdout.write("\r" + " " * (len(etiqueta) + 10) + "\r")
        sys.stdout.flush()


_procesos = set()            # FFmpeg en marcha (para matarlos todos si se interrumpe)
_lock_procesos = threading.Lock()


def detener_ffmpeg():
    with _lock_procesos:
        for proceso in list(_procesos):
            try:
                proceso.kill()
            except OSError:
                pass


def ejecutar_ffmpeg(cmd: list, duracion: float = 0, etiqueta: str = "", video: str = ""):
    """Ejecuta FFmpeg mostrando el porcentaje (si hay etiqueta). Devuelve (ok, error).

    Con `video` (ruta relativa), además avisa del porcentaje al panel web.
    Si se interrumpe (Ctrl+C), mata FFmpeg antes de propagar la interrupción.
    """
    with tempfile.TemporaryFile() as errores:
        proceso = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errores,
                                   stdin=subprocess.DEVNULL, text=True,
                                   encoding="utf-8", errors="replace")
        with _lock_procesos:
            _procesos.add(proceso)
        ultimo = -1
        try:
            for linea in proceso.stdout:
                clave, _, valor = linea.strip().partition("=")
                # out_time_ms está en microsegundos (error histórico de FFmpeg)
                if clave in ("out_time_us", "out_time_ms") and valor.isdigit() and duracion > 0:
                    porcentaje = min(100.0, int(valor) / 1e6 / duracion * 100)
                    _mostrar_progreso(etiqueta, porcentaje)
                    if video and int(porcentaje) != ultimo:
                        ultimo = int(porcentaje)
                        progreso("video", "videos", archivo=video, porcentaje=ultimo)
            proceso.wait()
        except BaseException:
            proceso.kill()
            proceso.wait()
            raise
        finally:
            with _lock_procesos:
                _procesos.discard(proceso)
            _borrar_progreso(etiqueta)
            if video:
                progreso("video_fin", "videos", archivo=video)
        errores.seek(0)
        mensaje = errores.read().decode("utf-8", "replace").strip()
    return proceso.returncode == 0, mensaje


# ----------------------------- Procesamiento -----------------------------

@dataclass
class _Trabajo:
    ruta: Path
    rel: Path
    st: os.stat_result
    digest: str
    info: dict
    fecha: object
    fuente: str
    base: str
    carpeta_rel: str
    destino: Path
    cambio: str
    tmp: Path = None
    hw_usado: str = None
    aviso_hw: str = ""


def _codificar(t: _Trabajo, opciones: OpcionesVideos, hw: str, etiqueta: str):
    """Codifica (en un hilo). Si el hardware falla, repite por software. (ok, error)."""
    t.destino.parent.mkdir(parents=True, exist_ok=True)
    t.tmp = ruta_temporal(t.destino)
    duracion = t.info.get("duracion", 0)
    video = t.rel.as_posix()
    if hw:
        ok, error = ejecutar_ffmpeg(comando_codificacion(t.ruta, t.tmp, opciones, hw),
                                    duracion, etiqueta, video)
        if ok and t.tmp.exists() and t.tmp.stat().st_size > 0:
            t.hw_usado = hw
            return ok, error
        t.tmp.unlink(missing_ok=True)
        ultima = (error or "sin salida").splitlines()[-1][:120] if error else "sin salida"
        t.aviso_hw = f"{hw} falló ({ultima}); repetido por software"
    return ejecutar_ffmpeg(comando_codificacion(t.ruta, t.tmp, opciones), duracion, etiqueta,
                           video)


def procesar_videos(origen: Path, destino: Path, simular: bool,
                    opciones: OpcionesVideos = None) -> dict:
    """Recodifica y organiza. El origen solo se lee: nunca se mueve, modifica ni borra.

    - Codificación correcta y más ligera: la versión nueva entra en la biblioteca (y, con
      `conservar_originales`, una copia del original en originales/Año/Mes).
    - Codificación correcta pero no más ligera: se copia el original a la biblioteca tal cual.
    - Error o interrupción: no queda ningún archivo a medias en el destino.

    Primero se analiza todo (rápido, en orden) y luego se codifica con `opciones.hilos`
    vídeos a la vez, por hardware si `opciones.hw` lo pide y está disponible.
    """
    opciones = opciones or OpcionesVideos()
    perfil = PERFILES[opciones.codec]
    carpeta_originales = destino / NOMBRE_ORIGINALES
    stats = nuevas_estadisticas()

    archivos = listar_archivos(origen, EXTENSIONES_VIDEO)
    if not archivos:
        print(f"No se encontraron vídeos en {origen}")
        return stats

    hilos = max(1, opciones.hilos or 1)
    hw, aviso_hw = elegir_hw(opciones.hw, opciones.codec)   # solo consulta FFmpeg
    motor = f"hardware {hw}" if hw else "software"
    print(f"\n{'SIMULACIÓN' if simular else 'PROCESANDO'} — {len(archivos)} vídeo(s)"
          f" — codec: {opciones.codec.upper()} ({motor}), "
          f"máx. {opciones.max_lado or 'sin límite'} px — {hilos} a la vez\n")
    if aviso_hw:
        print(f"AVISO: {aviso_hw}\n")

    reservados, vistos, trabajos = set(), {}, []
    danados = RegistroDanados(destino, origen, "videos", simular)

    def danado(ruta, st, problema, detalle, conocido=False):
        imprimir(f"  DAÑADO     {ruta.relative_to(origen)}  ({problema}: {detalle})")
        danados.anotar(ruta, problema, detalle, st.st_size, conocido)
        if not conocido:
            informe.anotar("DANADO", ruta, detalle=f"{problema}: {detalle}")
            catalogo.descartar(ruta, st.st_size, st.st_mtime_ns, "video", "danado",
                               problema, detalle)
        stats["danados"] += 1

    with Catalogo(destino, simular) as catalogo, Informe(destino, "videos", simular) as informe:
        # Fase 1: qué hay que codificar y con qué nombre (en orden, sin codificar nada)
        for n, ruta in enumerate(archivos, 1):
            rel = ruta.relative_to(origen)
            prefijo = f"  [{n}/{len(archivos)}]"
            progreso("avance", "videos", paso="Analizando", hecho=n, total=len(archivos),
                     archivo=rel.as_posix())
            try:
                st = ruta.stat()
                fila = catalogo.buscar_por_origen(ruta, st)
                digest = None
                if fila is None:
                    descarte = catalogo.buscar_descarte(ruta, st)
                    if descarte is not None and descarte["motivo"] == "danado":
                        danado(ruta, st, descarte["problema"], descarte["detalle"], True)
                        continue
                    diagnostico = diagnosticar(ruta, st.st_size)
                    if diagnostico:
                        danado(ruta, st, *diagnostico)
                        continue
                    digest = hash_archivo(ruta)
                    fila = catalogo.buscar_por_hash(digest)
                if fila is not None:
                    stats["ya_importados"] += 1
                    continue
                if digest in vistos:
                    imprimir(f"{prefijo} DUPLICADO  {rel}  (igual que {vistos[digest]})")
                    informe.anotar("DUPLICADO", ruta, detalle=f"igual que {vistos[digest]}")
                    stats["duplicados"] += 1
                    continue
                vistos[digest] = rel

                info = sondear(ruta) or {}
                fecha, fuente, base = fecha_y_nombre(ruta, *fecha_video(ruta, info))
                cat = categoria(rel)
                carpeta_rel = carpeta_destino(fecha, "" if cat == "captura" else cat, "video")
                destino_video = nombre_libre(destino / carpeta_rel, base, perfil["ext"],
                                             reservados)
                ancho, alto = info.get("ancho", 0), info.get("alto", 0)
                nuevo = dimensiones_objetivo(ancho, alto, opciones.max_lado)
                cambio = f"  ({ancho}x{alto} -> {nuevo[0]}x{nuevo[1]})" \
                    if ancho and nuevo != (ancho, alto) else ""

                if simular:
                    imprimir(f"{prefijo} {rel}  ->  {carpeta_rel}/{destino_video.name}{cambio}"
                             f"  [fecha: {fuente}]")
                    stats["procesados"] += 1
                    continue
                trabajos.append(_Trabajo(ruta, rel, st, digest, info, fecha, fuente, base,
                                         carpeta_rel, destino_video, cambio))
            except KeyboardInterrupt:
                print("\nInterrumpido antes de codificar nada; vuelve a ejecutar para continuar.")
                raise
            except Exception as exc:
                imprimir(f"{prefijo} ERROR en {rel}: {exc}")
                informe.anotar("ERROR", ruta, detalle=str(exc))
                stats["errores"] += 1

        # Fase 2: codificación (varios a la vez con --hilos-video)
        pool = ThreadPoolExecutor(hilos)
        if trabajos:
            progreso("avance", "videos", paso="Codificando", hecho=0, total=len(trabajos))
        try:
            futuros = {}
            for t in trabajos:
                etiqueta = f"  codificando {t.rel}" if hilos == 1 else ""
                futuros[pool.submit(_codificar, t, opciones, hw, etiqueta)] = t
            for n, futuro in enumerate(as_completed(futuros), 1):
                t = futuros[futuro]
                prefijo = f"  [{n}/{len(trabajos)}]"
                progreso("avance", "videos", paso="Codificando", hecho=n, total=len(trabajos),
                         archivo=t.rel.as_posix())
                try:
                    ok, error = futuro.result()
                    _terminar(t, ok, error, prefijo, destino, carpeta_originales, opciones,
                              reservados, catalogo, informe, stats, danado)
                except Exception as exc:
                    if t.tmp:
                        t.tmp.unlink(missing_ok=True)
                    imprimir(f"{prefijo} ERROR en {t.rel}: {exc}")
                    informe.anotar("ERROR", t.ruta, detalle=str(exc))
                    stats["errores"] += 1
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            detener_ffmpeg()
            pool.shutdown(wait=True)
            for t in trabajos:
                if t.tmp:
                    t.tmp.unlink(missing_ok=True)
            print("\nInterrumpido. Los vídeos en curso se han descartado; "
                  "vuelve a ejecutar para continuar.")
            raise
        finally:
            pool.shutdown(wait=True)

    imprimir_resumen(stats, "vídeos", simular,
                     carpeta_originales if opciones.conservar_originales else None,
                     informe.ruta if informe.filas else None)
    if stats.get("por_hardware"):
        print(f"{'Codificados por hardware':<28}: {stats['por_hardware']}")
    if stats.get("hw_fallidos"):
        print(f"{'Hardware falló (software)':<28}: {stats['hw_fallidos']}")
    danados.cerrar()
    return stats


def _terminar(t: _Trabajo, ok, error, prefijo, destino, carpeta_originales, opciones,
              reservados, catalogo, informe, stats, danado):
    """Tras codificar (en el hilo principal): decide qué entra en la biblioteca y lo anota."""
    tmp, ruta, rel, st = t.tmp, t.ruta, t.rel, t.st
    if t.aviso_hw:
        imprimir(f"{prefijo} aviso: {t.aviso_hw}")
        stats["hw_fallidos"] = stats.get("hw_fallidos", 0) + 1
    if not ok or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        detalle = (error or "FFmpeg no generó salida").splitlines()[-1][:300]
        problema = problema_de_excepcion(Exception(error or ""))
        if problema:
            danado(ruta, st, problema, detalle)
            return
        imprimir(f"{prefijo} ERROR  {rel}: {detalle}")
        informe.anotar("ERROR", ruta, detalle=detalle)
        stats["errores"] += 1
        return

    if tmp.stat().st_size >= st.st_size:
        # Recomprimir no compensa: el original entra en la biblioteca tal cual
        tmp.unlink()
        reservados.discard(str(t.destino).lower())
        final = nombre_libre(destino / t.carpeta_rel, t.base, ruta.suffix.lower(), reservados)
        copiar_atomico(ruta, final)
        original_rel, accion = None, "SIN_CAMBIOS"
        imprimir(f"{prefijo} SIN CAMBIOS  {rel}  ->  {t.carpeta_rel}/{final.name}"
                 "  (ya estaba bien comprimido)")
    else:
        os.replace(tmp, t.destino)
        final = t.destino
        original_rel, accion = None, "OK"
        if opciones.conservar_originales:
            original = nombre_libre(carpeta_originales / t.carpeta_rel, ruta.stem,
                                    ruta.suffix, reservados)
            original.parent.mkdir(parents=True, exist_ok=True)
            copiar_atomico(ruta, original)
            original_rel = original.relative_to(destino).as_posix()
        if t.hw_usado:
            stats["por_hardware"] = stats.get("por_hardware", 0) + 1
        imprimir(f"{prefijo} OK  {rel}  ->  {t.carpeta_rel}/{final.name}{t.cambio}"
                 f"  ({formato_bytes(st.st_size)} -> {formato_bytes(final.stat().st_size)})"
                 + (f"  [{t.hw_usado}]" if t.hw_usado else ""))

    despues = final.stat().st_size
    destino_rel = final.relative_to(destino).as_posix()
    catalogo.registrar(
        hash=t.digest, tipo="video", origen=str(ruta), tamano=st.st_size,
        mtime_ns=st.st_mtime_ns, destino=destino_rel, original=original_rel,
        fecha=t.fecha.isoformat(), fuente_fecha=t.fuente,
        bytes_antes=st.st_size, bytes_despues=despues)
    informe.anotar(accion, ruta, destino_rel, t.fecha, t.fuente, st.st_size, despues,
                   f"hardware {t.hw_usado}" if t.hw_usado else t.aviso_hw)
    stats["procesados"] += 1
    stats["sin_cambios"] += accion == "SIN_CAMBIOS"
    stats["bytes_antes"] += st.st_size
    stats["bytes_despues"] += despues
