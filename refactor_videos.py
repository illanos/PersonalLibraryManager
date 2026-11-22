#!/usr/bin/env python3
"""
organizador_videos.py
---------------------
Organiza, renombrea y comprime vídeos (requiere FFmpeg instalado):

  1. Lee la fecha de grabación de los metadatos del vídeo
     (creation_time > fecha de modificación del archivo).
  2. Renombra cada vídeo como AAAAMMDD_HHMMSS.mp4 (o .webm);
     si ya existe ese nombre, añade _01, _02, ...
  3. Organiza los vídeos en carpetas Año/Mes (ej.: 2024/05-Mayo).
  4. Recodifica a un formato homogéneo:
       - h264 (por defecto): MP4 con H.264 + AAC. Compatibilidad total,
         buena compresión. El estándar de facto universal.
       - vp9: WebM con VP9 + Opus. 100 % libre de patentes, comprime
         mejor, pero codifica bastante más lento.
  5. Reduce la resolución máxima a 1920 px en el lado largo (opcional).
  6. Mueve los originales sin tocar a una carpeta aparte.
  7. Detecta duplicados por hash MD5.
  8. Si el vídeo re-codificado pesa MÁS que el original (puede pasar
     con vídeos ya bien comprimidos), se conserva el original tal cual.

Requisitos:
    - Python 3.8+
    - FFmpeg accesible en la terminal. En Windows:
        winget install Gyan.FFmpeg
      (o descárgalo de https://ffmpeg.org y añade su carpeta /bin al PATH)

Uso:
    python organizador_videos.py "C:\\Users\\Tu\\Videos"              # H.264, máx 1920
    python organizador_videos.py "C:\\...\\Videos" --simular          # solo muestra qué haría
    python organizador_videos.py "C:\\...\\Videos" --codec vp9        # formato libre WebM
    python organizador_videos.py "C:\\...\\Videos" --max-lado 2560    # conserva hasta 4K->2K
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ----------------------------- Configuración -----------------------------

EXTENSIONES_VIDEO = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v",
    ".mpg", ".mpeg", ".mts", ".m2ts", ".3gp", ".webm", ".flv",
}

CRF_H264 = 23        # calidad H.264 (18 = casi sin pérdida, 28 = muy comprimido)
CRF_VP9 = 32         # equivalente aproximado en VP9
PRESET_H264 = "medium"
AUDIO_KBPS = 128
NOMBRE_ORIGINALES = "originales"

PERFILES = {
    "h264": {"ext": ".mp4",  "crf": CRF_H264},
    "vp9":  {"ext": ".webm", "crf": CRF_VP9},
}

MESES_ES = {
    1: "01-Enero", 2: "02-Febrero", 3: "03-Marzo", 4: "04-Abril",
    5: "05-Mayo", 6: "06-Junio", 7: "07-Julio", 8: "08-Agosto",
    9: "09-Septiembre", 10: "10-Octubre", 11: "11-Noviembre", 12: "12-Diciembre",
}

# ----------------------------- Utilidades ------------------------------

def hash_archivo(ruta: Path) -> str:
    h = hashlib.md5()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def sondear(ruta: Path):
    """Devuelve (info) con fecha y dimensiones usando ffprobe, o None si falla."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(ruta),
    ]
    try:
        salida = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if salida.returncode != 0:
            return None
        datos = json.loads(salida.stdout)
    except Exception:
        return None

    fecha = None
    # creation_time puede estar en el contenedor o en los streams
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
    """Nuevas dimensiones (pares, requerido por H.264) manteniendo proporción."""
    if not ancho or not alto or max(ancho, alto) <= max_lado:
        return ancho, alto
    factor = max_lado / max(ancho, alto)
    nuevo_w = max(2, round(ancho * factor) - round(ancho * factor) % 2)
    nuevo_h = max(2, round(alto * factor) - round(alto * factor) % 2)
    return nuevo_w, nuevo_h


def nombre_libre(carpeta: Path, base: str, extension: str) -> Path:
    candidata = carpeta / f"{base}{extension}"
    contador = 1
    while candidata.exists():
        candidata = carpeta / f"{base}_{contador:02d}{extension}"
        contador += 1
    return candidata


def dest_folder(fecha: datetime) -> str:
    return f"{fecha.year}/{MESES_ES.get(fecha.month, str(fecha.month))}"


def comando_codificacion(ruta_entrada: Path, ruta_salida: Path, codec: str,
                         ancho: int, alto: int, crf: int) -> list[str]:
    if codec == "h264":
        return [
            "ffmpeg", "-y", "-i", str(ruta_entrada),
            "-map_metadata", "0",
            "-vf", f"scale={ancho}:{alto}",
            "-c:v", "libx264", "-preset", PRESET_H264, "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k",
            "-movflags", "+faststart",
            "-loglevel", "error",
            str(ruta_salida),
        ]
    else:  # vp9
        return [
            "ffmpeg", "-y", "-i", str(ruta_entrada),
            "-map_metadata", "0",
            "-vf", f"scale={ancho}:{alto}",
            "-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0",
            "-row-mt", "1",
            "-c:a", "libopus", "-b:a", f"{AUDIO_KBPS}k",
            "-loglevel", "error",
            str(ruta_salida),
        ]

