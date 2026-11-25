"""Crea el esqueleto de una utilidad nueva del monorepo, ya conectada al resto.

    python herramientas/nueva_utilidad.py recetas --titulo "Recetas" \\
        --resumen "Recetas de cocina, con ingredientes y búsqueda"

Copia herramientas/plantilla/: el paquete con su línea de comandos, las pruebas, la
documentación, la guía del agente (CLAUDE.md), la skill y los .bat para abrirla con doble
clic; y regenera los mapas y la tabla del README. No toca las utilidades que ya hay.
"""

import argparse
import keyword
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapas  # noqa: E402

PLANTILLA = Path(__file__).with_name("plantilla")


def comprobar_nombre(raiz: Path, nombre: str):
    """El nombre será carpeta, paquete de Python y comando: tiene que valer para todo."""
    if not re.fullmatch("[a-z][a-z0-9_]{1,30}", nombre):
        raise SystemExit("El nombre lleva solo minúsculas sin acentos, números y _ (p. ej. recetas)")
    if keyword.iskeyword(nombre) or nombre in sys.stdlib_module_names or nombre == "tests":
        raise SystemExit(f"«{nombre}» ya es un nombre de Python: elige otro")
    for u in mapas.utilidades(raiz):
        if nombre in (u.nombre, u.paquete, u.datos["skill"]):
            raise SystemExit(f"Ya hay una utilidad, un paquete o una skill «{nombre}»")


def destinos(raiz: Path, nombre: str) -> dict:
    """{archivo de la plantilla: dónde va}."""
    salida = {}
    for origen in sorted(PLANTILLA.rglob("*")):
        if not origen.is_file() or "__pycache__" in origen.parts:
            continue
        relativa = origen.relative_to(PLANTILLA).as_posix().replace("_nombre_", nombre)
        if relativa == "SKILL.md":
            salida[origen] = raiz / ".claude" / "skills" / nombre / "SKILL.md"
        elif relativa == "raiz.bat":
            salida[origen] = raiz / f"{nombre}.bat"
        else:
            salida[origen] = raiz / "utilidades" / nombre / relativa.removeprefix("utilidad/")
    return salida


def crear(raiz: Path, nombre: str, titulo: str, resumen: str) -> list:
    """Crea la utilidad y devuelve los archivos escritos. Si algo ya existe, no escribe nada."""
    comprobar_nombre(raiz, nombre)
    cambios = {"@@nombre@@": nombre, "@@titulo@@": titulo, "@@resumen@@": resumen}
    for valor in (titulo, resumen):
        if not valor.strip() or re.search(r'["\\\n|]', valor):
            raise SystemExit('El título y el resumen no pueden estar vacíos ni llevar " \\ o |')
    plan = destinos(raiz, nombre)
    if existentes := [d for d in plan.values() if d.exists()]:
        raise SystemExit(f"Ya existe {existentes[0].relative_to(raiz).as_posix()}")
    for origen, destino in plan.items():
        texto = origen.read_text(encoding="utf-8")
        for marca, valor in cambios.items():
            texto = texto.replace(marca, valor)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8",
                           newline="\r\n" if destino.suffix == ".bat" else "\n")
    return [*plan.values(), *mapas.escribir(raiz)]


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("nombre", help="Carpeta, paquete y comando: minúsculas sin acentos (recetas)")
    p.add_argument("--titulo", required=True, help="Nombre para enseñar (Recetas)")
    p.add_argument("--resumen", required=True, help="Para qué sirve, en una frase")
    args = p.parse_args(argv)
    for ruta in crear(mapas.RAIZ, args.nombre, args.titulo, args.resumen):
        print(ruta.relative_to(mapas.RAIZ).as_posix())
    print(f"\nHecho. Siguiente: escribe utilidades/{args.nombre}/CLAUDE.md y la skill, y pasa\n"
          f"las pruebas con  python herramientas/pruebas.py {args.nombre}")


if __name__ == "__main__":
    main()
