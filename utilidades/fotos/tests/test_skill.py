"""La skill de Claude Code (.claude/skills/exportador) sigue al día con la CLI."""

import argparse
import importlib.util
import re
import unittest
from pathlib import Path

from exportador.cli import construir_parser

# Las skills están en la raíz del monorepo: tests -> fotos -> utilidades -> raíz
SKILL = Path(__file__).resolve().parents[3] / ".claude" / "skills" / "exportador"
REGENERAR = "python .claude/skills/exportador/scripts/opciones.py --escribir"
# Opciones de los scripts de la propia skill, no de la CLI
OPCIONES_SCRIPTS = {"--escribir", "--buscar", "--informe"}


def _script_opciones():
    spec = importlib.util.spec_from_file_location("opciones_skill", SKILL / "scripts" / "opciones.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _opciones_cli(parser) -> set:
    opciones = set()
    for accion in parser._actions:
        opciones.update(accion.option_strings)
        if isinstance(accion, argparse._SubParsersAction):
            for sub in accion.choices.values():
                opciones |= _opciones_cli(sub)
    return opciones


class TestSkill(unittest.TestCase):
    def test_referencia_de_comandos_al_dia(self):
        esperado = _script_opciones().markdown(construir_parser())
        actual = (SKILL / "references" / "comandos.md").read_text(encoding="utf-8")
        self.assertEqual(actual.replace("\r\n", "\n"), esperado,
                         f"references/comandos.md no coincide con la CLI: {REGENERAR}")

    def test_opciones_citadas_existen(self):
        validas = _opciones_cli(construir_parser()) | OPCIONES_SCRIPTS
        for md in SKILL.rglob("*.md"):
            texto = md.read_text(encoding="utf-8")
            citadas = {o for o in re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", texto)
                       if not o.endswith("-")}   # «--descargar-…» abrevia varias
            with self.subTest(archivo=md.name):
                self.assertFalse(citadas - validas, "opciones que la CLI no tiene")

    def test_comandos_citados_existen(self):
        parser = construir_parser()
        comandos = next(a.choices for a in parser._actions
                        if isinstance(a, argparse._SubParsersAction))
        for md in SKILL.rglob("*.md"):
            texto = md.read_text(encoding="utf-8")
            citados = set(re.findall(r"(?:python -m exportador|`exportador) ([a-z]+)\b", texto))
            with self.subTest(archivo=md.name):
                self.assertFalse(citados - set(comandos), "comandos que la CLI no tiene")


if __name__ == "__main__":
    unittest.main()
