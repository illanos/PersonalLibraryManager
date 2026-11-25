import contextlib
import os
import sqlite3
import unittest
import unittest.mock
from pathlib import Path

from notas.cuaderno import (ARCHIVO_BD, SIN_CATEGORIA, Cuaderno, carpeta_cuaderno, normalizar,
                            terminos)
from notas.errores import Conflicto, ErrorNotas, NoEncontrada
from tests.ayudas import CasoConCuaderno, png, wav


class Carpeta(unittest.TestCase):
    def test_elegida_variable_o_la_de_siempre(self):
        with unittest.mock.patch.dict(os.environ, {"NOTAS_CUADERNO": str(Path("x").resolve())}):
            self.assertEqual(carpeta_cuaderno(), Path("x").resolve())
            self.assertEqual(carpeta_cuaderno("y"), Path("y").resolve())
        with unittest.mock.patch.dict(os.environ, {"NOTAS_CUADERNO": ""}):
            self.assertEqual(carpeta_cuaderno(), Path.home() / "Notas")


class Notas(CasoConCuaderno):
    def test_crear_y_leer(self):
        n = self.c.crear("Título", "Texto\r\ncon dos líneas", "menta", True, ["Casa", "Ideas"])
        self.assertEqual(self.c.nota(n["id"]), n)
        self.assertEqual((n["titulo"], n["texto"]), ("Título", "Texto\ncon dos líneas"))
        self.assertEqual([c["nombre"] for c in n["categorias"]], ["Casa", "Ideas"])
        self.assertTrue(n["fijada"])
        self.assertEqual(n["adjuntos"], [])

    def test_editar_solo_lo_que_se_pide(self):
        n = self.c.crear("A", "b", "coral", False, ["Casa"])
        n2 = self.c.editar(n["id"], texto="c")
        self.assertEqual((n2["titulo"], n2["texto"], n2["color"]), ("A", "c", "coral"))
        self.assertEqual(n2["categorias"], n["categorias"])
        self.assertEqual(n2["version"], n["version"] + 1)

    def test_lo_que_no_es_texto_no_cuenta_como_modificada(self):
        n = self.c.crear("A", "b")
        n2 = self.c.editar(n["id"], color="cielo", fijada=True, categorias=["Casa"], texto="b")
        self.assertEqual((n2["modificada"], n2["version"]), (n["modificada"], n["version"]))

    def test_conflicto_no_pisa_el_cambio_de_otra_ventana(self):
        n = self.c.crear("A", "original")
        self.c.editar(n["id"], n["version"], texto="de la otra ventana")
        with self.assertRaises(Conflicto) as cm:
            self.c.editar(n["id"], n["version"], texto="mío")
        self.assertEqual(cm.exception.nota["texto"], "de la otra ventana")
        self.assertEqual(self.c.nota(n["id"])["texto"], "de la otra ventana")
        # Cambiar el color no choca con un texto que no se toca
        self.c.editar(n["id"], n["version"], color="rosa", texto="de la otra ventana")

    def test_si_algo_falla_no_se_guarda_nada(self):
        n = self.c.crear("A", "b")
        with self.assertRaises(ErrorNotas):
            self.c.editar(n["id"], texto="cambiado", color="fucsia")
        self.assertEqual(self.c.nota(n["id"])["texto"], "b")
        with self.assertRaises(ErrorNotas):
            self.c.crear("otra", categorias=["bien", "   "])
        self.assertEqual(self.titulos(), ["A"])
        self.assertEqual(self.c.categorias(), [])

    def test_datos_no_validos(self):
        for campos in ({"titulo": 3}, {"texto": None}, {"titulo": "x" * 501}, {"color": ["coral"]},
                       {"categorias": "Casa"}, {"categorias": [1]}, {"categorias": ["x" * 61]}):
            with self.subTest(campos=campos), self.assertRaises(ErrorNotas):
                self.c.crear(**campos)
        for ids in (None, "1", ["1"], [True], [0], [2 ** 70]):
            with self.subTest(ids=ids), self.assertRaises(ErrorNotas):
                self.c.lote(ids, "fijar")
        with self.assertRaises(ErrorNotas):
            self.c.lote([1], "explotar")
        with self.assertRaises(NoEncontrada):
            self.c.nota(99)

    def test_caracteres_raros(self):
        n = self.c.crear("a\x00b", "medio emoji \ud83d y entero 😀")
        self.assertEqual(n["titulo"], "ab")
        self.assertIn("😀", self.c.nota(n["id"])["texto"])

    def test_orden(self):
        for titulo in ("Óscar", "zeta", "alfa", ""):
            self.c.crear(titulo, "x")
        self.assertEqual(self.titulos(orden="titulo"), ["alfa", "Óscar", "zeta", ""])
        self.assertEqual(self.titulos(orden="creada"), ["", "alfa", "zeta", "Óscar"])
        ids = {n["titulo"]: n["id"] for n in self.c.listar()}
        self.c.lote([ids["zeta"]], "fijar")
        self.assertEqual(self.titulos(orden="titulo")[0], "zeta")
        self.assertEqual(len(self.c.listar(limite=2)), 2)


