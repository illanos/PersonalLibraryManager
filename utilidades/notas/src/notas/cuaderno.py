"""El cuaderno: notas, categorías, búsqueda y papelera, en una carpeta del usuario.

    <cuaderno>/
    ├── notas.sqlite     notas, categorías y qué adjuntos tiene cada una
    ├── adjuntos/        imágenes y notas de voz, por año y mes
    └── copias/          copias de seguridad (ver copia.py)

La carpeta está fuera del repositorio a propósito: son datos personales y no deben
desaparecer al limpiar o borrar una copia del código. Cada operación abre y cierra su
conexión, así que la web y la terminal pueden usar el mismo cuaderno a la vez.

Nada se borra directamente: las notas van a la papelera y los adjuntos quitados se
marcan; solo `vaciar_papelera` y `eliminar` borran de verdad.
"""

import contextlib
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import adjuntos as adj
from .errores import AdjuntoNoValido, Conflicto, ErrorNotas, NoEncontrada

VARIABLE_CUADERNO = "NOTAS_CUADERNO"
ARCHIVO_BD = "notas.sqlite"
COLORES = ("", "coral", "melocoton", "limon", "menta", "cielo", "lavanda", "rosa", "arena")
TIPOS = ("texto", "lista", adj.IMAGEN, adj.VOZ)
PENDIENTE, HECHA = "☐", "☑"  # una línea que empieza así es una casilla; con alguna, es una lista
MAX_TITULO, MAX_TEXTO, MAX_CATEGORIA, MAX_BUSQUEDA = 500, 500_000, 60, 500
SIN_CATEGORIA = 0            # en `listar`, las notas que no tienen ninguna
VACIAR = "VACIAR"            # lo que hay que escribir para vaciar la papelera

VISTAS = {
    "activas": "n.papelera IS NULL AND n.archivada = 0",
    "archivadas": "n.papelera IS NULL AND n.archivada = 1",
    "todas": "n.papelera IS NULL",
    "papelera": "n.papelera IS NOT NULL",
}
ES_LISTA = (f"(instr(char(10) || n.texto, char(10) || '{PENDIENTE}') > 0 "
            f"OR instr(char(10) || n.texto, char(10) || '{HECHA}') > 0)")
ORDENES = {
    "modificada": "n.modificada DESC, n.id DESC",
    "creada": "n.creada DESC, n.id DESC",
    # `busqueda` empieza por el título normalizado: ordena sin distinguir acentos
    "titulo": "n.titulo = '', n.busqueda, n.id DESC",
}

# Cada una lleva un cuaderno de una versión a la siguiente. Las publicadas no se tocan (ya hay
# cuadernos con cada una): para cambiar algo se añade otra al final de MIGRACIONES.
ESQUEMA = """
CREATE TABLE notas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo     TEXT NOT NULL DEFAULT '',
    texto      TEXT NOT NULL DEFAULT '',
    busqueda   TEXT NOT NULL DEFAULT '',     -- título y texto normalizados
    color      TEXT NOT NULL DEFAULT '',
    fijada     INTEGER NOT NULL DEFAULT 0,
    archivada  INTEGER NOT NULL DEFAULT 0,
    papelera   TEXT,                         -- cuándo se mandó a la papelera
    creada     TEXT NOT NULL,                -- fechas en UTC, ISO 8601
    modificada TEXT NOT NULL,
    version    INTEGER NOT NULL DEFAULT 1    -- sube con cada cambio de título o texto
);
CREATE TABLE categorias (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    clave  TEXT NOT NULL UNIQUE              -- nombre normalizado
);
CREATE TABLE notas_categorias (
    nota      INTEGER NOT NULL REFERENCES notas (id) ON DELETE CASCADE,
    categoria INTEGER NOT NULL REFERENCES categorias (id) ON DELETE CASCADE,
    PRIMARY KEY (nota, categoria)
) WITHOUT ROWID;
CREATE INDEX idx_notas_categorias ON notas_categorias (categoria);
CREATE TABLE adjuntos (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    nota     INTEGER NOT NULL REFERENCES notas (id) ON DELETE CASCADE,
    tipo     TEXT NOT NULL CHECK (tipo IN ('imagen', 'voz')),
    archivo  TEXT NOT NULL UNIQUE,           -- ruta relativa al cuaderno, con '/'
    nombre   TEXT NOT NULL,
    clave    TEXT NOT NULL DEFAULT '',       -- nombre normalizado, para buscar
    mime     TEXT NOT NULL,
    bytes    INTEGER NOT NULL,
    duracion REAL,                           -- segundos (notas de voz)
    ancho    INTEGER, alto INTEGER,          -- imágenes
    creado   TEXT NOT NULL,
    quitado  TEXT                            -- cuándo se quitó de la nota
);
CREATE INDEX idx_adjuntos_nota ON adjuntos (nota);
"""
# `origen`: de dónde se importó la nota, para no repetirla. `detalles`: JSON con lo que traía y
# no es texto (enlaces, con quién se compartió, recordatorio…), o nada
IMPORTADAS = """
ALTER TABLE notas ADD COLUMN origen TEXT;
ALTER TABLE notas ADD COLUMN detalles TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX idx_notas_origen ON notas (origen) WHERE origen IS NOT NULL;
"""
MIGRACIONES = (ESQUEMA, IMPORTADAS)
VERSION_BD = len(MIGRACIONES)

