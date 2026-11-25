"""El monorepo está completo y sus mapas, al día.

    python -m unittest discover -s tests -t .   (en herramientas/)
"""

import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERRAMIENTAS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERRAMIENTAS))

import mapas  # noqa: E402
import nueva_utilidad  # noqa: E402
import pruebas  # noqa: E402

RAIZ = mapas.RAIZ


class Mapas(unittest.TestCase):
    def test_al_dia(self):
        atrasados = [r.relative_to(RAIZ).as_posix() for r in mapas.atrasados()]
        self.assertEqual(atrasados, [], "regenéralos: python herramientas/mapas.py")

    def test_primera_frase(self):
        self.assertEqual(mapas._primera_frase("Copia de (p. ej. WhatsApp).\nAdemás otra.\n\nMás."),
                         "Copia de (p. ej. WhatsApp)")
        self.assertEqual(mapas._primera_frase("Uno | dos"), "Uno \\| dos")
        self.assertEqual(mapas._primera_frase(None), "")
        self.assertLess(len(mapas._primera_frase("palabra " * 60)), 165)


class Utilidades(unittest.TestCase):
    def setUp(self):
        self.todas = mapas.utilidades()

    def test_estan_todas_las_carpetas(self):
        carpetas = {p.name for p in (RAIZ / "utilidades").iterdir() if p.is_dir()}
        self.assertEqual({u.nombre for u in self.todas}, carpetas)

    def test_completas(self):
        for u in self.todas:
            for archivo in ("README.md", "CLAUDE.md", "MAPA.md", "doc/ARQUITECTURA.md",
                            "tests/__init__.py"):
                with self.subTest(utilidad=u.nombre, archivo=archivo):
                    self.assertTrue((u.carpeta / archivo).is_file())
            with self.subTest(utilidad=u.nombre):
                self.assertTrue(list((u.carpeta / "tests").glob("test_*.py")))
                self.assertTrue((RAIZ / f"{u.nombre}.bat").is_file(), "falta su .bat en la raíz")
                skill = RAIZ / ".claude" / "skills" / u.datos["skill"] / "SKILL.md"
                self.assertTrue(skill.is_file(), "falta su skill")
                self.assertIn(f"\nname: {u.datos['skill']}\n",
                              skill.read_text(encoding="utf-8").replace("\r\n", "\n"))

    def test_sin_puertos_nombres_ni_comandos_repetidos(self):
        puertos = [p for u in self.todas for p in u.datos.get("puertos", [])]
        comandos = [c for u in self.todas for c in u.proyecto.get("scripts", {})]
        for lista in (puertos, comandos, [u.paquete for u in self.todas],
                      [u.datos["skill"] for u in self.todas]):
            self.assertEqual(len(lista), len(set(lista)), lista)

    def test_no_se_importan_entre_si(self):
        paquetes = {u.paquete for u in self.todas}
        for u in self.todas:
            otros = "|".join(paquetes - {u.paquete})
            for ruta in u.carpeta.rglob("*.py"):
                with self.subTest(archivo=ruta.relative_to(RAIZ).as_posix()):
                    self.assertNotRegex(ruta.read_text(encoding="utf-8"),
                                        rf"(?m)^\s*(?:from|import)\s+(?:{otros})\b")

    def test_los_bat_llaman_a_algo_que_existe(self):
        for bat in RAIZ.glob("*.bat"):
            destino = re.search(r'call "%~dp0([^"]+)"', bat.read_text(encoding="utf-8")).group(1)
            self.assertTrue((RAIZ / destino.replace("\\", "/")).is_file(), bat.name)

    def test_las_rutas_que_citan_las_guias_existen(self):
        guias = [RAIZ / "CLAUDE.md", *(u.carpeta / "CLAUDE.md" for u in self.todas)]
        for guia in guias:
            for ruta in re.findall(r"`([\w./-]+/[\w./-]*\.(?:py|md|html|css|js))`",
                                   guia.read_text(encoding="utf-8")):
                bases = [RAIZ, guia.parent, *(p.parent for p in guia.parent.glob("src/*/__init__.py"))]
                with self.subTest(guia=guia.relative_to(RAIZ).as_posix(), ruta=ruta):
                    self.assertTrue(any((b / ruta).exists() for b in bases))

    def test_pruebas_sabe_de_todas(self):
        self.assertEqual(set(pruebas.carpetas()), {u.nombre for u in self.todas} | {"herramientas"})
        with self.assertRaises(SystemExit):
            pruebas.main(["nada"])


class NuevaUtilidad(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        (self.raiz / "utilidades").mkdir()
        (self.raiz / "README.md").write_text(f"# X\n\n{mapas.INICIO}\n{mapas.FIN}\n\nfin\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def crear(self, nombre="recetas"):
        return nueva_utilidad.crear(self.raiz, nombre, "Recetas", "Recetas de cocina, con búsqueda")

    def test_nace_completa_y_con_sus_pruebas_en_verde(self):
        creados = self.crear()
        self.assertTrue(all(r.is_file() for r in creados))
        for ruta in creados:
            self.assertNotRegex(ruta.read_text(encoding="utf-8"), r"@@|_nombre_", ruta.name)
        carpeta = self.raiz / "utilidades" / "recetas"
        for archivo in ("README.md", "CLAUDE.md", "MAPA.md", "doc/ARQUITECTURA.md", "src/recetas/cli.py"):
            self.assertTrue((carpeta / archivo).is_file(), archivo)
        self.assertTrue((self.raiz / ".claude" / "skills" / "recetas" / "SKILL.md").is_file())
        self.assertIn(b"\r\n", (self.raiz / "recetas.bat").read_bytes())
        readme = (self.raiz / "README.md").read_text(encoding="utf-8")
        self.assertIn("[Recetas](utilidades/recetas/README.md)", readme)
        self.assertTrue(readme.endswith("fin\n"))
        self.assertEqual(mapas.atrasados(self.raiz), [])
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                           cwd=carpeta, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr.decode(errors="replace"))

    def test_no_pisa_nada(self):
        self.crear()
        with self.assertRaises(SystemExit):
            self.crear()
        (self.raiz / "cine.bat").write_text("mío")
        with self.assertRaisesRegex(SystemExit, "cine.bat"):
            self.crear("cine")
        self.assertFalse((self.raiz / "utilidades" / "cine").exists())

    def test_nombres_no_validos(self):
        for nombre in ("Recetas", "mis recetas", "../x", "1x", "x", "class", "json", "tests", "niño"):
            with self.subTest(nombre=nombre), self.assertRaises(SystemExit):
                self.crear(nombre)
        for titulo, resumen in (("", "x"), ("a", " "), ('a"b', "x"), ("a", "x|y")):
            with self.assertRaises(SystemExit):
                nueva_utilidad.crear(self.raiz, "recetas", titulo, resumen)
        self.assertEqual(list((self.raiz / "utilidades").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