class Busqueda(CasoConCuaderno):
    def test_normalizar_y_terminos(self):
        self.assertEqual(normalizar("REUNIÓN Ñandú"), "reunion nandu")
        self.assertEqual(terminos('Pan -leche "dos cosas" -"otra frase"'),
                         [(False, "pan"), (True, "leche"), (False, "dos cosas"),
                          (True, "otra frase")])
        self.assertEqual(terminos('  - "" '), [])

    def test_todas_las_palabras_sin_acentos(self):
        self.c.crear("Reunión", "con el instalador de la cocina")
        self.c.crear("Cocina", "presupuesto")
        self.assertEqual(self.titulos(buscar="reunion COCINA"), ["Reunión"])
        self.assertEqual(sorted(self.titulos(buscar="cocina")), ["Cocina", "Reunión"])
        self.assertEqual(self.titulos(buscar="cocina -instalador"), ["Cocina"])
        self.assertEqual(self.titulos(buscar='"instalador de la"'), ["Reunión"])
        self.assertEqual(self.titulos(buscar="instalacion"), [])

    def test_en_categorias_y_nombres_de_adjuntos(self):
        n = self.c.crear("Uno", "", categorias=["Jardinería"])
        self.adjuntar(n, png(), "Plano del garaje.png")
        self.c.crear("Dos")
        self.assertEqual(self.titulos(buscar="jardineria"), ["Uno"])
        self.assertEqual(self.titulos(buscar="garaje"), ["Uno"])
        self.assertEqual(self.titulos(buscar="-garaje"), ["Dos"])

    def test_los_comodines_son_texto(self):
        self.c.crear("Descuento", "50% en 'ropa'")
        self.c.crear("Otra", "nada")
        self.assertEqual(self.titulos(buscar="%"), ["Descuento"])
        self.assertEqual(self.titulos(buscar="'ropa'"), ["Descuento"])
        self.assertEqual(self.titulos(buscar="_"), [])

    def test_se_busca_el_texto_nuevo_al_editar(self):
        n = self.c.crear("A", "viejo")
        self.c.editar(n["id"], texto="nuevo")
        self.assertEqual(self.titulos(buscar="viejo"), [])
        self.assertEqual(self.titulos(buscar="nuevo"), ["A"])

    def test_por_tipo(self):
        self.c.crear("texto")
        self.adjuntar(self.c.crear("foto"), png())
        ambas = self.c.crear("ambas")
        self.adjuntar(ambas, png())
        voz = self.adjuntar(ambas, wav())
        self.assertEqual(self.titulos(tipo="texto"), ["texto"])
        self.assertEqual(sorted(self.titulos(tipo="imagen")), ["ambas", "foto"])
        self.assertEqual(self.titulos(tipo="voz"), ["ambas"])
        self.c.quitar_adjunto(voz["id"])
        self.assertEqual(self.titulos(tipo="voz"), [])


