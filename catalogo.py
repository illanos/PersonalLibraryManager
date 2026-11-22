"""Catálogo persistente de la biblioteca (SQLite) e informe CSV de cada ejecución.

El catálogo vive en <biblioteca>/.exportador/catalogo.sqlite y permite:
  - importar de forma incremental: lo ya importado no se vuelve a procesar
    (por ejemplo, al volcar el móvil cada mes en la misma carpeta);
  - detectar duplicados entre ejecuciones distintas, no solo dentro de una;
  - saber qué original corresponde a cada archivo optimizado (lo usa la galería).

Si un archivo de la biblioteca se borra a mano, el catálogo deja de considerarlo
importado y la siguiente ejecución lo vuelve a traer: el catálogo nunca hace perder fotos.
"""

import csv
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from media_utils import CARPETA_INTERNA

VERSION_ESQUEMA = 1

ESQUEMA = """
CREATE TABLE IF NOT EXISTS archivos (
    hash          TEXT PRIMARY KEY,   -- MD5 del archivo de origen
    tipo          TEXT NOT NULL,      -- 'foto' | 'video'
    origen        TEXT NOT NULL,      -- ruta absoluta de la que se importó
    tamano        INTEGER NOT NULL,   -- tamaño y mtime del origen: permiten saltar
    mtime_ns      INTEGER NOT NULL,   --   lo ya importado sin volver a leerlo entero
    destino       TEXT NOT NULL,      -- relativo a la biblioteca (con '/')
    original      TEXT,               -- copia del original, relativa, o NULL
    fecha         TEXT,               -- fecha de captura (ISO)
    fuente_fecha  TEXT,               -- exif | metadatos | nombre | archivo
    bytes_antes   INTEGER,
    bytes_despues INTEGER,
    importado     TEXT NOT NULL       -- cuándo se importó (ISO)
);
CREATE INDEX IF NOT EXISTS idx_origen  ON archivos (origen, tamano, mtime_ns);
CREATE INDEX IF NOT EXISTS idx_destino ON archivos (destino);
"""


def ruta_catalogo(biblioteca: Path) -> Path:
    return biblioteca / CARPETA_INTERNA / "catalogo.sqlite"


class Catalogo:
    """Acceso al catálogo, seguro entre hilos. En simulación nunca escribe en disco."""

    def __init__(self, biblioteca: Path, simular: bool = False):
        self.biblioteca = biblioteca
        self.simular = simular
        self._lock = threading.Lock()
        ruta = ruta_catalogo(biblioteca)
        if simular:
            if ruta.exists():
                self._db = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True,
                                           check_same_thread=False)
            else:
                self._db = sqlite3.connect(":memory:", check_same_thread=False)
                self._db.executescript(ESQUEMA)
        else:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(ruta, check_same_thread=False)
            self._db.executescript(ESQUEMA)
            self._db.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
        self._db.row_factory = sqlite3.Row

    # --- consultas ---

    def _vigente(self, fila):
        """La fila solo cuenta si el archivo sigue existiendo en la biblioteca."""
        if fila and (self.biblioteca / fila["destino"]).exists():
            return fila
        return None

    def buscar_por_origen(self, ruta: Path, st):
        """Mismo archivo de origen (ruta, tamaño y fecha) ya importado."""
        with self._lock:
            fila = self._db.execute(
                "SELECT * FROM archivos WHERE origen = ? AND tamano = ? AND mtime_ns = ?",
                (str(ruta), st.st_size, st.st_mtime_ns)).fetchone()
        return self._vigente(fila)

    def buscar_por_hash(self, digest: str):
        with self._lock:
            fila = self._db.execute(
                "SELECT * FROM archivos WHERE hash = ?", (digest,)).fetchone()
        return self._vigente(fila)

    # --- escritura ---

    def registrar(self, **campos):
        if self.simular:
            return
        campos.setdefault("importado", datetime.now().isoformat(timespec="seconds"))
        columnas = ", ".join(campos)
        marcas = ", ".join("?" * len(campos))
        with self._lock:
            self._db.execute(
                f"INSERT OR REPLACE INTO archivos ({columnas}) VALUES ({marcas})",
                tuple(campos.values()))
            self._db.commit()

    def cerrar(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()


def originales_por_destino(biblioteca: Path) -> dict:
    """{destino_relativo: original_relativo} según el catálogo (vacío si no hay)."""
    ruta = ruta_catalogo(biblioteca)
    if not ruta.exists():
        return {}
    try:
        db = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
        try:
            filas = db.execute(
                "SELECT destino, original FROM archivos WHERE original IS NOT NULL").fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return {}
    return dict(filas)


class Informe:
    """CSV con una fila por archivo tratado, en <biblioteca>/.exportador/informes/.

    Separador ';' y UTF-8 con BOM para que Excel en español lo abra bien.
    """

    CAMPOS = ["hora", "accion", "origen", "destino", "fecha_captura", "fuente_fecha",
              "bytes_antes", "bytes_despues", "detalle"]

    def __init__(self, biblioteca: Path, tipo: str, simular: bool = False):
        self.ruta = None
        if not simular:
            marca = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.ruta = biblioteca / CARPETA_INTERNA / "informes" / f"{tipo}_{marca}.csv"
        self._archivo = None
        self._escritor = None
        self._lock = threading.Lock()
        self.filas = 0

    def anotar(self, accion: str, origen="", destino="", fecha=None, fuente="",
               bytes_antes="", bytes_despues="", detalle=""):
        if self.ruta is None:
            return
        with self._lock:
            if self._archivo is None:
                self.ruta.parent.mkdir(parents=True, exist_ok=True)
                self._archivo = open(self.ruta, "w", newline="", encoding="utf-8-sig")
                self._escritor = csv.writer(self._archivo, delimiter=";")
                self._escritor.writerow(self.CAMPOS)
            self._escritor.writerow([
                datetime.now().strftime("%H:%M:%S"), accion, origen, destino,
                fecha.isoformat(sep=" ") if fecha else "", fuente,
                bytes_antes, bytes_despues, detalle,
            ])
            self._archivo.flush()
            self.filas += 1

    def cerrar(self):
        if self._archivo:
            self._archivo.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()
