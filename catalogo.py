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

VERSION_ESQUEMA = 2

ESQUEMA = """
CREATE TABLE IF NOT EXISTS archivos (
    hash          TEXT PRIMARY KEY,   -- MD5 del archivo de origen
    tipo          TEXT NOT NULL,      -- 'foto' | 'video' | 'audio'
    origen        TEXT NOT NULL,      -- ruta absoluta de la que se importó
    tamano        INTEGER NOT NULL,   -- tamaño y mtime del origen: permiten saltar
    mtime_ns      INTEGER NOT NULL,   --   lo ya importado sin volver a leerlo entero
    destino       TEXT NOT NULL,      -- relativo a la biblioteca (con '/')
    original      TEXT,               -- copia del original, relativa, o NULL
    fecha         TEXT,               -- fecha de captura (ISO)
    fuente_fecha  TEXT,               -- exif | metadatos | nombre | archivo
    bytes_antes   INTEGER,
    bytes_despues INTEGER,
    importado     TEXT NOT NULL,      -- cuándo se importó (ISO)
    phash         TEXT,               -- hash perceptual (fotos), ver similares.py
    ancho         INTEGER,
    alto          INTEGER
);
CREATE INDEX IF NOT EXISTS idx_origen  ON archivos (origen, tamano, mtime_ns);
CREATE INDEX IF NOT EXISTS idx_destino ON archivos (destino);

-- Archivos del origen que no se importan a propósito: dañados o la peor copia de un
-- grupo de parecidas. Permite no volver a analizarlos mientras no cambien.
CREATE TABLE IF NOT EXISTS descartes (
    origen     TEXT PRIMARY KEY,
    tamano     INTEGER NOT NULL,
    mtime_ns   INTEGER NOT NULL,
    tipo       TEXT NOT NULL,         -- 'foto' | 'video' | 'audio'
    motivo     TEXT NOT NULL,         -- 'danado' | 'parecida'
    problema   TEXT,                  -- vacío | sin cabecera válida | truncado | ilegible
    detalle    TEXT,
    referencia TEXT,                  -- parecida: destino de la copia buena
    fecha      TEXT NOT NULL
);
"""

# Columnas añadidas después de la versión 1 (se crean al abrir un catálogo antiguo)
COLUMNAS_NUEVAS = {"phash": "TEXT", "ancho": "INTEGER", "alto": "INTEGER"}


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
            self._migrar()
            self._db.executescript(ESQUEMA)
            self._db.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
        self._db.row_factory = sqlite3.Row
        self.columnas = {f[1] for f in self._db.execute("PRAGMA table_info(archivos)")}
        self.hay_descartes = bool(self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'descartes'").fetchone())

    def _migrar(self):
        """Añade a un catálogo antiguo las columnas nuevas (sin perder nada)."""
        existentes = {f[1] for f in self._db.execute("PRAGMA table_info(archivos)")}
        if not existentes:
            return
        for columna, tipo in COLUMNAS_NUEVAS.items():
            if columna not in existentes:
                self._db.execute(f"ALTER TABLE archivos ADD COLUMN {columna} {tipo}")
        self._db.commit()

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

    def fotos_con_phash(self) -> list:
        """Fotos ya importadas (y aún en la biblioteca) con su hash perceptual."""
        if "phash" not in self.columnas:
            return []
        with self._lock:
            filas = self._db.execute(
                "SELECT * FROM archivos WHERE tipo = 'foto' AND phash IS NOT NULL").fetchall()
        return [f for f in filas if self._vigente(f)]

    def buscar_descarte(self, ruta: Path, st):
        """Descarte anterior del mismo archivo (sin cambios desde entonces) o None."""
        if not self.hay_descartes:
            return None
        with self._lock:
            return self._db.execute(
                "SELECT * FROM descartes WHERE origen = ? AND tamano = ? AND mtime_ns = ?",
                (str(ruta), st.st_size, st.st_mtime_ns)).fetchone()

    def filas(self, tipo: str = None) -> list:
        with self._lock:
            if tipo:
                return self._db.execute(
                    "SELECT * FROM archivos WHERE tipo = ?", (tipo,)).fetchall()
            return self._db.execute("SELECT * FROM archivos").fetchall()

    # --- escritura ---

    def descartar(self, ruta: Path, tamano: int, mtime_ns: int, tipo: str, motivo: str,
                  problema: str = "", detalle: str = "", referencia: str = None):
        if self.simular:
            return
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO descartes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(ruta), tamano, mtime_ns, tipo, motivo, problema, detalle, referencia,
                 datetime.now().isoformat(timespec="seconds")))
            self._db.commit()

    def olvidar_descarte(self, ruta: Path):
        if self.simular or not self.hay_descartes:
            return
        with self._lock:
            self._db.execute("DELETE FROM descartes WHERE origen = ?", (str(ruta),))
            self._db.commit()

    def cambiar_destino(self, viejo: str, nuevo: str, fecha: str = None, fuente: str = None):
        """Tras mover/renombrar un archivo dentro de la biblioteca."""
        if self.simular:
            return
        with self._lock:
            self._db.execute(
                "UPDATE archivos SET destino = ?, fecha = COALESCE(?, fecha), "
                "fuente_fecha = COALESCE(?, fuente_fecha) WHERE destino = ?",
                (nuevo, fecha, fuente, viejo))
            self._db.commit()

    def registrar(self, **campos):
        if self.simular:
            return
        campos = {k: v for k, v in campos.items()
                  if k in self.columnas or k == "importado"}
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


def info_por_destino(biblioteca: Path) -> dict:
    """{destino_relativo: {original, origen, fuente_fecha}} según el catálogo (vacío si no hay)."""
    ruta = ruta_catalogo(biblioteca)
    if not ruta.exists():
        return {}
    try:
        db = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
        try:
            db.row_factory = sqlite3.Row
            filas = db.execute("SELECT * FROM archivos").fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return {}
    return {f["destino"]: {"original": f["original"], "origen": f["origen"],
                           "fuente_fecha": f["fuente_fecha"]} for f in filas}


class Informe:
    """CSV con una fila por archivo tratado, en <biblioteca>/.exportador/informes/.

    Separador ';' y UTF-8 con BOM para que Excel en español lo abra bien.
    """

    CAMPOS = ["hora", "accion", "origen", "destino", "fecha_captura", "fuente_fecha",
              "bytes_antes", "bytes_despues", "detalle", "parecidas"]

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
               bytes_antes="", bytes_despues="", detalle="", parecidas=""):
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
                bytes_antes, bytes_despues, detalle, parecidas,
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
