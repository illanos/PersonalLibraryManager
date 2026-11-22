"""Tratamiento de fotos: renombrado por fecha, organización y optimización.

Requiere: pip install Pillow
"""

import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from media_utils import (
    NOMBRE_ORIGINALES, dest_folder, hash_archivo, imprimir_resumen,
    listar_archivos, nombre_libre, nombre_original_libre,
)

EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff", ".bmp", ".gif"}

MAX_LADO = 2560          # píxeles máximos en el lado largo
CALIDAD_JPEG = 88        # 80-92 = buen equilibrio calidad/peso
FORMATO_FINAL = "JPEG"


def obtener_fecha(ruta: Path) -> datetime:
    """Prioridad: EXIF DateTimeOriginal > EXIF DateTime > mtime."""
    try:
        with Image.open(ruta) as im:
            exif = im.getexif()
            if exif:
                for tag in (36867, 306):  # DateTimeOriginal, DateTime
                    valor = exif.get(tag)
                    if valor:
                        return datetime.strptime(valor.strip(), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return datetime.fromtimestamp(ruta.stat().st_mtime)


def guardar_optimizada(ruta: Path, destino: Path):
    with Image.open(ruta) as im:
        im = ImageOps.exif_transpose(im)  # respeta orientación EXIF
        ancho, alto = im.size
        if max(ancho, alto) > MAX_LADO:
            factor = MAX_LADO / max(ancho, alto)
            im = im.resize((round(ancho * factor), round(alto * factor)), Image.LANCZOS)

        if im.mode in ("RGBA", "P", "LA"):
            fondo = Image.new("RGB", im.size, (255, 255, 255))
            rgba = im.convert("RGBA")
            fondo.paste(rgba, mask=rgba.split()[-1])
            im = fondo
        elif im.mode != "RGB":
            im = im.convert("RGB")

        kwargs = {"quality": CALIDAD_JPEG, "optimize": True}
        exif_bytes = im.info.get("exif")
        if exif_bytes:
            kwargs["exif"] = exif_bytes
        im.save(destino, FORMATO_FINAL, **kwargs)


def procesar_fotos(origen: Path, destino: Path, simular: bool):
    carpeta_originales = destino / NOMBRE_ORIGINALES
    archivos = listar_archivos(origen, EXTENSIONES_FOTO)

    if not archivos:
        print(f"No se encontraron fotos en {origen}")
        return

    hashes_vistos = {}
    stats = {"procesados": 0, "duplicados": 0, "errores": 0,
             "bytes_antes": 0, "bytes_despues": 0}

    print(f"\n{'SIMULACIÓN' if simular else 'PROCESANDO'} — {len(archivos)} foto(s)\n")

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

            destino_foto = nombre_libre(ruta_final, base, ".jpg")

            if simular:
                print(f"  {ruta.name}  ->  {subcarpeta_rel}/{destino_foto.name}")
            else:
                carpeta_originales.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ruta, nombre_original_libre(carpeta_originales, ruta))
                guardar_optimizada(ruta, destino_foto)
                stats["bytes_antes"] += ruta.stat().st_size
                stats["bytes_despues"] += destino_foto.stat().st_size
                print(f"  OK  {ruta.name}  ->  {subcarpeta_rel}/{destino_foto.name}")

            hashes_vistos[digerir] = ruta.name
            stats["procesados"] += 1

        except Exception as exc:
            print(f"  ERROR en {ruta.name}: {exc}")
            stats["errores"] += 1

    imprimir_resumen(stats, "fotos", carpeta_originales, simular)
