"""Limpiar fotos repetidas: grupos, mejor copia, papelera y decisiones guardadas.

Lo usa la página «Limpiar repetidas» de la galería (limpiar_plantilla.html) a través
de los endpoints /api/limpieza/... de servidor.py. Reglas:

  - Solo actúa sobre archivos de la biblioteca (la carpeta de la galería); cualquier
    ruta fuera de ella, en carpetas internas o que sea el origen de una importación
    se rechaza. La carpeta de origen de la importación nunca se toca.
  - Nada se borra directamente: lo descartado se mueve a .exportador/papelera/ con su
    ruta relativa y se puede restaurar. Solo «vaciar la papelera» (con confirmación
    explícita) borra de verdad.
  - El contenido descartado se anota en el catálogo (tabla `descartadas`) para que
    la siguiente importación incremental no lo vuelva a traer.
  - Cada decisión se guarda en .exportador/limpieza.json en cuanto se toma: se puede
    cerrar el navegador y seguir otro día. La última decisión se puede deshacer.
"""

import contextlib
import functools
import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path, PurePosixPath

from catalogo import ESQUEMA, Catalogo, ESPERA_BLOQUEO, ruta_catalogo
from clasificacion import es_whatsapp
from media_utils import CARPETA_INTERNA, CARPETAS_EXCLUIDAS, hash_archivo
from similares import UMBRAL, agrupar

CARPETA_PAPELERA = "papelera"                 # dentro de .exportador/
ARCHIVO_DECISIONES = "limpieza.json"          # dentro de .exportador/
UMBRAL_MAX = 24                               # bits (de 128) como máximo en el ajuste
TOLERANCIA_RESOLUCION = 0.05                  # ±5 % de píxeles cuenta como la misma resolución
EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}   # las de la galería
CONFIRMAR_VACIADO = "VACIAR"
_RE_SENT = re.compile(r"(^|[\\/])sent([\\/]|$)", re.IGNORECASE)

ESQUEMA_PAPELERA = """
CREATE TABLE IF NOT EXISTS papelera (
    src        TEXT PRIMARY KEY,   -- ruta relativa en la biblioteca (con '/')
    en_papelera TEXT NOT NULL,     -- ruta relativa dentro de la papelera
    original   TEXT,               -- copia del original (originales/...) movida con ella
    original_en_papelera TEXT,
    hash       TEXT,               -- el que queda en `descartadas`
    bytes      INTEGER NOT NULL,   -- espacio que ocupa (foto + original)
    elemento   TEXT,               -- su entrada de galeria.json (para restaurarla)
    decision   TEXT,               -- id de la decisión que la quitó
    fecha      TEXT NOT NULL
);
"""


class RutaNoValida(ValueError):
    """Ruta que no es una foto de la biblioteca (fuera de ella, interna, origen...)."""


class ErrorLimpieza(ValueError):
    """Petición coherente pero imposible (p. ej. quitar todas las copias de un grupo)."""


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def id_grupo(srcs) -> str:
    return hashlib.sha1("\n".join(sorted(srcs)).encode("utf-8")).hexdigest()[:16]


# ----------------------------- Elegir la mejor copia -----------------------------

def _rasgos(f: dict) -> dict:
    origen = f.get("origen") or ""
    return {
        "pixeles": (f.get("ancho") or 0) * (f.get("alto") or 0),
        "exif": bool(f.get("camara")) or f.get("fuente_fecha") == "exif",
        "whatsapp": f.get("ambito") == "whatsapp" or es_whatsapp(f["src"]) or
                    (bool(origen) and es_whatsapp(origen)),
        "sent": bool(_RE_SENT.search(origen) or _RE_SENT.search(f["src"])),
        "peso": f.get("bytes_origen") or f.get("bytes") or 0,
    }


