"""Mapas del monorepo para el agente (y para las personas), generados del código.

    python herramientas/mapas.py               # regenera los mapas
    python herramientas/mapas.py --comprobar   # solo dice si están al día (código 1 si no)

Escribe:
    MAPA.md                      qué utilidades hay y dónde está cada cosa
    utilidades/<x>/MAPA.md       cada módulo: qué hace, qué usa, quién lo usa y sus pruebas
    README.md                    la tabla de utilidades (entre los comentarios `utilidades`)

Todo sale de `pyproject.toml` (sección [tool.monorepo]) y del propio código (docstrings e
imports), sin ejecutarlo. No se editan a mano: si un mapa no dice lo que debería, se
arregla el docstring. Solo necesita la biblioteca estándar (Python 3.11+, por tomllib).
"""

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    sys.exit("herramientas/ necesita Python 3.11 o superior")

RAIZ = Path(__file__).resolve().parents[1]
AVISO = ("<!-- Generado por herramientas/mapas.py. No editar a mano: "
         "`python herramientas/mapas.py` -->")
INICIO, FIN = "<!-- utilidades:inicio -->", "<!-- utilidades:fin -->"
OBLIGATORIOS = ("titulo", "resumen", "abrir", "datos", "skill")


# --- leer el monorepo ---

@dataclass
class Modulo:
    """Un módulo Python de una utilidad, leído sin ejecutarlo."""
    nombre: str
    archivo: str
    resumen: str
    simbolos: list = field(default_factory=list)     # (nombre, resumen, [métodos])
    usa: set = field(default_factory=set)            # otros módulos del mismo paquete
    pruebas: set = field(default_factory=set)


@dataclass
class Utilidad:
    """Una carpeta de utilidades/ con su pyproject.toml."""
    nombre: str
    carpeta: Path
    paquete: str
    datos: dict                                       # [tool.monorepo]
    proyecto: dict                                    # [project]
    modulos: list = field(default_factory=list)
    otros: list = field(default_factory=list)         # archivos del paquete que no son .py

    @property
    def ruta(self) -> str:
        return f"utilidades/{self.nombre}"


def utilidades(raiz: Path = RAIZ) -> list:
    """Todas las utilidades del monorepo, por orden alfabético."""
    encontradas = []
    for pyproject in sorted((raiz / "utilidades").glob("*/pyproject.toml")):
        datos = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        monorepo = datos.get("tool", {}).get("monorepo", {})
        faltan = [c for c in OBLIGATORIOS if not monorepo.get(c)]
        if faltan:
            raise SystemExit(f"{pyproject.relative_to(raiz).as_posix()}: falta en [tool.monorepo]: "
                             + ", ".join(faltan))
        carpeta = pyproject.parent
        paquetes = sorted(p.parent for p in (carpeta / "src").glob("*/__init__.py"))
        if len(paquetes) != 1:
            raise SystemExit(f"{carpeta.name}: se espera un paquete en src/ (hay {len(paquetes)})")
        u = Utilidad(carpeta.name, carpeta, paquetes[0].name, monorepo, datos["project"])
        _leer_paquete(u, paquetes[0])
        encontradas.append(u)
    return encontradas


def _primera_frase(doc: str) -> str:
    """La primera frase del docstring, en una línea."""
    parrafo = " ".join((doc or "").strip().split("\n\n")[0].split())
    # Acaba en un punto seguido de mayúscula: así no corta en «p. ej.»
    m = re.match(r"(.+?(?<! ej)\.)(?=\s+[A-ZÁÉÍÓÚÑ¿«]|$)", parrafo)
    frase = m.group(1) if m else parrafo
    if len(frase) > 160:
        frase = frase[:157].rsplit(" ", 1)[0] + "…"
    return frase.rstrip(".: ").replace("|", "\\|")


# Métodos que pide http.server: no dicen nada de lo que hace el módulo
_DE_HTTP = re.compile("do_[A-Z]+|log_message|end_headers|handle_error")


def _es_publico(nodo) -> bool:
    return not nodo.name.startswith("_") and not _DE_HTTP.fullmatch(nodo.name)