# ----------------------------- Procesamiento ---------------------------

def procesar(origen: Path, destino: Path, simular: bool, codec: str, max_lado: int):
    perfil = PERFILES[codec]
    extension_salida = perfil["ext"]
    crf = perfil["crf"]
    carpeta_originales = destino / NOMBRE_ORIGINALES

    archivos = sorted(
        p for p in origen.rglob("*")
        if p.is_file()
        and p.suffix.lower() in EXTENSIONES_VIDEO
        and NOMBRE_ORIGINALES not in p.parts
    )

    if not archivos:
        print(f"No se encontraron vídeos en {origen}")
        return

    hashes_vistos: dict[str, str] = {}
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

            # --- duplicados ---
            digerir = hash_archivo(ruta)
            if digerir in hashes_vistos:
                print(f"  DUPLICADO  {ruta.name}  (= {hashes_vistos[digerir]})")
                if not simular:
                    ruta.unlink()
                stats["duplicados"] += 1
                continue

            # --- dimensiones ---
            info = sondear(ruta)
            ancho = info["ancho"] if info else 0
            alto = info["alto"] if info else 0
            nuevo_w, nuevo_h = dimensiones_objetivo(ancho, alto, max_lado)
            escalar = (nuevo_w, nuevo_h) != (ancho, alto) and nuevo_w > 0

            # --- nombre libre ---
            ruta_final.mkdir(parents=True, exist_ok=True)
            destino_video = nombre_libre(ruta_final, base, extension_salida)

            if simular:
                cambio_res = f" ({ancho}x{alto} -> {nuevo_w}x{nuevo_h})" if escalar else ""
                print(f"  {ruta.name}  ->  {subcarpeta_rel}/{destino_video.name}{cambio_res}")
                hashes_vistos[digerir] = ruta.name
                stats["procesados"] += 1
                continue

            # --- conservar original (se mueve, no se copia: ahorra espacio) ---
            carpeta_originales.mkdir(parents=True, exist_ok=True)
            destino_original = carpeta_originales / ruta.name
            i = 1
            while destino_original.exists():
                destino_original = carpeta_originales / f"{ruta.stem}_{i:02d}{ruta.suffix}"
                i += 1
            shutil.move(str(ruta), destino_original)

            # --- codificar ---
            cmd = comando_codificacion(
                destino_original, destino_video, codec,
                nuevo_w or 0, nuevo_h or 0, crf,
            )
            resultado = subprocess.run(cmd, capture_output=True, text=True)

            ok = resultado.returncode == 0 and destino_video.exists()
            if ok and destino_video.stat().st_size >= destino_original.stat().st_size:
                # Re-comprimir no compensa: nos quedamos el original tal cual
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
                # Codificación fallida: devolvemos el original a su sitio
                shutil.move(str(destino_original), ruta)
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

    # ----------------------------- Resumen ------------------------------
    print("\n----------- RESUMEN -----------")
    print(f"Vídeos procesados : {stats['procesados']}")
    print(f"Duplicados        : {stats['duplicados']}")
    print(f"Errores           : {stats['errores']}")
    if not simular and stats["bytes_antes"]:
        antes_gb = stats["bytes_antes"] / (1024 ** 3)
        despues_gb = stats["bytes_despues"] / (1024 ** 3)
        ahorro = (1 - stats["bytes_despues"] / stats["bytes_antes"]) * 100
        print(f"Peso original     : {antes_gb:.2f} GB")
        print(f"Peso optimizado   : {despues_gb:.2f} GB  (ahorro {ahorro:.0f} %)")
        print(f"Originales en     : {carpeta_originales}")


def main():
    parser = argparse.ArgumentParser(description="Organiza, renombra y comprime vídeos.")
    parser.add_argument("origen", type=Path, help="Carpeta con los vídeos a procesar")
    parser.add_argument("--destino", type=Path, default=None,
                        help="Carpeta destino (por defecto: <origen>_organizados)")
    parser.add_argument("--simular", action="store_true",
                        help="Muestra qué haría sin modificar nada")
    parser.add_argument("--codec", choices=["h264", "vp9"], default="h264",
                        help="h264 = MP4 universal | vp9 = WebM totalmente libre")
    parser.add_argument("--max-lado", type=int, default=1920,
                        help="Resolución máxima del lado largo en px (1920 = Full HD)")
    args = parser.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("FFmpeg no está disponible en la terminal. Instálalo con:\n"
                 "    winget install Gyan.FFmpeg\n"
                 "y abre una terminal nueva antes de volver a ejecutar.")

    origen = args.origen.resolve()
    if not origen.is_dir():
        sys.exit(f"La carpeta de origen no existe: {origen}")

    destino = (args.destino or origen.with_name(origen.name + "_organizados")).resolve()
    destino.mkdir(parents=True, exist_ok=True)
    print(f"Origen  : {origen}\nDestino : {destino}\n")

    if origen == destino or origen in destino.parents:
        sys.exit("El destino no puede estar dentro del origen ni coincidir con él.")

    procesar(origen, destino, args.simular, args.codec, args.max_lado)


if __name__ == "__main__":
    main()