def _comparar(a: dict, b: dict) -> int:
    """>0 si `a` es mejor copia que `b`. Resolución, EXIF de cámara, no WhatsApp/Sent, peso."""
    ra, rb = _rasgos(a), _rasgos(b)
    mayor = max(ra["pixeles"], rb["pixeles"])
    if mayor and abs(ra["pixeles"] - rb["pixeles"]) / mayor > TOLERANCIA_RESOLUCION:
        return 1 if ra["pixeles"] > rb["pixeles"] else -1
    for clave, mejor_si in (("exif", True), ("whatsapp", False), ("sent", False)):
        if ra[clave] != rb[clave]:
            return 1 if ra[clave] == mejor_si else -1
    if ra["peso"] != rb["peso"]:
        return 1 if ra["peso"] > rb["peso"] else -1
    return (b["src"] > a["src"]) - (b["src"] < a["src"])   # desempate estable


def elegir_mejor(fotos: list) -> tuple:
    """(src de la mejor copia, motivo legible) de un grupo de fotos (dicts)."""
    orden = sorted(fotos, key=functools.cmp_to_key(_comparar), reverse=True)
    mejor, segunda = orden[0], orden[1] if len(orden) > 1 else None
    if segunda is None:
        return mejor["src"], ""
    rm, rs = _rasgos(mejor), _rasgos(segunda)
    if rm["pixeles"] and abs(rm["pixeles"] - rs["pixeles"]) / rm["pixeles"] > TOLERANCIA_RESOLUCION:
        motivo = "más resolución"
    elif rm["exif"] and not rs["exif"]:
        motivo = "tiene EXIF de cámara"
    elif not rm["whatsapp"] and rs["whatsapp"]:
        motivo = "no viene de WhatsApp"
    elif not rm["sent"] and rs["sent"]:
        motivo = "no es la copia enviada (Sent)"
    elif rm["peso"] > rs["peso"]:
        motivo = "más peso (menos comprimida)"
    else:
        motivo = "copias equivalentes"
    return mejor["src"], motivo


# ----------------------------- Limpieza -----------------------------

