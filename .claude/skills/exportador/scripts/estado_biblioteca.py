"""Resumen de una biblioteca del exportador, SOLO LECTURA (no modifica nada).

    python estado_biblioteca.py <biblioteca>                 # resumen general
    python estado_biblioteca.py <biblioteca> --buscar IMG_1234   # dónde está / de dónde vino
    python estado_biblioteca.py <biblioteca> --informe       # acciones del último informe CSV

Lee el catálogo (.exportador/catalogo.sqlite, abierto en modo solo lectura), los informes
CSV, la papelera, limpieza.json y galeria.json. Solo usa la biblioteca estándar de Python,
así que funciona aunque el paquete no esté instalado.
"""

import argparse
import collections
import csv
import json
import sqlite3
import sys
from pathlib import Path


def _mb(n) -> str:
    n = n or 0
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.1f} MB"


def _catalogo(biblioteca: Path):
    ruta = biblioteca / ".exportador" / "catalogo.sqlite"
    if not ruta.is_file():
        return None
    db = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def _tablas(db) -> set:
    return {f[0] for f in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def resumen(biblioteca: Path):
    print(f"Biblioteca: {biblioteca}")
    db = _catalogo(biblioteca)
    if db is None:
        print("  Sin catálogo (.exportador/catalogo.sqlite): no es una biblioteca del exportador"
              " o aún no se ha importado nada en ella.")
    else:
        with db:
            tablas = _tablas(db)
            print("\nCatálogo (lo importado):")
            for f in db.execute("SELECT tipo, COUNT(*) n, SUM(bytes_antes) a, SUM(bytes_despues) d "
                                "FROM archivos GROUP BY tipo ORDER BY n DESC"):
                print(f"  {f['tipo']:6} {f['n']:7}   {_mb(f['a'])} en origen -> {_mb(f['d'])} en la biblioteca")
            filas = db.execute("SELECT substr(fecha, 1, 4) anio, COUNT(*) n FROM archivos "
                               "GROUP BY anio ORDER BY anio").fetchall()
            if filas:
                print("  Por año: " + ", ".join(f"{f['anio'] or '?'}: {f['n']}" for f in filas))
            filas = db.execute("SELECT fuente_fecha, COUNT(*) n FROM archivos "
                               "GROUP BY fuente_fecha ORDER BY n DESC").fetchall()
            print("  Fuente de la fecha: " + ", ".join(f"{f['fuente_fecha'] or '?'}: {f['n']}"
                                                       for f in filas))
            n_wa = db.execute("SELECT COUNT(*) FROM archivos WHERE destino LIKE 'WhatsApp/%'").fetchone()[0]
            n_orig = db.execute("SELECT COUNT(*) FROM archivos WHERE original IS NOT NULL").fetchone()[0]
            print(f"  En WhatsApp/: {n_wa}   con copia en originales/: {n_orig}")
            f = db.execute("SELECT MIN(importado) a, MAX(importado) b FROM archivos").fetchone()
            if f["a"]:
                print(f"  Importado entre {f['a'][:16]} y {f['b'][:16]}")
            carpetas = collections.Counter(
                str(Path(r[0]).parent) for r in db.execute("SELECT origen FROM archivos"))
            if carpetas:
                print("  Carpetas de origen más frecuentes:")
                for carpeta, n in carpetas.most_common(5):
                    print(f"    {n:7}  {carpeta}")
            if "descartes" in tablas:
                filas = db.execute("SELECT motivo, COALESCE(problema, '') p, COUNT(*) n "
                                   "FROM descartes GROUP BY motivo, p ORDER BY n DESC").fetchall()
                if filas:
                    print("\nDescartes (no importados a propósito; no se vuelven a leer si no cambian):")
                    for f in filas:
                        print(f"  {f['n']:7}  {f['motivo']}{' - ' + f['p'] if f['p'] else ''}")
            if "descartadas" in tablas:
                n = db.execute("SELECT COUNT(*) FROM descartadas").fetchone()[0]
                print(f"\nQuitadas con «Limpiar repetidas» (no se reimportan): {n}")
        db.close()

    papelera = biblioteca / ".exportador" / "papelera"
    if papelera.is_dir():
        archivos = [p for p in papelera.rglob("*") if p.is_file()]
        print(f"Papelera: {len(archivos)} archivos, {_mb(sum(p.stat().st_size for p in archivos))}"
              " (se restaura o vacía desde «Limpiar repetidas»)")
    decisiones = biblioteca / ".exportador" / "limpieza.json"
    if decisiones.is_file():
        try:
            datos = json.loads(decisiones.read_text(encoding="utf-8"))
            print(f"Decisiones de «Limpiar repetidas»: {len(datos.get('historial', []))}")
        except (OSError, ValueError):
            pass

    galeria = biblioteca / "galeria.json"
    if galeria.is_file():
        try:
            datos = json.loads(galeria.read_text(encoding="utf-8"))
            elementos = datos.get("elementos", [])
            tipos = collections.Counter(e.get("tipo") for e in elementos)
            dudosas = sum(1 for e in elementos if e.get("fuente_fecha") == "archivo")
            print(f"\nGalería: {len(elementos)} elementos ({', '.join(f'{t}: {n}' for t, n in tipos.items())}),"
                  f" {dudosas} con fecha dudosa (de la fecha del archivo)")
        except (OSError, ValueError):
            print("\nGalería: galeria.json ilegible (regenerarla con `galeria`)")
    else:
        print("\nGalería: no generada (python -m exportador galeria <biblioteca>)")

    informes = sorted((biblioteca / ".exportador" / "informes").glob("*.csv"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    if informes:
        print("\nÚltimos informes:")
        for p in informes[:6]:
            print(f"  {p.name}")


def buscar(biblioteca: Path, texto: str):
    db = _catalogo(biblioteca)
    patron = f"%{texto}%"
    encontrado = False
    if db is not None:
        with db:
            tablas = _tablas(db)
            for f in db.execute("SELECT * FROM archivos WHERE origen LIKE ? OR destino LIKE ? "
                                "LIMIT 50", (patron, patron)):
                encontrado = True
                print(f"IMPORTADO  {f['destino']}\n  origen: {f['origen']}\n  fecha: {f['fecha']}"
                      f" (de {f['fuente_fecha']})  importado: {f['importado'][:16]}"
                      f"  {_mb(f['bytes_antes'])} -> {_mb(f['bytes_despues'])}"
                      + (f"\n  original: {f['original']}" if f["original"] else ""))
            if "descartes" in tablas:
                for f in db.execute("SELECT * FROM descartes WHERE origen LIKE ? OR referencia LIKE ? "
                                    "LIMIT 50", (patron, patron)):
                    encontrado = True
                    print(f"DESCARTADO ({f['motivo']}{', ' + f['problema'] if f['problema'] else ''})"
                          f"  {f['origen']}\n  {f['detalle'] or ''}"
                          + (f"  copia buena: {f['referencia']}" if f["referencia"] else ""))
            if "descartadas" in tablas:
                for f in db.execute("SELECT * FROM descartadas WHERE destino LIKE ? LIMIT 50", (patron,)):
                    encontrado = True
                    print(f"QUITADA con «Limpiar repetidas» el {f['fecha'][:16]}: {f['destino']}")
        db.close()
    papelera = biblioteca / ".exportador" / "papelera"
    if papelera.is_dir():
        for p in papelera.rglob(f"*{texto}*"):
            if p.is_file():
                encontrado = True
                print(f"EN LA PAPELERA  {p.relative_to(papelera).as_posix()}")
    if not encontrado:
        print(f"No aparece «{texto}» en el catálogo ni en la papelera. Si se importó con otro "
              "nombre, prueba con parte del nombre original o de la fecha (20240810).")


def informe(biblioteca: Path, nombre: str = None):
    carpeta = biblioteca / ".exportador" / "informes"
    candidatos = sorted(carpeta.glob(f"{nombre or ''}*.csv"), key=lambda p: p.stat().st_mtime)
    if not candidatos:
        sys.exit(f"No hay informes en {carpeta}")
    ruta = candidatos[-1]
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    print(f"{ruta.name}: {len(filas)} filas")
    # Los informes de dañados no tienen `accion`: se cuentan por problema
    columna = "accion" if filas and "accion" in filas[0] else "problema"
    for valor, n in collections.Counter(f.get(columna) or "?" for f in filas).most_common():
        print(f"  {valor:24} {n}")
    for f in [f for f in filas if f.get("accion") == "ERROR"][:10]:
        print(f"  ERROR {f.get('origen')}: {f.get('detalle')}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("biblioteca", type=Path)
    p.add_argument("--buscar", metavar="TEXTO", help="Parte del nombre o ruta (original o final)")
    p.add_argument("--informe", nargs="?", const="", metavar="PREFIJO",
                   help="Acciones del último informe CSV (o del último que empiece por PREFIJO: "
                        "fotos, videos, audio, fusion, danados)")
    args = p.parse_args()
    biblioteca = args.biblioteca.resolve()
    if not biblioteca.is_dir():
        sys.exit(f"La carpeta no existe: {biblioteca}")
    if args.buscar:
        buscar(biblioteca, args.buscar)
    elif args.informe is not None:
        informe(biblioteca, args.informe or None)
    else:
        resumen(biblioteca)


if __name__ == "__main__":
    main()
