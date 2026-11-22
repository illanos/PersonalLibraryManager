#!/usr/bin/env python3
"""
organizador_fotos.py
--------------------
Organiza, renombrea y optimiza fotografías:

  1. Lee la fecha de origen desde los metadatos EXIF
     (DateTimeOriginal > DateTime > fecha de modificación del archivo).
  2. Renombra cada foto como AAAAMMDD_HHMMSS(.ext); si ya existe ese
     nombre, añade _01, _02, ...
  3. Organiza las fotos en carpetas Año/Mes (ej.: 2024/05-Mayo).
  4. Redimensiona a un máximo de 2560 px en el lado largo manteniendo
     la proporción, y guarda con calidad JPEG alta.
  5. Conserva los originales sin tocar en una carpeta separada.
  6. Detecta duplicados: si un archivo tiene el mismo hash MD5 que otro
     ya procesado, no se vuelve a copiar.

Requisitos:
    pip install Pillow

Uso:
    python organizador_fotos.py /ruta/a/tus/fotos            # procesa de verdad
    python organizador_fotos.py /ruta/a/tus/fotos --simular  # solo muestra qué haría
"""

import argparse
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("Falta la librería Pillow. Instálala con:  pip install Pillow")

# ----------------------------- Configuración -----------------------------

EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff", ".bmp", ".gif"}
MAX_LADO = 2560          # píxeles máximos en el lado largo
CALIDAD_JPEG = 88        # calidad de guardado (80-92 = buen equilibrio)
FORMATO_FINAL = "JPEG"   # todas las salidas se convierten a JPG
NOMBRE_ORIGINALES = "originales"

MESES_ES = {
    1: "01-Enero", 2: "02-Febrero", 3: "03-Marzo", 4: "04-Abril",
    5: "05-Mayo", 6: "06-Junio", 7: "07-Julio", 8: "08-Agosto",
    9: "09-Septiembre", 10: "10-Octubre", 11: "11-Noviembre", 12: "12-Diciembre",
}

# ----------------------------- Utilidades ------------------------------