class Limpieza:
    """Estado de la limpieza de una biblioteca. Seguro entre hilos (un lock por biblioteca)."""

    _locks = {}
    _lock_locks = threading.Lock()

    def __init__(self, biblioteca: Path):
        self.biblioteca = Path(biblioteca).resolve()
        self.interna = self.biblioteca / CARPETA_INTERNA
        self.papelera = self.interna / CARPETA_PAPELERA
        self.ruta_decisiones = self.interna / ARCHIVO_DECISIONES
        with Limpieza._lock_locks:
            self.lock = Limpieza._locks.setdefault(str(self.biblioteca), threading.RLock())

    # --- base de datos (el mismo catálogo SQLite) ---

    @contextlib.contextmanager
    def _db(self, solo_leer: bool = False):
        """Conexión al catálogo: confirma al salir (también si hubo error: lo ya movido
        queda anotado y se puede restaurar) y siempre se cierra. Para solo leer, si la
        carpeta aún no tiene catálogo no se crea (se usa uno vacío en memoria)."""
        if solo_leer and not ruta_catalogo(self.biblioteca).exists():
            db = sqlite3.connect(":memory:")
            db.executescript(ESQUEMA)
        else:
            with Catalogo(self.biblioteca):    # crea/migra el catálogo (y `descartadas`)
                pass
            db = sqlite3.connect(ruta_catalogo(self.biblioteca), timeout=ESPERA_BLOQUEO)
        try:
            db.row_factory = sqlite3.Row
            db.executescript(ESQUEMA_PAPELERA)
            yield db
        finally:
            db.commit()
            db.close()

    def _catalogo_por_destino(self, db) -> dict:
        return {f["destino"]: f for f in db.execute(
            "SELECT destino, origen, hash, original, bytes_antes, fuente_fecha FROM archivos")}

    # --- decisiones (limpieza.json) ---

    def _leer_decisiones(self) -> dict:
        try:
            datos = json.loads(self.ruta_decisiones.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            datos = {}
        if not isinstance(datos, dict):
            datos = {}
        datos.setdefault("revisados", [])    # conjuntos de fotos ya decididos (no vuelven a salir)
        datos.setdefault("historial", [])    # decisiones, la última al final (para deshacer)
        return datos

    def _guardar_decisiones(self, datos: dict):
        self.interna.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta_decisiones.with_name(self.ruta_decisiones.name + ".part")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.ruta_decisiones)

    # --- validación de rutas ---

    def validar(self, src, existir: bool = True) -> Path:
        """Ruta absoluta de una foto de la biblioteca o RutaNoValida."""
        if not isinstance(src, str) or not src or len(src) > 1024 or "\x00" in src:
            raise RutaNoValida("ruta vacía o no válida")
        if "\\" in src or ":" in src or src.startswith("/"):
            raise RutaNoValida(f"ruta no relativa: {src}")
        partes = PurePosixPath(src).parts
        if any(p in ("", ".", "..") for p in partes) or src != "/".join(partes):
            raise RutaNoValida(f"ruta con '..' o tramos vacíos: {src}")
        if partes[0] in CARPETAS_EXCLUIDAS or any(p.startswith(".") for p in partes):
            raise RutaNoValida(f"carpeta interna: {src}")
        if PurePosixPath(src).suffix.lower() not in EXTENSIONES:
            raise RutaNoValida(f"no es una foto: {src}")
        ruta = (self.biblioteca / src).resolve()
        if not ruta.is_relative_to(self.biblioteca) or ruta == self.biblioteca:
            raise RutaNoValida(f"fuera de la biblioteca: {src}")
        if existir and not ruta.is_file():
            raise RutaNoValida(f"no existe: {src}")
        return ruta

    def _no_es_origen(self, db, rutas):
        """La carpeta de origen de una importación nunca se toca (aunque esté dentro)."""
        origenes = {os.path.normcase(f[0]) for f in db.execute("SELECT origen FROM archivos")}
        for ruta in rutas:
            if os.path.normcase(str(ruta)) in origenes:
                raise RutaNoValida(f"es un archivo de origen de una importación: {ruta.name}")

    # --- galería ---

    def _indice(self) -> dict:
        try:
            datos = json.loads((self.biblioteca / "galeria.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return datos if isinstance(datos, dict) else {}

    def _escribir_indice(self, datos: dict):
        from galeria import _escribir, marcar_parecidas
        marcar_parecidas(datos["elementos"])
        _escribir(self.biblioteca / "galeria.json",
                  json.dumps(datos, ensure_ascii=False, separators=(",", ":")))

    # --- grupos ---

    def grupos(self, umbral: int = UMBRAL) -> dict:
        """Grupos pendientes de revisar, con la mejor copia propuesta."""
        umbral = max(0, min(UMBRAL_MAX, int(umbral)))
        elementos = [e for e in self._indice().get("elementos", [])
                     if isinstance(e, dict) and e.get("tipo") == "foto" and e.get("dhash")]
        with self.lock, self._db(solo_leer=True) as db:
            catalogo = self._catalogo_por_destino(db)
            decisiones = self._leer_decisiones()
            papelera = db.execute("SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM papelera").fetchone()
        fotos = {}
        for e in elementos:
            if not (self.biblioteca / e["src"]).is_file():
                continue
            info = catalogo.get(e["src"])
            origen = info["origen"] if info else ""
            fotos[e["src"]] = {
                "src": e["src"], "thumb": e.get("thumb") or "",
                "ancho": e.get("ancho") or 0, "alto": e.get("alto") or 0,
                "bytes": e.get("bytes") or 0, "fecha": e.get("fecha", ""),
                "camara": e.get("camara") or "", "ambito": e.get("ambito") or "",
                "fuente_fecha": (info["fuente_fecha"] if info else "") or e.get("fuente_fecha") or "",
                "nombre_original": Path(origen).name if origen else (e.get("nombre_original") or ""),
                "carpeta_origen": str(Path(origen).parent) if origen else "",
                "origen": origen,
                "bytes_origen": (info["bytes_antes"] if info else 0) or 0,
            }
        proporciones = {s: f["ancho"] / f["alto"] for s, f in fotos.items() if f["ancho"] and f["alto"]}
        revisados = [set(r) for r in decisiones["revisados"]]
        pendientes = []
        for g in agrupar({s: e["dhash"] for s, e in ((e["src"], e) for e in elementos)
                          if s in fotos}, proporciones, umbral):
            if any(set(g) <= r for r in revisados):
                continue
            miembros = sorted((fotos[s] for s in g), key=lambda f: (f["fecha"], f["src"]))
            mejor, motivo = elegir_mejor(miembros)
            for f in miembros:
                f["rasgos"] = {k: v for k, v in _rasgos(f).items() if k != "peso"}
                f.pop("origen", None)
            liberable = sum(f["bytes"] for f in miembros if f["src"] != mejor)
            pendientes.append({"id": id_grupo(g), "fotos": miembros, "mejor": mejor,
                               "motivo": motivo, "liberable": liberable})
        pendientes.sort(key=lambda g: (g["fotos"][0]["fecha"], g["id"]))
        return {
            "umbral": umbral, "umbral_defecto": UMBRAL, "umbral_max": UMBRAL_MAX,
            "grupos": pendientes,
            "liberable": sum(g["liberable"] for g in pendientes),
            "revisados": len(decisiones["revisados"]),
            "decididos": len(decisiones["historial"]),
            "deshacer": _resumen_decision(decisiones["historial"][-1]) if decisiones["historial"] else None,
            "papelera": {"fotos": papelera[0], "bytes": papelera[1]},
        }

    # --- decisiones ---

    def decidir(self, grupo: list, quitar: list) -> dict:
        """Mueve a la papelera las fotos `quitar` del grupo y lo marca como revisado."""
        grupo, quitar = _lista_rutas(grupo, "grupo"), _lista_rutas(quitar, "quitar")
        if len(set(grupo)) < 2:
            raise ErrorLimpieza("un grupo tiene al menos dos fotos")
        if not set(quitar) <= set(grupo):
            raise ErrorLimpieza("solo se pueden quitar fotos del propio grupo")
        conservar = [s for s in dict.fromkeys(grupo) if s not in quitar]
        if not conservar:
            raise ErrorLimpieza("hay que conservar al menos una copia de cada grupo")
        with self.lock, self._db() as db:
            rutas = {s: self.validar(s) for s in dict.fromkeys(grupo)}
            self._no_es_origen(db, rutas.values())
            decision = {"id": os.urandom(6).hex(), "tipo": "quitar" if quitar else "conservar",
                        "grupo": sorted(set(grupo)), "quitar": sorted(set(quitar)), "fecha": _ahora()}
            catalogo = self._catalogo_por_destino(db)
            indice = self._indice()
            elementos = {e.get("src"): e for e in indice.get("elementos", []) if isinstance(e, dict)}
            movidas, liberado = [], 0
            for src in decision["quitar"]:
                liberado += self._mover_a_papelera(db, src, rutas[src], catalogo.get(src),
                                                   elementos.get(src), decision["id"])
                movidas.append(src)
            db.commit()
            decisiones = self._leer_decisiones()
            if len(conservar) > 1:
                decisiones["revisados"].append(sorted(conservar))
            decisiones["historial"].append(decision)
            self._guardar_decisiones(decisiones)
            if movidas and indice.get("elementos") is not None:
                indice["elementos"] = [e for e in indice["elementos"]
                                       if not isinstance(e, dict) or e.get("src") not in set(movidas)]
                self._escribir_indice(indice)
        return {"ok": True, "quitadas": len(movidas), "liberado": liberado,
                "deshacer": _resumen_decision(decision)}

    def no_repetidas(self, grupo: list) -> dict:
        """«No son repetidas»: el grupo no vuelve a salir (sin mover nada)."""
        grupo = _lista_rutas(grupo, "grupo")
        if len(set(grupo)) < 2:
            raise ErrorLimpieza("un grupo tiene al menos dos fotos")
        for s in grupo:
            self.validar(s, existir=False)
        with self.lock:
            decisiones = self._leer_decisiones()
            decision = {"id": os.urandom(6).hex(), "tipo": "no_repetidas",
                        "grupo": sorted(set(grupo)), "quitar": [], "fecha": _ahora()}
            decisiones["revisados"].append(decision["grupo"])
            decisiones["historial"].append(decision)
            self._guardar_decisiones(decisiones)
        return {"ok": True, "deshacer": _resumen_decision(decision)}

    def deshacer(self) -> dict:
        """Deshace la última decisión: restaura sus fotos y el grupo vuelve a salir."""
        with self.lock:
            decisiones = self._leer_decisiones()
            if not decisiones["historial"]:
                raise ErrorLimpieza("no hay nada que deshacer")
            decision = decisiones["historial"][-1]
            restauradas, recuperado = [], 0
            if decision.get("quitar"):
                with self._db() as db:
                    filas = db.execute("SELECT src, bytes FROM papelera WHERE decision = ?",
                                       (decision["id"],)).fetchall()
                en_papelera = {f["src"] for f in filas}
                recuperado = sum(f["bytes"] for f in filas)
                if en_papelera != set(decision["quitar"]):
                    raise ErrorLimpieza("esas fotos ya no están en la papelera (¿se vació?): "
                                        "no se puede deshacer")
                restauradas = self._restaurar(sorted(en_papelera))
            decisiones = self._leer_decisiones()
            decisiones["historial"].pop()
            conjunto = sorted(s for s in decision["grupo"] if s not in decision.get("quitar", []))
            for i in range(len(decisiones["revisados"]) - 1, -1, -1):
                if sorted(decisiones["revisados"][i]) in (conjunto, decision["grupo"]):
                    del decisiones["revisados"][i]
                    break
            self._guardar_decisiones(decisiones)
            ultima = decisiones["historial"][-1] if decisiones["historial"] else None
        return {"ok": True, "deshecha": _resumen_decision(decision), "restauradas": restauradas,
                "recuperado": recuperado,
                "deshacer": _resumen_decision(ultima) if ultima else None}

    # --- papelera ---

    def _ruta_en_papelera(self, rel: str) -> Path:
        destino = self.papelera / rel
        n = 1
        while destino.exists():   # ya hay una con ese nombre (quitada, restaurada y vuelta a quitar)
            destino = destino.with_name(f"{Path(rel).stem}~{n}{Path(rel).suffix}")
            n += 1
        return destino

    def _mover_a_papelera(self, db, src: str, ruta: Path, info, elemento, decision: str) -> int:
        digest = (info["hash"] if info else None) or hash_archivo(ruta)
        bytes_ = ruta.stat().st_size
        destino = self._ruta_en_papelera(src)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(ruta), str(destino))
        original = original_en_papelera = None
        if info and info["original"]:
            ruta_original = (self.biblioteca / info["original"]).resolve()
            if ruta_original.is_file() and ruta_original.is_relative_to(self.biblioteca):
                destino_original = self._ruta_en_papelera(info["original"])
                destino_original.parent.mkdir(parents=True, exist_ok=True)
                bytes_ += ruta_original.stat().st_size
                shutil.move(str(ruta_original), str(destino_original))
                original = info["original"]
                original_en_papelera = destino_original.relative_to(self.papelera).as_posix()
        db.execute("INSERT OR REPLACE INTO papelera VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (src, destino.relative_to(self.papelera).as_posix(), original,
                    original_en_papelera, digest, bytes_,
                    json.dumps(elemento, ensure_ascii=False) if elemento else None,
                    decision, _ahora()))
        db.execute("INSERT OR REPLACE INTO descartadas VALUES (?, ?, ?)", (digest, src, _ahora()))
        return bytes_

    def contenido_papelera(self) -> dict:
        with self.lock, self._db(solo_leer=True) as db:
            filas = db.execute("SELECT * FROM papelera ORDER BY fecha DESC, src").fetchall()
        fotos = []
        for f in filas:
            elemento = json.loads(f["elemento"]) if f["elemento"] else {}
            fotos.append({"src": f["src"], "bytes": f["bytes"], "fecha": f["fecha"],
                          "thumb": elemento.get("thumb") if elemento.get("thumb") and
                          (self.biblioteca / elemento["thumb"]).is_file() else "",
                          "ancho": elemento.get("ancho"), "alto": elemento.get("alto")})
        return {"fotos": fotos, "bytes": sum(f["bytes"] for f in fotos),
                "carpeta": str(self.papelera)}

    def restaurar(self, srcs=None) -> dict:
        """Devuelve a su sitio las fotos de la papelera (todas si `srcs` es None).

        Sus grupos vuelven a salir para revisarlos otra vez.
        """
        if srcs is not None:
            srcs = _lista_rutas(srcs, "srcs")
            for s in srcs:
                self.validar(s, existir=False)
        with self.lock:
            restauradas = self._restaurar(srcs)
            self._olvidar_decisiones_de(restauradas)
        return {"ok": True, "restauradas": restauradas}

    def _restaurar(self, srcs) -> list:
        restauradas = []
        with self.lock, self._db() as db:
            if srcs is None:
                filas = db.execute("SELECT * FROM papelera").fetchall()
            else:
                filas = [f for s in srcs for f in
                         db.execute("SELECT * FROM papelera WHERE src = ?", (s,)).fetchall()]
            indice = self._indice()
            for f in filas:
                src = f["src"]
                en_papelera = self._dentro_papelera(f["en_papelera"])
                if not en_papelera.is_file():
                    db.execute("DELETE FROM papelera WHERE src = ?", (src,))
                    continue
                destino = self.validar(src, existir=False)
                if destino.exists():   # ocupada por una importación posterior: otro nombre
                    destino = _nombre_libre(destino)
                    nuevo = destino.relative_to(self.biblioteca).as_posix()
                    db.execute("UPDATE archivos SET destino = ? WHERE destino = ?", (nuevo, src))
                else:
                    nuevo = src
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(en_papelera), str(destino))
                if f["original"]:
                    origen_original = self._dentro_papelera(f["original_en_papelera"])
                    destino_original = (self.biblioteca / f["original"]).resolve()
                    if (origen_original.is_file() and destino_original.is_relative_to(self.biblioteca)
                            and not destino_original.exists()):
                        destino_original.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(origen_original), str(destino_original))
                db.execute("DELETE FROM papelera WHERE src = ?", (src,))
                db.execute("DELETE FROM descartadas WHERE hash = ?", (f["hash"],))
                restauradas.append(nuevo)
                if f["elemento"] and indice.get("elementos") is not None:
                    elemento = json.loads(f["elemento"])
                    elemento["src"] = nuevo
                    _miniatura_si_falta(self.biblioteca, destino, elemento)
                    indice["elementos"] = [e for e in indice["elementos"]
                                           if not isinstance(e, dict) or e.get("src") != nuevo]
                    indice["elementos"].append(elemento)
            db.commit()
            if restauradas and indice.get("elementos") is not None:
                indice["elementos"].sort(key=lambda e: (e.get("fecha", ""), e.get("src", "")),
                                         reverse=True)
                self._escribir_indice(indice)
            self._limpiar_carpetas_vacias()
        return restauradas

    def _olvidar_decisiones_de(self, restauradas):
        """Una foto restaurada a mano vuelve a poder salir en su grupo."""
        if not restauradas:
            return
        decisiones = self._leer_decisiones()
        quitadas = set(restauradas)
        for d in decisiones["historial"]:
            d["quitar"] = [s for s in d.get("quitar", []) if s not in quitadas]
        decisiones["revisados"] = [r for r in decisiones["revisados"]
                                   if not quitadas & set(r)]
        # Los grupos con fotos restauradas se vuelven a revisar enteros
        afectados = [d for d in decisiones["historial"] if quitadas & set(d["grupo"])]
        for d in afectados:
            conjunto = sorted(s for s in d["grupo"] if s not in d["quitar"])
            decisiones["revisados"] = [r for r in decisiones["revisados"]
                                       if sorted(r) != conjunto]
        decisiones["historial"] = [d for d in decisiones["historial"] if d not in afectados]
        self._guardar_decisiones(decisiones)

    def vaciar(self, confirmacion) -> dict:
        """Borra de verdad lo que hay en la papelera. Exige confirmacion == 'VACIAR'."""
        if confirmacion != CONFIRMAR_VACIADO:
            raise ErrorLimpieza(f"para vaciar la papelera hay que confirmar con «{CONFIRMAR_VACIADO}»")
        borradas, liberado = 0, 0
        with self.lock, self._db() as db:
            filas = db.execute("SELECT * FROM papelera").fetchall()
            for f in filas:
                for rel in (f["en_papelera"], f["original_en_papelera"]):
                    if not rel:
                        continue
                    ruta = self._dentro_papelera(rel)
                    if ruta.is_file():
                        liberado += ruta.stat().st_size
                        ruta.unlink()
                borradas += 1
                db.execute("DELETE FROM papelera WHERE src = ?", (f["src"],))
            db.commit()   # `descartadas` se queda: no se vuelven a importar
            self._limpiar_carpetas_vacias()
            decisiones = self._leer_decisiones()
            for d in decisiones["historial"]:
                d["vaciada"] = True
            self._guardar_decisiones(decisiones)
        return {"ok": True, "borradas": borradas, "liberado": liberado}

    def _dentro_papelera(self, rel: str) -> Path:
        ruta = (self.papelera / rel).resolve()
        if not ruta.is_relative_to(self.papelera.resolve()):
            raise RutaNoValida(f"fuera de la papelera: {rel}")
        return ruta

    def _limpiar_carpetas_vacias(self):
        if not self.papelera.is_dir():
            return
        for raiz, carpetas, archivos in os.walk(self.papelera, topdown=False):
            if raiz != str(self.papelera) and not os.listdir(raiz):
                os.rmdir(raiz)


