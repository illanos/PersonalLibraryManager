"""La skill de Claude Code (.claude/skills/notas) sigue al día con la línea de comandos."""

import argparse
import re
import unittest
from pathlib import Path

from notas.cli import construir_parser
from notas.cuaderno import COLORES

# Las skills están en la raíz del monorepo: tests -> notas -> utilidades -> raíz
SKILL = Path(__file__).resolve().parents[3] / ".claude" / "skills" / "notas" / "SKILL.md"


def _comandos() -> dict:
    """{comando: sus opciones}."""
    sub = next(a for a in construir_parser()._actions if isinstance(a, argparse._SubParsersAction))
    return {nombre: {o for a in p._actions for o in a.option_strings if o.startswith("--")} - {"--help"}
            for nombre, p in sub.choices.items()}


class TestSkill(unittest.TestCase):
    def setUp(self):
        self.texto = SKILL.read_text(encoding="utf-8")
        self.comandos = _comandos()

    def test_todo_lo_que_hay_esta_explicado(self):
        for comando, opciones in self.comandos.items():
            self.assertRegex(self.texto, rf"`{comando}\b", f"falta el comando {comando}")
            for opcion in opciones:
                with self.subTest(comando=comando, opcion=opcion):
                    self.assertRegex(self.texto, rf"{opcion}(?![\w-])")

    def test_las_opciones_citadas_existen(self):
        validas = set().union(*self.comandos.values())
        citadas = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", self.texto))
        self.assertFalse(citadas - validas)

    def test_los_comandos_citados_existen(self):
        citados = set(re.findall(r"python -m notas ([a-z]+)\b", self.texto))
        self.assertTrue(citados)
        self.assertFalse(citados - set(self.comandos))

    def test_colores(self):
        linea = next(l for l in self.texto.splitlines() if l.startswith("- Colores:"))
        self.assertEqual(set(re.findall(r"[a-z]+", linea.split(":")[1])), {c for c in COLORES if c})


if __name__ == "__main__":
    unittest.main()