# Un término de búsqueda: palabra o "frase exacta", con '-' delante para excluir
_RE_TERMINO = re.compile(r'(-?)(?:"([^"]+)"|([^\s"]+))')


def carpeta_cuaderno(elegida=None) -> Path:
    """La carpeta del cuaderno: la elegida, la de NOTAS_CUADERNO o ~/Notas."""
    valor = elegida or os.environ.get(VARIABLE_CUADERNO)
    return Path(valor).expanduser().resolve() if valor else Path.home() / "Notas"


def normalizar(texto: str) -> str:
    """Sin mayúsculas ni acentos, para buscar y comparar: «Reunión» -> «reunion»."""
    descompuesto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def terminos(buscar: str) -> list:
    """[(excluir, término normalizado)] de lo que escribe el usuario en el buscador."""
    return [(bool(menos), normalizar(frase or palabra))
            for menos, frase, palabra in _RE_TERMINO.findall(buscar[:MAX_BUSQUEDA])
            if frase.strip() or palabra.strip("-")]        # un guion suelto: aún está escribiendo


def _ahora() -> str:
    return _instante(datetime.now(timezone.utc))


def _texto(valor, campo: str, maximo: int) -> str:
    if not isinstance(valor, str):
        raise ErrorNotas(f"{campo}: se esperaba un texto")
    if len(valor) > maximo:
        raise ErrorNotas(f"{campo}: demasiado largo (máximo {maximo} caracteres)")
    # Medio emoji suelto (se puede colar al cortar un texto) no se puede guardar en UTF-8
    valor = valor.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return valor.replace("\r\n", "\n").replace("\x00", "")