class Vistas(CasoConCuaderno):
    def test_archivar_suelta_y_fijar_desarchiva(self):
        n = self.c.crear("A", fijada=True)
        self.c.lote([n["id"]], "archivar")
        n = self.c.nota(n["id"])
        self.assertEqual((n["fijada"], n["archivada"]), (False, True))
        self.assertEqual((self.titulos(), self.titulos(vista="archivadas")), ([], ["A"]))
        self.assertEqual(self.titulos(vista="todas"), ["A"])
        n = self.c.editar(n["id"], fijada=True)
        self.assertEqual((n["fijada"], n["archivada"]), (True, False))

    def test_papelera(self):
        n = self.c.crear("A", "x", categorias=["Casa"])
        self.assertEqual(self.c.lote([n["id"]], "papelera"), 1)
        self.assertEqual(self.c.lote([n["id"]], "papelera"), 0)
        self.assertEqual((self.titulos(vista="todas"), self.titulos(vista="papelera")), ([], ["A"]))
        with self.assertRaises(ErrorNotas):
            self.c.editar(n["id"], texto="y")
        with self.assertRaises(ErrorNotas):
            self.adjuntar(n, png())
        self.assertEqual(self.c.lote([n["id"]], "color", "coral"), 0)
        self.c.lote([n["id"]], "restaurar")
        n = self.c.nota(n["id"])
        self.assertEqual((n["texto"], n["papelera"], len(n["categorias"])), ("x", None, 1))

    def test_eliminar_solo_lo_que_esta_en_la_papelera(self):
        a, b = self.c.crear("A"), self.c.crear("B")
        self.adjuntar(a, png())
        self.c.lote([a["id"]], "papelera")
        self.assertEqual(self.c.eliminar([a["id"], b["id"]]), 1)
        self.assertEqual((self.titulos(vista="todas"), self.en_disco()), (["B"], []))

    def test_vaciar_papelera(self):
        a, b = self.c.crear("A"), self.c.crear("B")
        self.adjuntar(a, png())
        quitado, queda = self.adjuntar(b, png()), self.adjuntar(b, wav())
        self.c.quitar_adjunto(quitado["id"])
        self.c.lote([a["id"]], "papelera")
        for confirmar in (None, "", "vaciar", True):
            with self.assertRaises(ErrorNotas):
                self.c.vaciar_papelera(confirmar)
        self.assertEqual(len(self.en_disco()), 3)
        self.assertEqual(self.c.vaciar_papelera("VACIAR"), 1)
        self.assertEqual(self.en_disco(), [queda["archivo"]])
        self.assertEqual(self.titulos(), ["B"])

    def test_totales(self):
        n = self.c.crear("A", categorias=["Casa"])
        self.adjuntar(n, png())
        self.adjuntar(n, png())
        self.c.lote([self.c.crear("B")["id"]], "archivar")
        self.c.lote([self.c.crear("C")["id"]], "papelera")
        self.c.crear("D")
        t = self.c.estado()["totales"]
        self.assertEqual((t["activas"], t["archivadas"], t["papelera"], t["todas"]), (2, 1, 1, 3))
        self.assertEqual((t["imagen"], t["voz"], t["texto"], t["sin_categoria"]), (1, 0, 1, 1))


class Categorias(CasoConCuaderno):
    def nombres(self):
        return [c["nombre"] for c in self.c.categorias()]

    def test_no_se_repiten_por_acentos_ni_mayusculas(self):
        self.c.crear("A", categorias=["Cocina  fácil", "cocina facil", "COCINA FÁCIL"])
        self.assertEqual(self.nombres(), ["Cocina fácil"])
        self.assertEqual(self.c.buscar_categoria("cocina FACIL"), self.c.categorias()[0]["id"])
        with self.assertRaises(ErrorNotas):
            self.c.crear_categoria("Cocina facil")

    def test_agrupar_y_contar(self):
        a = self.c.crear("A", categorias=["Casa", "Ideas"])
        self.c.crear("B", categorias=["Casa"])
        self.c.crear("C")
        totales = {c["nombre"]: c["total"] for c in self.c.categorias()}
        self.assertEqual(totales, {"Casa": 2, "Ideas": 1})
        casa = self.c.buscar_categoria("casa")
        self.assertEqual(sorted(self.titulos(categoria=casa)), ["A", "B"])
        self.assertEqual(self.titulos(categoria=SIN_CATEGORIA), ["C"])
        self.c.lote([a["id"]], "archivar")
        self.assertEqual(self.titulos(categoria=casa), ["B"])

    def test_renombrar(self):
        self.c.crear("A", categorias=["Casa"])
        self.c.crear_categoria("Ideas")
        casa = self.c.buscar_categoria("Casa")
        self.c.renombrar_categoria(casa, "Hogar")
        self.assertEqual(self.c.listar()[0]["categorias"][0]["nombre"], "Hogar")
        self.c.renombrar_categoria(casa, "HOGAR")      # solo cambia cómo se escribe
        with self.assertRaises(ErrorNotas):
            self.c.renombrar_categoria(casa, "ideas")
        with self.assertRaises(NoEncontrada):
            self.c.renombrar_categoria(99, "x")

    def test_quitar_una_categoria_no_borra_sus_notas(self):
        self.c.crear("A", categorias=["Casa", "Ideas"])
        self.c.borrar_categoria(self.c.buscar_categoria("Casa"))
        self.assertEqual([c["nombre"] for c in self.c.listar()[0]["categorias"]], ["Ideas"])
        with self.assertRaises(NoEncontrada):
            self.c.borrar_categoria(99)

    def test_en_lote(self):
        ids = [self.c.crear(t)["id"] for t in "ABC"]
        self.c.lote(ids[:1], "poner_categoria", "casa")
        self.assertEqual(self.c.lote(ids, "poner_categoria", "Casa"), 2)     # una ya la tenía
        self.assertEqual(self.c.lote(ids[:2], "quitar_categoria", "CASA"), 2)
        self.assertEqual(self.titulos(categoria=self.c.buscar_categoria("casa")), ["C"])


