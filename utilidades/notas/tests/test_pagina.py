"""La página es coherente: lo que usa el JavaScript existe en el HTML, el CSS y la API."""

import re
import unittest

from notas.cuaderno import COLORES, ORDENES
from notas.servidor import CABECERA_TOKEN, ESTATICOS, PLANTILLAS, ManejadorNotas

HTML, CSS, JS = ((PLANTILLAS / f"notas.{ext}").read_text(encoding="utf-8") for ext in ("html", "css", "js"))


class Pagina(unittest.TestCase):
    def test_los_ids_que_usa_el_javascript_existen(self):
        ids = re.findall(r'\bid="([^"]+)"', HTML)
        self.assertEqual(len(ids), len(set(ids)), "hay ids repetidos")
        usados = set(re.findall(r"""['"(]#([a-z][a-z0-9-]*)(?=['" )])""", JS))
        vistas = {"categoria", "tipo", "archivo", "papelera", "sin-categoria"}     # son direcciones
        self.assertFalse(usados - set(ids) - vistas)

    def test_los_iconos_existen(self):
        iconos = set(re.findall(r"^  (\w+): 'M", JS, re.M))
        self.assertGreater(len(iconos), 20)
        usados = set(re.findall(r'data-icono="(\w+)"', HTML)) | set(re.findall(r"\b(?:icono|boton)\('(\w+)'", JS))
        self.assertFalse(usados - iconos)

    def test_colores_y_ordenes(self):
        self.assertEqual(set(re.findall(r"^\.color-(\w+)", CSS, re.M)), {c for c in COLORES if c})
        orden = re.search(r'<select id="orden".*?</select>', HTML, re.S).group()
        self.assertEqual(set(re.findall(r'value="(\w+)"', orden)), set(ORDENES))

    def test_las_rutas_de_la_api_existen(self):
        self.assertIn(CABECERA_TOKEN, JS)
        patrones = [p for _, p, _ in ManejadorNotas.RUTAS]
        rutas = [a.split("?")[0] or b
                 for a, b in re.findall(r"""pedir\('[A-Z]+', (?:'([^']+)'|`([^`]+)`)""", JS)]
        self.assertGreater(len(rutas), 8)
        for ruta in rutas:
            ruta = re.sub(r"\$\{quitar[^}]*\}", "quitar", ruta)
            ruta = re.sub(r"\$\{[^}]*\}", "1", ruta)
            with self.subTest(ruta=ruta):
                self.assertTrue(any(re.fullmatch(p, ruta) for p in patrones))

    def test_sin_nada_de_fuera_ni_en_linea(self):
        # La CSP lo bloquearía, y la página debe funcionar sin conexión
        self.assertNotRegex(HTML, r"<script(?![^>]*\bsrc=)|<style|\son\w+=|\sstyle=")
        self.assertNotRegex(HTML + CSS, r"https?://")
        self.assertNotRegex(JS, r"innerHTML|outerHTML|insertAdjacentHTML|\beval\(|document\.write")
        for recurso in re.findall(r'(?:src|href)="/estaticos/([^"]+)"', HTML):
            self.assertIn(recurso, ESTATICOS)

    def test_todas_las_plantillas_se_sirven(self):
        self.assertEqual({p.name for p in PLANTILLAS.iterdir()}, set(ESTATICOS))


if __name__ == "__main__":
    unittest.main()
