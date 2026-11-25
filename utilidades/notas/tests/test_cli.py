import contextlib
import io
import json
import unittest
import unittest.mock
import zipfile

from notas.cli import construir_parser, main
from notas.cuaderno import Cuaderno
from tests.ayudas import HTML, CasoConCuaderno, png, wav


class CasoCli(CasoConCuaderno):
    def notas(self, *args, entrada="") -> str:
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), unittest.mock.patch("sys.stdin", io.StringIO(entrada)):
            main([args[0], "--cuaderno", str(self.carpeta), *args[1:]])
        return salida.getvalue()

    def error(self, *args) -> str:
        with self.assertRaises(SystemExit) as cm:
            self.notas(*args)
        return str(cm.exception.code)

    def archivo(self, nombre, datos):
        ruta = self.dir / nombre
        ruta.write_bytes(datos)
        return str(ruta)


class Crear(CasoCli):
    def test_nueva_con_todo(self):
        n = json.loads(self.notas("nueva", "Texto", "--titulo", "T", "--categoria", "Casa", "--categoria", "Ideas",
                                  "--adjunto", self.archivo("a.png", png()), "--adjunto", self.archivo("b.wav", wav()),
                                  "--color", "menta", "--fijar", "--json"))
        self.assertEqual((n["titulo"], n["texto"], n["color"], n["fijada"]), ("T", "Texto", "menta", True))
        self.assertEqual([a["tipo"] for a in n["adjuntos"]], ["imagen", "voz"])
        self.assertEqual(len(n["categorias"]), 2)
        self.assertTrue((self.dir / "a.png").is_file())        # el original no se mueve

    def test_desde_la_entrada_estandar(self):
        self.notas("nueva", "-", entrada="línea 1\nlínea 2")
        self.assertEqual(self.c.listar()[0]["texto"], "línea 1\nlínea 2")

    def test_si_un_adjunto_falla_no_se_crea(self):
        self.assertIn("No existe", self.error("nueva", "x", "--adjunto", str(self.dir / "no.png")))
        self.assertIn("no es una imagen", self.error("nueva", "x", "--adjunto", self.archivo("x.png", HTML)))
        self.assertIn("vacía", self.error("nueva", "   "))
        self.assertEqual(self.c.listar(), [])

    def test_solo_se_estrena_el_cuaderno_al_crear(self):
        self.carpeta = self.dir / "otro"
        for args in (["listar"], ["ver", "1"], ["categorias"], ["copia"], ["borrar", "1"]):
            with self.subTest(args=args):
                self.assertIn("No hay ningún cuaderno", self.error(*args))
        self.assertFalse(self.carpeta.exists())
        self.notas("nueva", "x")
        self.assertEqual(len(Cuaderno(self.carpeta).listar()), 1)


class Consultar(CasoCli):
    def test_listar_y_buscar(self):
        self.c.crear("Reunión", "cocina", categorias=["Casa"])
        n = self.c.crear("", "Solo texto\nsegunda línea")
        self.adjuntar(n, wav())
        salida = self.notas("listar")
        self.assertIn("Reunión  [Casa]", salida)
        self.assertIn("Solo texto  [1 voz]", salida)
        self.assertIn("2 notas", salida)
        self.assertIn("1 nota\n", self.notas("listar", "--buscar", "reunion"))
        self.assertIn("Reunión", self.notas("listar", "--categoria", "CASA"))
        self.assertNotIn("Reunión", self.notas("listar", "--sin-categoria"))
        self.assertNotIn("Reunión", self.notas("listar", "--tipo", "voz"))
        self.assertIn("1 nota\n", self.notas("listar", "--limite", "1"))
        self.assertEqual(json.loads(self.notas("listar", "--buscar=-cocina", "--json"))[0]["id"], n["id"])
        self.assertIn("hay: Casa", self.error("listar", "--categoria", "nada"))

    def test_ver(self):
        n = self.c.crear("T", "cuerpo", categorias=["Casa"], fijada=True)
        a = self.adjuntar(n, wav(), "voz.wav", duracion=65)
        salida = self.notas("ver", str(n["id"]))
        for trozo in ("T", "cuerpo", "Casa", "fijada", "[voz] 1:05 voz.wav", a["archivo"].split("/")[-1]):
            self.assertIn(trozo, salida)
        self.assertIn("No existe la nota 99", self.error("ver", "99"))