class Adjuntos(CasoConCuaderno):
    def test_adjuntar_quitar_y_recuperar(self):
        n = self.c.crear("A")
        voz = self.adjuntar(n, wav(), "nota.wav", duracion="2.5")
        self.assertEqual((voz["tipo"], voz["duracion"], voz["miniatura"]), ("voz", 2.5, None))
        imagen = self.adjuntar(n, png(), "dibujo.png", duracion="9")
        self.assertEqual((imagen["tipo"], imagen["duracion"]), ("imagen", None))
        self.assertEqual([a["nombre"] for a in self.c.nota(n["id"])["adjuntos"]],
                         ["nota.wav", "dibujo.png"])
        self.assertEqual(len(self.c.quitar_adjunto(voz["id"])["adjuntos"]), 1)
        self.assertEqual(len(self.en_disco()), 2)            # el archivo sigue ahí
        self.assertTrue(self.c.adjunto(voz["id"])["ruta"].is_file())
        self.assertEqual(len(self.c.quitar_adjunto(voz["id"], False)["adjuntos"]), 2)

    def test_duracion_rara(self):
        n = self.c.crear("A")
        for valor in (None, "", "abc", "-3", "nan", "inf", "1e99"):
            with self.subTest(valor=valor):
                self.assertIsNone(self.adjuntar(n, wav(), duracion=valor)["duracion"])

    def test_si_no_se_puede_guardar_no_deja_restos(self):
        with self.assertRaises(NoEncontrada):
            self.adjuntar({"id": 99}, png())
        n = self.c.crear("A")
        with unittest.mock.patch.object(Cuaderno, "_escribir", side_effect=sqlite3.OperationalError):
            with self.assertRaises(sqlite3.OperationalError):
                self.adjuntar(n, png())
        self.assertEqual(self.en_disco(), [])


class Archivo(CasoConCuaderno):
    def test_dos_accesos_al_mismo_cuaderno(self):
        otro = Cuaderno(self.carpeta)
        n = self.c.crear("A")
        otro.editar(n["id"], texto="desde el otro")
        self.assertEqual(self.c.nota(n["id"])["texto"], "desde el otro")

    def test_no_se_crea_si_no_se_pide(self):
        with self.assertRaises(NoEncontrada):
            Cuaderno(self.dir / "nada", crear=False)
        self.assertFalse((self.dir / "nada").exists())

    def test_version_mas_nueva(self):
        with contextlib.closing(sqlite3.connect(self.carpeta / ARCHIVO_BD)) as db:
            db.execute("PRAGMA user_version = 99")
        with self.assertRaisesRegex(ErrorNotas, "más nueva"):
            Cuaderno(self.carpeta)

    def test_los_ids_no_se_reutilizan(self):
        n = self.c.crear("A")
        self.c.lote([n["id"]], "papelera")
        self.c.vaciar_papelera("VACIAR")
        self.assertGreater(self.c.crear("B")["id"], n["id"])


if __name__ == "__main__":
    unittest.main()
