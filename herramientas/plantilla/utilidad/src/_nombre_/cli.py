"""Línea de comandos de @@titulo@@."""

import argparse
import sys

from . import __version__


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="@@nombre@@", description="@@resumen@@.")
    parser.add_argument("--version", action="version", version=f"@@nombre@@ {__version__}")
    sub = parser.add_subparsers(dest="comando")
    sub.add_parser("estado", help="Comprobar que la utilidad funciona")
    return parser


def main(argv=None):
    parser = construir_parser()
    args = parser.parse_args(argv)
    if args.comando == "estado":
        print("@@titulo@@: todo en orden")
    else:
        parser.print_help()


def ejecutar():
    """Punto de entrada: consola en UTF-8 y salida limpia al interrumpir."""
    for flujo in (sys.stdout, sys.stderr, sys.stdin):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8")
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