# ----------------------------- Auxiliares -----------------------------

def _lista_rutas(valor, nombre: str) -> list:
    if not isinstance(valor, list) or not all(isinstance(x, str) for x in valor) or len(valor) > 500:
        raise RutaNoValida(f"«{nombre}» debe ser una lista de rutas")
    return valor


def _resumen_decision(d: dict) -> dict:
    return {"id": d["id"], "tipo": d["tipo"], "grupo": d["grupo"], "quitar": d.get("quitar", []),
            "fecha": d.get("fecha", ""), "posible": not d.get("vaciada") or not d.get("quitar")}


def _nombre_libre(ruta: Path) -> Path:
    n = 1
    while True:
        candidata = ruta.with_name(f"{ruta.stem}_restaurada{'' if n == 1 else n}{ruta.suffix}")
        if not candidata.exists():
            return candidata
        n += 1


def _miniatura_si_falta(biblioteca: Path, ruta: Path, elemento: dict):
    from galeria import _clave, _miniatura_foto
    rel = ruta.relative_to(biblioteca).as_posix()
    thumb_rel = elemento.get("thumb") or ""
    if thumb_rel and (biblioteca / thumb_rel).is_file() and rel == elemento["src"]:
        return
    from media_utils import CARPETA_GALERIA
    thumb_rel = f"{CARPETA_GALERIA}/thumbs/{_clave(rel)}.jpg"
    try:
        (biblioteca / thumb_rel).parent.mkdir(parents=True, exist_ok=True)
        _miniatura_foto(ruta, biblioteca / thumb_rel)
        elemento["thumb"] = thumb_rel
    except Exception:
        elemento["thumb"] = ""
