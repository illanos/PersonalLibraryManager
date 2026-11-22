"""Tratamiento de vídeos: renombrado por fecha, organización y recodificación.

Requiere FFmpeg y ffprobe accesibles en la terminal:
    winget install Gyan.FFmpeg
"""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from media_utils import (
    NOMBRE_ORIGINALES, dest_folder, hash_archivo, imprimir_resumen,
    listar_archivos, nombre_libre, nombre_original_libre,
)

EXTENSIONES_VIDEO = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v",
    ".mpg", ".mpeg", ".mts", ".m2ts", ".3gp", ".webm", ".flv",
}

CRF_H264 = 23
CRF_VP9 = 32
PRESET_H264 = "medium"
AUDIO_KBPS = 128

PERFILES = {
    "h264": {"ext": ".mp4",  "crf": CRF_H264},
    "vp9":  {"ext": ".webm", "crf": CRF_VP9},
}


def sondear(ruta: Path):
    """Fecha (creation_time) y dimensiones vía ffprobe, o None si falla."""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(ruta)]
    try:
        salida = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if salida.returncode != 0:
            return None
        datos = json.loads(salida.stdout)
    except Exception:
        return None

    fecha = None
    candidatos = [datos.get("format", {}).get("tags", {})]
    candidatos += [s.get("tags", {}) for s in datos.get("streams", [])]
    for tags in candidatos:
        crudo = tags.get("creation_time")
        if crudo:
            try:
                fecha = datetime.fromisoformat(crudo.replace("Z", "+00:00"))
                break
            except ValueError:
                pass

    ancho = alto = 0
    for s in datos.get("streams", []):
        if s.get("codec_type") == "video":
            ancho = int(s.get("width") or 0)
            alto = int(s.get("height") or 0)
            break

    return {"fecha": fecha, "ancho": ancho, "alto": alto}


def obtener_fecha(ruta: Path) -> datetime:
    info = sondear(ruta)
    if info and info["fecha"]:
        return info["fecha"]
    return datetime.fromtimestamp(ruta.stat().st_mtime)


def dimensiones_objetivo(ancho: int, alto: int, max_lado: int):
    """Dimensiones pares (requisito de H.264) manteniendo proporción."""
    if not ancho or not alto or max(ancho, alto) <= max_lado:
        return ancho, alto
    factor = max_lado / max(ancho, alto)
    nuevo_w = max(2, round(ancho * factor) - round(ancho * factor) % 2)
    nuevo_h = max(2, round(alto * factor) - round(alto * factor) % 2)
    return nuevo_w, nuevo_h


def comando_codificacion(entrada: Path, salida: Path, codec: str,
                         ancho: int, alto: int, crf: int):
    escala = ["-vf", f"scale={ancho}:{alto}"]
    meta = ["-map_metadata", "0", "-loglevel", "error"]

    if codec == "h264":
        return ["ffmpeg", "-y", "-i", str(entrada), *meta, *escala,
                "-c:v", "libx264", "-preset", PRESET_H264, "-crf", str(crf),
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k",
                "-movflags", "+faststart", str(salida)]
    return ["ffmpeg", "-y", "-i", str(entrada), *meta, *escala,
            "-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0", "-row-mt", "1",
            "-c:a", "libopus", "-b:a", f"{AUDIO_KBPS}k", str(salida)]


def procesar_videos(origen: Path, destino: Path, simular: bool,
                    codec: str = "h264", max_lado: int = 1920):
    perfil = PERFILES[codec]
    extension_salida = perfil["ext"]
    crf = perfil["crf"]
    carpeta_originales = destino / NOMBRE_ORIGINALES
    archivos = listar_archivos(origen, EXTENSIONES_VIDEO)

    if not archivos:
        print(f"No se encontraron vídeos en {origen}")
        return

    hashes_vistos = {}
    stats = {"procesados": 0, "duplicados": 0, "errores": 0,
             "bytes_antes": 0, "bytes_despues": 0}

    print(f"\n{'SIMULACIÓN' if simular else 'PROCESANDO'} — {len(archivos)} vídeo(s)"
          f" — codec: {codec.upper()}, máx. {max_lado} px\n")

    for ruta in archivos:
        try:
            fecha = obtener_fecha(ruta)
            base = fecha.strftime("%Y%m%d_%H%M%S")
            subcarpeta_rel = dest_folder(fecha)
            ruta_final = destino / subcarpeta_rel
            ruta_final.mkdir(parents=True, exist_ok=True)

            digerir = hash_archivo(ruta)
            if digerir in hashes_vistos:
                print(f"  DUPLICADO  {ruta.name}  (= {hashes_vistos[digerir]})")
                if not simular:
                    ruta.unlink()
                stats["duplicados"] += 1
                continue

            info = sondear(ruta)
            ancho = info["ancho"] if info else 0
            alto = info["alto"] if info else 0
            nuevo_w, nuevo_h = dimensiones_objetivo(ancho, alto, max_lado)
            escalar = (nuevo_w, nuevo_h) != (ancho, alto) and nuevo_w > 0

            destino_video = nombre_libre(ruta_final, base, extension_salida)

            if simular:
                cambio = f" ({ancho}x{alto} -> {nuevo_w}x{nuevo_h})" if escalar else ""
                print(f"  {ruta.name}  ->  {subcarpeta_rel}/{destino_video.name}{cambio}")
                hashes_vistos[digerir] = ruta.name
                stats["procesados"] += 1
                continue

            # Conservar original (se mueve: duplicarlo ocuparía demasiado)
            carpeta_originales.mkdir(parents=True, exist_ok=True)
            destino_original = nombre_original_libre(carpeta_originales, ruta)
            shutil.move(str(ruta), destino_original)

            cmd = comando_codificacion(destino_original, destino_video, codec,
                                       nuevo_w or 0, nuevo_h or 0, crf)
            resultado = subprocess.run(cmd, capture_output=True, text=True)

            ok = resultado.returncode == 0 and destino_video.exists()
            if ok and destino_video.stat().st_size >= destino_original.stat().st_size:
                destino_video.unlink(missing_ok=True)
                destino_final = nombre_libre(ruta_final, base, destino_original.suffix)
                shutil.move(str(destino_original), destino_final)
                print(f"  SIN CAMBIOS  {ruta.name} -> {subcarpeta_rel}/{destino_final.name}"
                      "  (ya estaba bien comprimido)")
                antes = despues = destino_final.stat().st_size
            elif ok:
                cambio = f" ({ancho}x{alto}->{nuevo_w}x{nuevo_h})" if escalar else ""
                print(f"  OK  {ruta.name} -> {subcarpeta_rel}/{destino_video.name}{cambio}")
                antes = destino_original.stat().st_size
                despues = destino_video.stat().st_size
            else:
                shutil.move(str(destino_original), ruta)  # restaurar original
                print(f"  ERROR  {ruta.name}: {resultado.stderr.strip()[:200]}")
                stats["errores"] += 1
                continue

            stats["bytes_antes"] += antes
            stats["bytes_despues"] += despues
            hashes_vistos[digerir] = ruta.name
            stats["procesados"] += 1

        except Exception as exc:
            print(f"  ERROR en {ruta.name}: {exc}")
            stats["errores"] += 1

    imprimir_resumen(stats, "vídeos", carpeta_originales, simular)
