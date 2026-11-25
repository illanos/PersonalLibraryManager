"""Pasa las pruebas de todo el monorepo, o solo de las utilidades que se digan.

    python herramientas/pruebas.py               # todas las utilidades y las herramientas
    python herramientas/pruebas.py notas         # solo las de utilidades/notas
    python herramientas/pruebas.py herramientas  # solo las de herramientas/

Cada utilidad se prueba en su propio proceso y desde su carpeta, como si fuera un proyecto
aparte: así no se mezclan sus paquetes `tests`.
"""

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def carpetas(raiz: Path = RAIZ) -> dict:
    """{nombre: carpeta desde la que se lanzan sus pruebas}."""
    con_pruebas = {p.parent.name: p.parent for p in sorted((raiz / "utilidades").glob("*/tests"))}
    return {**con_pruebas, "herramientas": raiz / "herramientas"}


def main(argv=None):
    todas = carpetas()
    pedidas = (sys.argv[1:] if argv is None else argv) or list(todas)
    if desconocidas := [n for n in pedidas if n not in todas]:
        sys.exit(f"No hay pruebas de: {', '.join(desconocidas)} (hay: {', '.join(todas)})")
    fallan = []
    for nombre in pedidas:
        print(f"== {nombre}", flush=True)
        orden = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]
        if subprocess.run(orden, cwd=todas[nombre]).returncode:
            fallan.append(nombre)
    if fallan:
        sys.exit(f"FALLAN: {', '.join(fallan)}")
    print(f"Todo bien: {', '.join(pedidas)}")


if __name__ == "__main__":
    main()
