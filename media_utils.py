"""Utilidades compartidas entre el tratamiento de fotos y de vídeos."""

import hashlib
from datetime import datetime
from pathlib import Path

NOMBRE_ORIGINALES = "originales"

MESES_ES = {
    1: "01-Enero", 2: "02-Febrero", 3: "03-Marzo", 4: "04-Abril",
    5: "05-Mayo", 6: "06-Junio", 7: "07-Julio", 8: "08-Agosto",
    9: "09-Septiembre", 10: "10-Octubre", 11: "11-Noviembre", 12: "12-Diciembre",
}


def hash_archivo(ruta: Path) -> str:
    """MD5 del contenido del archivo (detección de duplicados)."""
    h = hashlib.md5()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def nombre_libre(carpeta: Path, base: str, extension: str) -> Path:
    """Devuelve una ruta no ocupada: base.ext, base_01.ext, base_02.ext..."""
    candidata = carpeta / f"{base}{extension}"
    contador = 1
    while candidata.exists():
        candidata = carpeta / f"{base}_{contador:02d}{extension}"
        contador += 1
    return candidata


def nombre_original_libre(carpeta_originales: Path, ruta: Path) -> Path:
    """Ruta única dentro de la carpeta de originales para este archivo."""
    destino = carpeta_originales / ruta.name
    i = 1
    while destino.exists():
        destino = carpeta_originales / f"{ruta.stem}_{i:02d}{ruta.suffix}"
        i += 1
    return destino


def dest_folder(fecha: datetime) -> str:
    """Subcarpeta relativa Año/Mes, ej.: '2024/05-Mayo'."""
    return f"{fecha.year}/{MESES_ES.get(fecha.month, str(fecha.month))}"


def listar_archivos(origen: Path, extensiones: set) -> list:
    """Archivos con las extensiones dadas, excluyendo la carpeta de originales."""
    return sorted(
        p for p in origen.rglob("*")
        if p.is_file()
        and p.suffix.lower() in extensiones
        and NOMBRE_ORIGINALES not in p.parts
    )


def imprimir_resumen(stats: dict, sustantivo: str, carpeta_originales: Path, simular: bool):
    print("\n----------- RESUMEN -----------")
    print(f"{sustantivo.capitalize()} procesados : {stats['procesados']}")
    print(f"Duplicados               : {stats['duplicados']}")
    print(f"Errores                  : {stats['errores']}")
    if not simular and stats["bytes_antes"]:
        antes = stats["bytes_antes"] / (1024 ** 3)
        despues = stats["bytes_despues"] / (1024 ** 3)
        ahorro = (1 - stats["bytes_despues"] / stats["bytes_antes"]) * 100
        unidad = "GB"
        if antes < 1:
            antes *= 1024
            despues *= 1024
            unidad = "MB"
        print(f"Peso original            : {antes:.1f} {unidad}")
        print(f"Peso optimizado          : {despues:.1f} {unidad}  (ahorro {ahorro:.0f} %)")
        print(f"Originales en            : {carpeta_originales}")