def _instante(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _para_buscar(titulo: str, texto: str, detalles: dict) -> str:
    """Lo que mira el buscador. El título va primero: también sirve para ordenar."""
    enlaces = [f"{e['titulo']} {e['descripcion']} {e['url']}" for e in detalles.get("enlaces", ())]
    return normalizar("\n".join([titulo, texto, *enlaces, *detalles.get("compartida", ())]))


def _detalles(fila) -> dict:
    return json.loads(fila["detalles"] or "{}")


def _duracion(valor):
    """Segundos de una nota de voz, o None si no se sabe."""
    try:
        segundos = float(valor)
    except (TypeError, ValueError):
        return None
    return round(segundos, 2) if 0 < segundos < 7 * 24 * 3600 else None


def _nombre_categoria(valor) -> str:
    nombre = " ".join(_texto(valor, "Categoría", 1000).split())
    if not nombre:
        raise ErrorNotas("Escribe un nombre para la categoría")
    if len(nombre) > MAX_CATEGORIA:
        raise ErrorNotas(f"El nombre de la categoría es demasiado largo (máximo {MAX_CATEGORIA})")
    return nombre


def _color(valor) -> str:
    if valor not in COLORES:
        raise ErrorNotas(f"Color desconocido: {valor} (hay: {', '.join(c for c in COLORES if c)})")
    return valor


def _ids(ids) -> list:
    if not isinstance(ids, (list, tuple, set)) or not all(
            isinstance(i, int) and not isinstance(i, bool) and 0 < i < 2 ** 62 for i in ids):
        raise ErrorNotas("Se esperaba una lista de notas")
    return list(dict.fromkeys(ids))


class Cuaderno:
    """Acceso a las notas de una carpeta. Se puede compartir entre hilos."""

    def __init__(self, carpeta, crear: bool = True):
        self.carpeta = Path(carpeta)
        self.bd = self.carpeta / ARCHIVO_BD
        if not self.bd.is_file():
            if not crear:
                raise NoEncontrada(f"No hay ningún cuaderno de notas en {self.carpeta}")
            self.carpeta.mkdir(parents=True, exist_ok=True)
        self._preparar()

    # --- conexión ---

    def _conectar(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.bd, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @contextlib.contextmanager
    def _leer(self):
        db = self._conectar()
        try:
            yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def _escribir(self):
        """Transacción: todo o nada."""
        db = self._conectar()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def _preparar(self):
        with self._escribir() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > VERSION_BD:
                raise ErrorNotas("Este cuaderno es de una versión más nueva de Notas: "
                                 "actualiza el programa")
            if version < VERSION_BD:
                for sentencia in "".join(MIGRACIONES[version:]).split(";\n"):
                    if sentencia.strip():
                        db.execute(sentencia)
                db.execute(f"PRAGMA user_version = {VERSION_BD}")

    # --- notas: leer ---

    def listar(self, vista: str = "activas", buscar: str = "", categoria: int = None,
               tipo: str = None, orden: str = "modificada", limite: int = None) -> list:
        """Notas de una vista, las fijadas primero, con sus categorías y adjuntos.

        `buscar` pide que aparezcan todos los términos (en título, texto, categorías o
        nombres de adjuntos), sin distinguir mayúsculas ni acentos.
        """
        if vista not in VISTAS or orden not in ORDENES or tipo not in (None, *TIPOS):
            raise ErrorNotas("Vista, orden o tipo desconocido")
        condiciones, valores = [VISTAS[vista]], []
        if categoria == SIN_CATEGORIA:
            condiciones.append("NOT EXISTS (SELECT 1 FROM notas_categorias nc WHERE nc.nota = n.id)")
        elif categoria is not None:
            condiciones.append("EXISTS (SELECT 1 FROM notas_categorias nc "
                               "WHERE nc.nota = n.id AND nc.categoria = ?)")
            valores.append(categoria)
        if tipo == "texto":
            condiciones.append("NOT EXISTS (SELECT 1 FROM adjuntos a "
                               "WHERE a.nota = n.id AND a.quitado IS NULL)")
        elif tipo == "lista":
            condiciones.append(ES_LISTA)
        elif tipo:
            condiciones.append("EXISTS (SELECT 1 FROM adjuntos a WHERE a.nota = n.id "
                               "AND a.quitado IS NULL AND a.tipo = ?)")
            valores.append(tipo)
        for excluir, termino in terminos(buscar or ""):
            condiciones.append(("NOT " if excluir else "") + (
                "(instr(n.busqueda, ?) > 0 OR EXISTS (SELECT 1 FROM notas_categorias nc "
                "JOIN categorias c ON c.id = nc.categoria "
                "WHERE nc.nota = n.id AND instr(c.clave, ?) > 0) OR EXISTS (SELECT 1 FROM adjuntos a "
                "WHERE a.nota = n.id AND a.quitado IS NULL AND instr(a.clave, ?) > 0))"))
            valores += [termino] * 3
        orden_sql = ("n.papelera DESC, n.id DESC" if vista == "papelera"
                     else f"n.fijada DESC, {ORDENES[orden]}")
        sql = f"SELECT n.* FROM notas n WHERE {' AND '.join(condiciones)} ORDER BY {orden_sql}"
        if limite:
            sql += " LIMIT ?"
            valores.append(limite)
        with self._leer() as db:
            return self._componer(db, db.execute(sql, valores).fetchall())

    def nota(self, id_nota: int) -> dict:
        with self._leer() as db:
            return self._nota(db, id_nota)

    def _nota(self, db, id_nota: int) -> dict:
        return self._componer(db, [self._fila(db, id_nota)])[0]

    @staticmethod
    def _fila(db, id_nota: int) -> sqlite3.Row:
        fila = db.execute("SELECT * FROM notas WHERE id = ?", (id_nota,)).fetchone()
        if fila is None:
            raise NoEncontrada(f"No existe la nota {id_nota}")
        return fila

    def _componer(self, db, filas) -> list:
        """Filas de `notas` -> diccionarios con sus categorías y adjuntos."""
        notas = {f["id"]: {
            "id": f["id"], "titulo": f["titulo"], "texto": f["texto"], "color": f["color"],
            "fijada": bool(f["fijada"]), "archivada": bool(f["archivada"]),
            "papelera": f["papelera"], "creada": f["creada"], "modificada": f["modificada"],
            "version": f["version"], "detalles": _detalles(f), "categorias": [], "adjuntos": []}
            for f in filas}
        ids = json.dumps(list(notas))
        for f in db.execute("SELECT nc.nota, c.id, c.nombre FROM notas_categorias nc "
                            "JOIN categorias c ON c.id = nc.categoria "
                            "WHERE nc.nota IN (SELECT value FROM json_each(?)) ORDER BY c.clave",
                            (ids,)):
            notas[f["nota"]]["categorias"].append({"id": f["id"], "nombre": f["nombre"]})
        for f in db.execute("SELECT * FROM adjuntos WHERE quitado IS NULL "
                            "AND nota IN (SELECT value FROM json_each(?)) ORDER BY id", (ids,)):
            notas[f["nota"]]["adjuntos"].append(self._adjunto(f))
        return list(notas.values())

    @staticmethod
    def _adjunto(f) -> dict:
        # `v` cambia con el archivo: se puede guardar en la caché del navegador para siempre
        version = Path(f["archivo"]).stem
        return {"id": f["id"], "tipo": f["tipo"], "nombre": f["nombre"], "mime": f["mime"],
                "bytes": f["bytes"], "duracion": f["duracion"], "ancho": f["ancho"],
                "alto": f["alto"], "archivo": f["archivo"],
                "url": f"/adjuntos/{f['id']}?v={version}",
                "miniatura": (f"/adjuntos/{f['id']}/miniatura?v={version}"
                              if f["tipo"] == adj.IMAGEN else None)}

    def estado(self) -> dict:
        """Totales por vista y tipo, y las categorías con cuántas notas activas tienen."""
        activas = VISTAS["activas"]
        con = ("SELECT COUNT(DISTINCT n.id) FROM notas n JOIN adjuntos a ON a.nota = n.id "
               f"AND a.quitado IS NULL AND a.tipo = ? WHERE {activas}")
        with self._leer() as db:
            uno = lambda sql, *v: db.execute(sql, v).fetchone()[0]
            totales = {vista: uno(f"SELECT COUNT(*) FROM notas n WHERE {condicion}")
                       for vista, condicion in VISTAS.items()}
            totales[adj.IMAGEN] = uno(con, adj.IMAGEN)
            totales[adj.VOZ] = uno(con, adj.VOZ)
            totales["texto"] = uno(
                f"SELECT COUNT(*) FROM notas n WHERE {activas} AND NOT EXISTS (SELECT 1 "
                "FROM adjuntos a WHERE a.nota = n.id AND a.quitado IS NULL)")
            totales["lista"] = uno(f"SELECT COUNT(*) FROM notas n WHERE {activas} AND {ES_LISTA}")
            totales["sin_categoria"] = uno(
                f"SELECT COUNT(*) FROM notas n WHERE {activas} AND NOT EXISTS "
                "(SELECT 1 FROM notas_categorias nc WHERE nc.nota = n.id)")
            return {"totales": totales, "categorias": self._categorias(db)}

    # --- notas: escribir ---

    def crear(self, titulo: str = "", texto: str = "", color: str = "", fijada: bool = False,
              categorias=(), creada: str = None) -> dict:
        titulo = _texto(titulo, "Título", MAX_TITULO)
        texto = _texto(texto, "Texto", MAX_TEXTO)
        ahora = creada or _ahora()
        with self._escribir() as db:
            id_nota = db.execute(
                "INSERT INTO notas (titulo, texto, busqueda, color, fijada, creada, modificada) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (titulo, texto, _para_buscar(titulo, texto, {}), _color(color), int(bool(fijada)),
                 ahora, ahora)).lastrowid
            self._poner_categorias(db, id_nota, categorias)
            return self._nota(db, id_nota)

    def editar(self, id_nota: int, version: int = None, **cambios) -> dict:
        """Cambia los campos dados: titulo, texto, color, fijada, archivada, categorias.

        Con `version`, si el título o el texto han cambiado desde entonces lanza Conflicto
        en vez de pisar el cambio. `modificada` solo sube con cambios de título o texto.
        """
        desconocidos = set(cambios) - {"titulo", "texto", "color", "fijada", "archivada",
                                       "categorias"}
        if desconocidos:
            raise ErrorNotas(f"No se puede cambiar: {', '.join(sorted(desconocidos))}")
        with self._escribir() as db:
            fila = self._fila(db, id_nota)
            if fila["papelera"]:
                raise ErrorNotas("La nota está en la papelera: restáurala para cambiarla")
            titulo = _texto(cambios.get("titulo", fila["titulo"]), "Título", MAX_TITULO)
            texto = _texto(cambios.get("texto", fila["texto"]), "Texto", MAX_TEXTO)
            if (titulo, texto) != (fila["titulo"], fila["texto"]):
                if version is not None and version != fila["version"]:
                    raise Conflicto(self._nota(db, id_nota))
                db.execute("UPDATE notas SET titulo = ?, texto = ?, busqueda = ?, modificada = ?, "
                           "version = version + 1 WHERE id = ?",
                           (titulo, texto, _para_buscar(titulo, texto, _detalles(fila)), _ahora(),
                            id_nota))
            if "color" in cambios:
                db.execute("UPDATE notas SET color = ? WHERE id = ?",
                           (_color(cambios["color"]), id_nota))
            for campo in ("fijada", "archivada"):
                if campo in cambios:
                    db.execute(f"UPDATE notas SET {campo} = ? WHERE id = ?",
                               (int(bool(cambios[campo])), id_nota))
            # Archivar suelta la nota y fijarla la saca del archivo
            if cambios.get("archivada"):
                db.execute("UPDATE notas SET fijada = 0 WHERE id = ?", (id_nota,))
            elif cambios.get("fijada"):
                db.execute("UPDATE notas SET archivada = 0 WHERE id = ?", (id_nota,))
            if "categorias" in cambios:
                self._poner_categorias(db, id_nota, cambios["categorias"])
            return self._nota(db, id_nota)

    def lote(self, ids, accion: str, valor=None) -> int:
        """La misma acción sobre varias notas; devuelve cuántas han cambiado."""
        ids = _ids(ids)
        marcas = ",".join("?" * len(ids))
        vivas = f"id IN ({marcas}) AND papelera IS NULL"
        actualizar = {
            "fijar": f"UPDATE notas SET fijada = 1, archivada = 0 WHERE {vivas}",
            "soltar": f"UPDATE notas SET fijada = 0 WHERE {vivas}",
            "archivar": f"UPDATE notas SET archivada = 1, fijada = 0 WHERE {vivas}",
            "desarchivar": f"UPDATE notas SET archivada = 0 WHERE {vivas}",
            "restaurar": f"UPDATE notas SET papelera = NULL WHERE id IN ({marcas}) "
                         "AND papelera IS NOT NULL",
        }
        with self._escribir() as db:
            if accion in actualizar:
                return db.execute(actualizar[accion], ids).rowcount
            if accion == "papelera":
                return db.execute(f"UPDATE notas SET papelera = ? WHERE {vivas}",
                                  [_ahora(), *ids]).rowcount
            if accion == "color":
                return db.execute(f"UPDATE notas SET color = ? WHERE {vivas}",
                                  [_color(valor), *ids]).rowcount
            if accion == "poner_categoria":
                categoria = self._categoria(db, valor)
                return db.execute(
                    "INSERT OR IGNORE INTO notas_categorias (nota, categoria) "
                    f"SELECT id, ? FROM notas WHERE {vivas}", [categoria, *ids]).rowcount
            if accion == "quitar_categoria":
                clave = normalizar(_nombre_categoria(valor))
                return db.execute(
                    f"DELETE FROM notas_categorias WHERE nota IN ({marcas}) AND categoria IN "
                    "(SELECT id FROM categorias WHERE clave = ?)", [*ids, clave]).rowcount
        raise ErrorNotas(f"Acción desconocida: {accion}")

    # --- importar ---

    def importadas(self) -> set:
        """El `origen` de las notas que vienen de otro programa (también las de la papelera)."""
        with self._leer() as db:
            return {f[0] for f in db.execute("SELECT origen FROM notas WHERE origen IS NOT NULL")}

    def importar(self, origen: str, titulo: str = "", texto: str = "", color: str = "",
                 fijada: bool = False, archivada: bool = False, papelera: datetime = None,
                 creada: datetime = None, modificada: datetime = None, categorias=(),
                 detalles: dict = None, adjuntos=()) -> dict:
        """Crea una nota que viene de otro programa, con sus fechas, adjuntos y detalles.

        `origen` la identifica («keep:1365…») para no importarla dos veces; `adjuntos`, una
        lista de diccionarios con `flujo`, `nombre`, `creado` y, si se sabe, `duracion`.
        O se guarda entera o no se guarda nada.
        """
        titulo = _texto(titulo, "Título", MAX_TITULO)
        texto = _texto(texto, "Texto", MAX_TEXTO)
        detalles = detalles or {}
        creada = creada or datetime.now(timezone.utc)
        guardados = []
        try:
            for a in adjuntos:
                guardados.append((a, adj.guardar(self.carpeta, a["flujo"], a["nombre"],
                                                 ahora=a["creado"].astimezone())))
            with self._escribir() as db:
                if db.execute("SELECT 1 FROM notas WHERE origen = ?", (origen,)).fetchone():
                    raise ErrorNotas("Esa nota ya está importada")
                id_nota = db.execute(
                    "INSERT INTO notas (titulo, texto, busqueda, color, fijada, archivada, papelera, "
                    "creada, modificada, origen, detalles) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (titulo, texto, _para_buscar(titulo, texto, detalles), _color(color),
                     int(bool(fijada and not archivada)), int(bool(archivada)),
                     _instante(papelera) if papelera else None, _instante(creada),
                     _instante(modificada or creada), origen,
                     json.dumps(detalles, ensure_ascii=False) if detalles else "")).lastrowid
                self._poner_categorias(db, id_nota, categorias)
                for a, datos in guardados:
                    self._anotar_adjunto(db, id_nota, datos, a.get("duracion"),
                                         _instante(a["creado"]))
                return self._nota(db, id_nota)
        except BaseException:
            adj.borrar_archivos(self.carpeta, [datos["archivo"] for _, datos in guardados])
            raise

    # --- borrar de verdad ---

    def eliminar(self, ids) -> int:
        """Borra para siempre notas que ya están en la papelera (las demás no se tocan)."""
        ids = _ids(ids)
        marcas = ",".join("?" * len(ids))
        return self._borrar(f"id IN ({marcas}) AND papelera IS NOT NULL", ids)

    def vaciar_papelera(self, confirmar: str) -> int:
        """Borra para siempre lo que hay en la papelera y los adjuntos quitados de las notas."""
        if confirmar != VACIAR:
            raise ErrorNotas(f"Para vaciar la papelera hay que confirmar con {VACIAR}")
        return self._borrar("papelera IS NOT NULL", [], quitados=True)

    def _borrar(self, condicion: str, valores: list, quitados: bool = False) -> int:
        with self._escribir() as db:
            archivos = [f[0] for f in db.execute(
                "SELECT archivo FROM adjuntos WHERE nota IN "
                f"(SELECT id FROM notas WHERE {condicion})", valores)]
            n = db.execute(f"DELETE FROM notas WHERE {condicion}", valores).rowcount
            if quitados:
                archivos += [f[0] for f in db.execute(
                    "SELECT archivo FROM adjuntos WHERE quitado IS NOT NULL")]
                db.execute("DELETE FROM adjuntos WHERE quitado IS NOT NULL")
        adj.borrar_archivos(self.carpeta, archivos)
        return n

    # --- categorías ---

    @staticmethod
    def _categorias(db) -> list:
        return [dict(f) for f in db.execute(
            "SELECT c.id, c.nombre, (SELECT COUNT(*) FROM notas_categorias nc JOIN notas n "
            f"ON n.id = nc.nota WHERE nc.categoria = c.id AND {VISTAS['activas']}) AS total "
            "FROM categorias c ORDER BY c.clave")]

    def categorias(self) -> list:
        with self._leer() as db:
            return self._categorias(db)

    @staticmethod
    def _categoria(db, nombre) -> int:
        """id de la categoría con ese nombre (sin distinguir acentos); la crea si no existe."""
        nombre = _nombre_categoria(nombre)
        fila = db.execute("SELECT id FROM categorias WHERE clave = ?",
                          (normalizar(nombre),)).fetchone()
        if fila:
            return fila["id"]
        return db.execute("INSERT INTO categorias (nombre, clave) VALUES (?, ?)",
                          (nombre, normalizar(nombre))).lastrowid

    def _poner_categorias(self, db, id_nota: int, nombres):
        if not isinstance(nombres, (list, tuple)):
            raise ErrorNotas("Categorías: se esperaba una lista de nombres")
        db.execute("DELETE FROM notas_categorias WHERE nota = ?", (id_nota,))
        for nombre in nombres:
            db.execute("INSERT OR IGNORE INTO notas_categorias (nota, categoria) VALUES (?, ?)",
                       (id_nota, self._categoria(db, nombre)))

    def buscar_categoria(self, nombre: str):
        """id de la categoría que se llama así, o None."""
        with self._leer() as db:
            fila = db.execute("SELECT id FROM categorias WHERE clave = ?",
                              (normalizar(_nombre_categoria(nombre)),)).fetchone()
            return fila["id"] if fila else None

    def crear_categoria(self, nombre: str) -> dict:
        nombre = _nombre_categoria(nombre)
        with self._escribir() as db:
            if db.execute("SELECT 1 FROM categorias WHERE clave = ?",
                          (normalizar(nombre),)).fetchone():
                raise ErrorNotas(f"Ya hay una categoría «{nombre}»")
            return {"id": self._categoria(db, nombre), "nombre": nombre, "total": 0}

    def renombrar_categoria(self, id_categoria: int, nombre: str) -> dict:
        nombre = _nombre_categoria(nombre)
        with self._escribir() as db:
            if db.execute("SELECT 1 FROM categorias WHERE clave = ? AND id <> ?",
                          (normalizar(nombre), id_categoria)).fetchone():
                raise ErrorNotas(f"Ya hay una categoría «{nombre}»")
            if not db.execute("UPDATE categorias SET nombre = ?, clave = ? WHERE id = ?",
                              (nombre, normalizar(nombre), id_categoria)).rowcount:
                raise NoEncontrada("Esa categoría ya no existe")
            return {"id": id_categoria, "nombre": nombre}

    def borrar_categoria(self, id_categoria: int):
        """Quita la categoría; sus notas se quedan, sin ella."""
        with self._escribir() as db:
            if not db.execute("DELETE FROM categorias WHERE id = ?", (id_categoria,)).rowcount:
                raise NoEncontrada("Esa categoría ya no existe")

    # --- adjuntos ---

    def adjuntar(self, id_nota: int, flujo, nombre: str = "", mime: str = "",
                 duracion: float = None, longitud: int = None) -> dict:
        """Guarda una imagen o un audio y lo añade a la nota; devuelve el adjunto."""
        with self._leer() as db:          # antes de copiar nada
            if self._fila(db, id_nota)["papelera"]:
                raise ErrorNotas("La nota está en la papelera: restáurala para cambiarla")
        datos = adj.guardar(self.carpeta, flujo, nombre, mime, longitud)
        try:
            with self._escribir() as db:
                self._fila(db, id_nota)
                ahora = _ahora()
                id_adjunto = self._anotar_adjunto(db, id_nota, datos, duracion, ahora)
                db.execute("UPDATE notas SET modificada = ? WHERE id = ?", (ahora, id_nota))
                return self._adjunto(self._fila_adjunto(db, id_adjunto))
        except BaseException:
            adj.borrar_archivos(self.carpeta, [datos["archivo"]])
            raise

    @staticmethod
    def _anotar_adjunto(db, id_nota: int, datos: dict, duracion, creado: str) -> int:
        return db.execute(
            "INSERT INTO adjuntos (nota, tipo, archivo, nombre, clave, mime, bytes, duracion, "
            "ancho, alto, creado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id_nota, datos["tipo"], datos["archivo"], datos["nombre"],
             normalizar(datos["nombre"]), datos["mime"], datos["bytes"],
             _duracion(duracion) if datos["tipo"] == adj.VOZ else None, datos["ancho"],
             datos["alto"], creado)).lastrowid

    def adjuntar_archivo(self, id_nota: int, ruta) -> dict:
        """Como `adjuntar`, desde un archivo del disco (que solo se lee)."""
        ruta = Path(ruta)
        if not ruta.is_file():
            raise AdjuntoNoValido(f"No existe el archivo {ruta}")
        with open(ruta, "rb") as f:
            return self.adjuntar(id_nota, f, ruta.name)

    @staticmethod
    def _fila_adjunto(db, id_adjunto: int) -> sqlite3.Row:
        fila = db.execute("SELECT * FROM adjuntos WHERE id = ?", (id_adjunto,)).fetchone()
        if fila is None:
            raise NoEncontrada("Ese adjunto ya no existe")
        return fila

    def adjunto(self, id_adjunto: int) -> dict:
        """Datos de un adjunto (también de los quitados, para poder deshacer), con su `ruta`."""
        with self._leer() as db:
            datos = self._adjunto(self._fila_adjunto(db, id_adjunto))
        datos["ruta"] = adj.ruta_segura(self.carpeta, datos["archivo"])
        return datos

    def quitar_adjunto(self, id_adjunto: int, quitar: bool = True) -> dict:
        """Quita un adjunto de su nota (o lo recupera); el archivo no se borra todavía."""
        with self._escribir() as db:
            fila = self._fila_adjunto(db, id_adjunto)
            ahora = _ahora()
            db.execute("UPDATE adjuntos SET quitado = ? WHERE id = ?",
                       (ahora if quitar else None, id_adjunto))
            db.execute("UPDATE notas SET modificada = ? WHERE id = ?", (ahora, fila["nota"]))
            return self._nota(db, fila["nota"])