def hash_archivo(ruta: Path) -> str:
    """MD5 del contenido del archivo (para detectar duplicados)."""
    h = hashlib.md5()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def obtener_fecha(ruta: Path) -> datetime:
    """Prioridad: EXIF DateTimeOriginal > EXIF DateTime > mtime."""
    try:
        with Image.open(ruta) as im:
            exif = im.getexif()
            if exif:
                # 36867 = DateTimeOriginal, 306 = DateTime
                for tag in (36867, 306):
                    valor = exif.get(tag)
                    if valor:
                        return datetime.strptime(valor.strip(), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass  # sin EXIF o archivo dañado: caemos al mtime
    return datetime.fromtimestamp(ruta.stat().st_mtime)


def nombre_libre(carpeta: Path, base: str, extension: str) -> Path:
    """Devuelve una ruta no ocupada: base.ext, base_01.ext, base_02.ext..."""
    candidata = carpeta / f"{base}{extension}"
    contador = 1
    while candidata.exists():
        candidata = carpeta / f"{base}_{contador:02d}{extension}"
        contador += 1
    return candidata


def dest_folder(fecha: datetime) -> str:
    return f"{fecha.year}/{MESES_ES.get(fecha.month, str(fecha.month))}"

# ----------------------------- Procesamiento ---------------------------

def procesar(origen: Path, destino: Path, simular: bool):
    carpeta_originales = destino / NOMBRE_ORIGINALES

    archivos = sorted(
        p for p in origen.rglob("*")
        if p.is_file()
        and p.suffix.lower() in EXTENSIONES_FOTO
        and NOMBRE_ORIGINALES not in p.parts
    )

    if not archivos:
        print(f"No se encontraron fotos en {origen}")
        return

    hashes_vistos: dict[str, str] = {}
    stats = {"procesadas": 0, "duplicadas": 0, "errores": 0,
             "bytes_antes": 0, "bytes_despues": 0}

    print(f"\n{'SIMULACIÓN' if simular else 'PROCESANDO'} — {len(archivos)} archivo(s)\n")

    for ruta in archivos:
        try:
            fecha = obtener_fecha(ruta)
            base = fecha.strftime("%Y%m%d_%H%M%S")
            extension = ".jpg"  # salida homogénea
            subcarpeta_rel = dest_folder(fecha)
            ruta_final = destino / subcarpeta_rel

            # --- duplicados ---
            digerir = hash_archivo(ruta)
            if digerir in hashes_vistos:
                print(f"  DUPLICADO  {ruta.name}  (= {hashes_vistos[digerir]})")
                if not simular:
                    ruta.unlink()  # o cámbialo por: mover a una carpeta "duplicados"
                stats["duplicadas"] += 1
                continue

            # --- nombre libre ---
            ruta_final.mkdir(parents=True, exist_ok=True)
            destino_archivo = nombre_libre(ruta_final, base, extension)

            # --- conservar original ---
            destino_original = carpeta_originales / ruta.name
            i = 1
            while destino_original.exists():
                destino_original = carpeta_originales / f"{ruta.stem}_{i:02d}{ruta.suffix}"
                i += 1

            if simular:
                print(f"  {ruta.name}  ->  {subcarpeta_rel}/{destino_archivo.name}")
            else:
                shutil.copy2(ruta, destino_original)

                # --- redimensionar y guardar ---
                with Image.open(ruta) as im:
                    im = ImageOps.exif_transpose(im)  # respeta orientación
                    ancho, alto = im.size
                    if max(ancho, alto) > MAX_LADO:
                        factor = MAX_LADO / max(ancho, alto)
                        im = im.resize(
                            (round(ancho * factor), round(alto * factor)),
                            Image.LANCZOS,
                        )
                    # RGBA -> RGB antes de guardar como JPEG
                    if im.mode in ("RGBA", "P", "LA"):
                        fondo = Image.new("RGB", im.size, (255, 255, 255))
                        fondo.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
                        im = fondo
                    elif im.mode != "RGB":
                        im = im.convert("RGB")

                    exif_bytes = im.info.get("exif") if hasattr(im, "info") else None
                    kwargs = {"quality": CALIDAD_JPEG, "optimize": True}
                    if exif_bytes:
                        kwargs["exif"] = exif_bytes
                    im.save(destino_archivo, FORMATO_FINAL, **kwargs)

                stats["bytes_antes"] += ruta.stat().st_size
                stats["bytes_despues"] += destino_archivo.stat().st_size
                print(f"  OK  {ruta.name}  ->  {subcarpeta_rel}/{destino_archivo.name}")

            hashes_vistos[digerir] = ruta.name
            stats["procesadas"] += 1

        except Exception as exc:
            print(f"  ERROR en {ruta.name}: {exc}")
            stats["errores"] += 1

    # ----------------------------- Resumen ------------------------------
    print("\n----------- RESUMEN -----------")
    print(f"Fotos procesadas : {stats['procesadas']}")
    print(f"Duplicados       : {stats['duplicadas']}")
    print(f"Errores          : {stats['errores']}")
    if not simular and stats["bytes_antes"]:
        antes_mb = stats["bytes_antes"] / (1024 * 1024)
        despues_mb = stats["bytes_despues"] / (1024 * 1024)
        ahorro = (1 - stats["bytes_despues"] / stats["bytes_antes"]) * 100
        print(f"Peso original    : {antes_mb:.1f} MB")
        print(f"Peso optimizado  : {despues_mb:.1f} MB  (ahorro {ahorro:.0f} %)")
        print(f"Originales guardados en: {carpeta_originales}")


def main():
    parser = argparse.ArgumentParser(description="Organiza, renombra y optimiza fotos.")
    parser.add_argument("origen", type=Path, help="Carpeta con las fotos a procesar")
    parser.add_argument("--destino", type=Path, default=None,
                        help="Carpeta destino (por defecto: <origen>_organizadas)")
    parser.add_argument("--simular", action="store_true",
                        help="Muestra qué haría sin modificar nada")
    args = parser.parse_args()

    origen = args.origen.resolve()
    if not origen.is_dir():
        sys.exit(f"La carpeta de origen no existe: {origen}")

    destino = (args.destino or origen.with_name(origen.name + "_organizadas")).resolve()
    destino.mkdir(parents=True, exist_ok=True)
    print(f"Origen  : {origen}\nDestino : {destino}\n")

    if origen == destino or origen in destino.parents:
        sys.exit("El destino no puede estar dentro del origen ni coincidir con él.")

    procesar(origen, destino, args.simular)


if __name__ == "__main__":
    main()