class Cambiar(CasoCli):
    def test_editar(self):
        n = self.c.crear("A", "uno", "coral", categorias=["Casa"])
        i = str(n["id"])
        self.notas("editar", i, "--anadir", "dos", "--color", "ninguno", "--fijar", "--quitar-categoria", "casa",
                   "--poner-categoria", "Ideas", "--adjunto", self.archivo("a.png", png()))
        n = self.c.nota(n["id"])
        self.assertEqual((n["texto"], n["color"], n["fijada"]), ("uno\ndos", "", True))
        self.assertEqual([c["nombre"] for c in n["categorias"]], ["Ideas"])
        self.assertEqual(len(n["adjuntos"]), 1)
        self.notas("editar", i, "--titulo", "", "--texto", "-", "--archivar", entrada="nuevo")
        n = self.c.nota(n["id"])
        self.assertEqual((n["titulo"], n["texto"], n["archivada"]), ("", "nuevo", True))
        self.assertIn("ningún cambio", self.error("editar", i))

    def test_borrar_y_restaurar(self):
        ids = [str(self.c.crear(t)["id"]) for t in "AB"]
        self.assertIn("No existe", self.error("borrar", ids[0], "99"))
        self.assertEqual(len(self.c.listar()), 2)              # o todas o ninguna
        self.assertIn("2 notas a la papelera", self.notas("borrar", *ids))
        self.assertIn("1 nota fuera", self.notas("restaurar", ids[0]))
        self.assertEqual(self.titulos(), ["A"])

    def test_categorias(self):
        self.notas("categorias", "--crear", "Casa")
        self.notas("categorias", "--renombrar", "casa", "Hogar")
        self.assertEqual(json.loads(self.notas("categorias", "--json"))[0]["nombre"], "Hogar")
        self.notas("categorias", "--borrar", "hogar")
        self.assertIn("No hay categorías", self.notas("categorias"))

    def test_copia(self):
        self.c.crear("A")
        destino = self.dir / "copia.zip"
        self.notas("copia", str(destino))
        self.assertTrue(zipfile.is_zipfile(destino))
        self.assertIn("Ya existe", self.error("copia", str(destino)))


class Importar(CasoCli):
    def test_importar(self):
        self.carpeta = self.dir / "otro"
        (self.dir / "Keep").mkdir()
        (self.dir / "Keep" / "a.json").write_text(json.dumps({
            "color": "RED", "isTrashed": False, "isPinned": False, "isArchived": True, "title": "De Keep",
            "createdTimestampUsec": 1_500_000_000_000_000, "listContent": [{"text": "Pan", "isChecked": True}],
            "annotations": [{"url": "https://e.org", "title": "Página", "description": ""}],
            "sharees": [{"email": "ana@e.org"}], "tasks": [{"id": "x"}]}), encoding="utf-8")
        salida = self.notas("importar", str(self.dir), "--simular")
        self.assertIn("Se importarían 1 nota en", salida)
        self.assertFalse(self.carpeta.exists())
        salida = self.notas("importar", str(self.dir), "--lado", "0", "--calidad", "60")
        self.assertIn("Importadas 1 nota en", salida)
        self.assertIn("1 archivadas", salida)
        self.assertIn("1 listas", salida)
        self.assertIn("1 ya estaban", self.notas("importar", str(self.dir)))
        ver = self.notas("ver", "1")
        for trozo in ("De Keep", "☑ Pan", "https://e.org", "ana@e.org", "recordatorio", "importada de Google Keep"):
            self.assertIn(trozo, ver)
        self.assertIn("No hay notas de Google Keep", self.error("importar", str(self.carpeta)))


class Abrir(CasoCli):
    def test_abrir(self):
        with unittest.mock.patch("notas.servidor.servir") as servir:
            self.notas("abrir", "--puerto", "9000", "--sin-navegador")
        (cuaderno, puerto, navegador), _ = servir.call_args
        self.assertEqual((cuaderno.carpeta, puerto, navegador), (self.carpeta.resolve(), 9000, False))

    def test_cuaderno_ilegible(self):
        (self.dir / "malo").mkdir()
        (self.dir / "malo" / "notas.sqlite").write_bytes(b"esto no es sqlite" * 100)
        self.carpeta = self.dir / "malo"
        self.assertIn("no se puede usar el cuaderno", self.error("listar"))

    def test_opciones_fuera_de_rango(self):
        for args in (["abrir", "--puerto", "0"], ["nueva", "x", "--color", "fucsia"], ["listar", "--tipo", "x"],
                     ["importar", "x", "--lado", "10"], ["importar", "x", "--calidad", "100"]):
            with self.subTest(args=args), self.assertRaises(SystemExit), unittest.mock.patch("sys.stderr"):
                construir_parser().parse_args(args)


if __name__ == "__main__":
    unittest.main()