def _leer_paquete(u: Utilidad, carpeta: Path):
    for ruta in sorted(carpeta.rglob("*")):
        if not ruta.is_file() or "__pycache__" in ruta.parts:
            continue
        relativa = ruta.relative_to(carpeta).as_posix()
        if ruta.suffix == ".py":
            u.modulos.append(_leer_modulo(ruta, relativa))
        else:
            u.otros.append(relativa)
    nombres = {m.nombre for m in u.modulos}
    for m in u.modulos:
        m.usa &= nombres - {m.nombre}
    _leer_pruebas(u)


def _leer_modulo(ruta: Path, relativa: str) -> Modulo:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    nombre = relativa[:-3].replace("/", ".").removesuffix(".__init__")
    m = Modulo(nombre, relativa, _primera_frase(ast.get_docstring(arbol)))
    for nodo in arbol.body:
        if isinstance(nodo, ast.ClassDef) and _es_publico(nodo):
            metodos = [n.name for n in nodo.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _es_publico(n)]
            m.simbolos.append((f"class {nodo.name}", _primera_frase(ast.get_docstring(nodo)), metodos))
        elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and _es_publico(nodo):
            m.simbolos.append((f"{nodo.name}()", _primera_frase(ast.get_docstring(nodo)), []))
    for nodo in ast.walk(arbol):          # también los imports dentro de funciones
        if isinstance(nodo, ast.ImportFrom) and nodo.level == 1:
            if nodo.module:
                m.usa.add(nodo.module)
            else:
                m.usa.update(a.name for a in nodo.names)
    return m


def _leer_pruebas(u: Utilidad):
    """Qué pruebas importan cada módulo."""
    por_nombre = {m.nombre: m for m in u.modulos}
    for ruta in sorted((u.carpeta / "tests").glob("test_*.py")):
        for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
            usados = []
            if isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                if nodo.module == u.paquete:
                    usados = [a.name for a in nodo.names]
                elif nodo.module.startswith(u.paquete + "."):
                    usados = [nodo.module[len(u.paquete) + 1:]]
            elif isinstance(nodo, ast.Import):
                usados = [a.name[len(u.paquete) + 1:] for a in nodo.names
                          if a.name.startswith(u.paquete + ".")]
            for nombre in usados:
                if nombre in por_nombre:
                    por_nombre[nombre].pruebas.add(ruta.stem)


# --- escribir los mapas ---

def _lista(nombres) -> str:
    return ", ".join(f"`{n}`" for n in sorted(nombres)) or "—"


def mapa_utilidad(u: Utilidad) -> str:
    """utilidades/<x>/MAPA.md: los módulos de una utilidad y lo que hay en cada uno."""
    modulos = [m for m in u.modulos if not Path(m.archivo).name.startswith("__")]
    usan = {m.nombre: {o.nombre for o in u.modulos if m.nombre in o.usa} for m in modulos}
    lineas = [f"# Mapa de {u.datos['titulo']}", "", AVISO, "",
              f"Paquete `{u.paquete}` (`src/{u.paquete}/`). Las rutas son relativas a `{u.ruta}/`. "
              "Para el porqué de las cosas, `doc/ARQUITECTURA.md`; para cómo trabajar aquí, `CLAUDE.md`.",
              "", "## Módulos", "", "| Módulo | Qué hace | Usa | Lo usan | Pruebas (`tests/`) |",
              "|---|---|---|---|---|"]
    for m in modulos:
        lineas.append(f"| `{m.archivo}` | {m.resumen or '—'} | {_lista(m.usa)} | "
                      f"{_lista(usan[m.nombre])} | {_lista(m.pruebas)} |")
    if u.otros:
        lineas += ["", "Otros archivos del paquete: " + _lista(u.otros) + "."]
    lineas += ["", "## Qué hay en cada módulo", "",
               "Solo lo público (sin `_` delante), en el orden en que aparece."]
    for m in modulos:
        if not m.simbolos:
            continue
        lineas += ["", f"### `{m.archivo}`", ""]
        for nombre, resumen, metodos in m.simbolos:
            linea = f"- `{nombre}`" + (f" — {resumen}" if resumen else "")
            if metodos:
                linea += "\n  - " + ", ".join(f"`.{x}`" for x in metodos)
            lineas.append(linea)
    return "\n".join(lineas) + "\n"


