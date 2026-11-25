"""Copia de seguridad del cuaderno en un ZIP.

Lleva la base de datos (copiada con la API de copias de SQLite, así vale aunque el programa
esté abierto), todos los adjuntos y `notas.json`, legible sin este programa. Para
restaurarla se descomprime en una carpeta vacía y se abre con `--cuaderno`.
"""

import contextlib
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from . import adjuntos as adj
from .cuaderno import ARCHIVO_BD, Cuaderno
from .errores import ErrorNotas

CARPETA_COPIAS = "copias"
LEEME = """Copia de seguridad de Notas.

Para restaurarla: descomprime este ZIP en una carpeta vacía y ábrela con

    python -m notas abrir --cuaderno "<esa carpeta>"

notas.json tiene todas las notas en texto, por si algún día quieres leerlas sin el
programa; los archivos que cita están en adjuntos/.
"""


def nombre_copia(ahora: datetime = None) -> str:
    return f"notas_{ahora or datetime.now():%Y%m%d_%H%M%S}.zip"


def crear_copia(cuaderno: Cuaderno, destino: Path = None) -> Path:
    """Crea el ZIP (por defecto en <cuaderno>/copias/) y devuelve su ruta."""
    destino = Path(destino) if destino else cuaderno.carpeta / CARPETA_COPIAS / nombre_copia()
    if destino.is_dir():
        destino = destino / nombre_copia()
    if destino.exists():
        raise ErrorNotas(f"Ya existe {destino}: elige otro nombre")
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".part")
    try:
        with open(tmp, "wb") as f:
            escribir_copia(cuaderno, f)
        os.replace(tmp, destino)
    finally:
        tmp.unlink(missing_ok=True)
    return destino


def escribir_copia(cuaderno: Cuaderno, flujo):
    """Escribe el ZIP de la copia en un archivo binario ya abierto."""
    with tempfile.TemporaryDirectory() as carpeta:
        copia_bd = Path(carpeta) / ARCHIVO_BD
        with contextlib.closing(sqlite3.connect(cuaderno.bd, timeout=30)) as origen, \
                contextlib.closing(sqlite3.connect(copia_bd)) as copia:
            origen.backup(copia)
            archivos = [f[0] for f in copia.execute("SELECT archivo FROM adjuntos ORDER BY id")]
        notas = cuaderno.listar("todas") + cuaderno.listar("papelera")
        with zipfile.ZipFile(flujo, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("LEEME.txt", LEEME)
            z.write(copia_bd, ARCHIVO_BD)
            z.writestr("notas.json", json.dumps(notas, ensure_ascii=False, indent=1))
            for relativa in archivos:
                ruta = adj.ruta_segura(cuaderno.carpeta, relativa)
                if ruta.is_file():      # ya vienen comprimidos (JPEG, Opus…): tal cual
                    z.write(ruta, relativa, compress_type=zipfile.ZIP_STORED)
