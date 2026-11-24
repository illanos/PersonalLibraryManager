"""Referencia de todos los comandos y opciones del exportador, sacada de su argparse.

    python .claude/skills/exportador/scripts/opciones.py            # Markdown completo
    python .claude/skills/exportador/scripts/opciones.py fusionar   # solo un comando
    python .claude/skills/exportador/scripts/opciones.py --escribir # regenera references/comandos.md

Lee `exportador.cli.construir_parser()`, así que siempre coincide con el programa. Busca
el paquete en el `src/` del proyecto que contiene esta skill y, si no, el instalado.
No ejecuta nada ni toca ninguna biblioteca.
"""

import argparse
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
REFERENCIA = SKILL / "references" / "comandos.md"


def _cargar_parser():
    for carpeta in Path(__file__).resolve().parents:
        if (carpeta / "pyproject.toml").is_file() and (carpeta / "src" / "exportador").is_dir():
            sys.path.insert(0, str(carpeta / "src"))
            break
    from exportador.cli import construir_parser
    return construir_parser()


def _subcomandos(parser):
    for accion in parser._actions:
        if isinstance(accion, argparse._SubParsersAction):
            ayudas = {a.dest: a.help for a in accion._choices_actions}
            return [(nombre, sub, ayudas.get(nombre, "")) for nombre, sub in accion.choices.items()]
    return []


def _celda(texto) -> str:
    return " ".join(str(texto).split()).replace("|", "\\|").replace("%%", "%")


def _es_interruptor(accion) -> bool:
    return isinstance(accion, (argparse._StoreTrueAction, argparse._StoreFalseAction))


def _defecto(accion) -> str:
    if _es_interruptor(accion):
        return "no" if accion.default is False else "sí"
    if not accion.option_strings or accion.default in (None, argparse.SUPPRESS):
        return "—"
    return f"`{accion.default}`"


def _valor(accion) -> str:
    """Lo que va detrás de la opción: sus valores posibles, CARPETA o N."""
    if accion.choices:
        return "\\|".join(str(c) for c in accion.choices)
    if accion.metavar:
        return accion.metavar
    return "CARPETA" if accion.type is Path else "N"


def markdown_comando(nombre, sub, ayuda) -> str:
    lineas = [f"## `{nombre}`", "", _celda(ayuda)]
    if sub.description and _celda(sub.description) != _celda(ayuda):
        lineas += ["", _celda(sub.description)]
    posicionales = [f"<{a.dest}>" for a in sub._actions if not a.option_strings]
    lineas += ["", "`" + " ".join(["python -m exportador", nombre, *posicionales]) + "`"]
    filas = []
    for a in sub._actions:
        if a.help == argparse.SUPPRESS or isinstance(a, argparse._HelpAction):
            continue
        if a.option_strings:
            opcion = ", ".join(f"`{o}`" for o in a.option_strings)
            if not _es_interruptor(a):
                opcion += f" {_valor(a)}"
            if a.required:
                opcion += " *(obligatoria)*"
        else:
            opcion = f"`<{a.dest}>`"
        filas.append(f"| {opcion} | {_defecto(a)} | {_celda(a.help or '')} |")
    lineas += ["", "| Opción | Por defecto | Qué hace |", "|---|---|---|", *filas]
    return "\n".join(lineas)


def markdown(parser, solo=None) -> str:
    partes = []
    if solo is None:
        partes.append(
            "# Comandos y opciones\n\n"
            "Generado de `exportador.cli.construir_parser()` con `scripts/opciones.py` (no "
            "editar a mano: regenerar con `--escribir` si cambia la CLI). Con el paquete "
            "instalado, `exportador` equivale a `python -m exportador`. `-h` en cualquier "
            "comando muestra lo mismo.\n\n"
            "Opciones ocultas por compatibilidad (no las propongas): `--sin-originales` "
            "(ya es lo normal) y, en `videos`, `--max-lado` (= `--max-lado-video`).")
    for nombre, sub, ayuda in _subcomandos(parser):
        if solo in (None, nombre):
            partes.append(markdown_comando(nombre, sub, ayuda))
    if not partes:
        raise SystemExit(f"No existe el comando {solo!r}")
    return "\n\n".join(partes) + "\n"


def main():
    args = sys.argv[1:]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    texto = markdown(_cargar_parser(), None if not args or args[0] == "--escribir" else args[0])
    if args[:1] == ["--escribir"]:
        REFERENCIA.write_text(texto, encoding="utf-8", newline="\n")
        print(f"Escrito {REFERENCIA}")
    else:
        sys.stdout.write(texto)


if __name__ == "__main__":
    main()