def _puertos(u: Utilidad) -> str:
    return ", ".join(str(p) for p in u.datos.get("puertos", [])) or "—"


def mapa_raiz(todas: list) -> str:
    """MAPA.md de la raíz: qué utilidades hay y dónde está cada cosa."""
    lineas = ["# Mapa del monorepo", "", AVISO, "", "## Utilidades", "",
              "| Utilidad | Para qué | Código | Se abre con | Datos del usuario | Puertos | Skill |",
              "|---|---|---|---|---|---|---|"]
    for u in todas:
        lineas.append(f"| **{u.datos['titulo']}** | {u.datos['resumen']} | `{u.ruta}/src/{u.paquete}/` | "
                      f"{u.datos['abrir']} | {u.datos['datos']} | {_puertos(u)} | "
                      f"`{u.datos['skill']}` |")
    lineas += ["", "## Dónde mirar", "",
               "| Utilidad | Cómo trabajar en ella | Mapa del código | Decisiones | Pruebas |",
               "|---|---|---|---|---|"]
    for u in todas:
        lineas.append(f"| {u.datos['titulo']} | `{u.ruta}/CLAUDE.md` | `{u.ruta}/MAPA.md` | "
                      f"`{u.ruta}/doc/ARQUITECTURA.md` | `cd {u.ruta}` y "
                      "`python -m unittest discover -s tests -t .` |")
    return "\n".join(lineas) + "\n"


def tabla_readme(todas: list) -> str:
    """La tabla de utilidades del README de la raíz."""
    lineas = ["| Utilidad | Para qué | Se abre con |", "|---|---|---|"]
    lineas += [f"| [{u.datos['titulo']}]({u.ruta}/README.md) | {u.datos['resumen']} | {u.datos['abrir']} |"
               for u in todas]
    return "\n".join(lineas)


def documentos(raiz: Path = RAIZ) -> dict:
    """{ruta: contenido que debería tener} de todo lo que se genera."""
    todas = utilidades(raiz)
    salida = {raiz / "MAPA.md": mapa_raiz(todas)}
    salida.update({u.carpeta / "MAPA.md": mapa_utilidad(u) for u in todas})
    readme = raiz / "README.md"
    if readme.is_file():
        texto = _leer(readme)
        if INICIO not in texto or FIN not in texto:
            raise SystemExit(f"README.md: faltan los comentarios {INICIO} y {FIN}")
        antes, resto = texto.split(INICIO, 1)
        salida[readme] = f"{antes}{INICIO}\n\n{tabla_readme(todas)}\n\n{FIN}{resto.split(FIN, 1)[1]}"
    return salida


def _leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8").replace("\r\n", "\n") if ruta.is_file() else ""


def atrasados(raiz: Path = RAIZ) -> list:
    """Rutas de los mapas que no coinciden con el código."""
    return [ruta for ruta, texto in documentos(raiz).items() if _leer(ruta) != texto]


def escribir(raiz: Path = RAIZ) -> list:
    """Regenera los mapas que no estén al día y devuelve sus rutas."""
    cambiados = []
    for ruta, texto in documentos(raiz).items():
        if _leer(ruta) != texto:
            ruta.write_text(texto, encoding="utf-8", newline="\n")
            cambiados.append(ruta)
    return cambiados


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--comprobar", action="store_true", help="No escribir: solo decir si están al día")
    args = p.parse_args(argv)
    rutas = atrasados() if args.comprobar else escribir()
    for ruta in rutas:
        print(("atrasado: " if args.comprobar else "escrito: ") + ruta.relative_to(RAIZ).as_posix())
    if not rutas:
        print("Los mapas están al día")
    elif args.comprobar:
        sys.exit("Regenera los mapas: python herramientas/mapas.py")


if __name__ == "__main__":
    main()
