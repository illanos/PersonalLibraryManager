"""Mejora 4: informe de archivos dañados."""

import csv
import unittest
from unittest import mock

import fotos
import videos
from danados import SIN_CABECERA, TRUNCADO, VACIO, diagnosticar
from fotos import OpcionesFotos, procesar_fotos
from tests.ayudas import CasoConCarpeta, crear_foto


class Diagnostico(CasoConCarpeta):
    def test_casos(self):
        buena = crear_foto(self.dir / "buena.jpg", tam=(800, 600))
        datos = buena.read_bytes()
        casos = {
            "vacia.jpg": b"",
            "ceros.jpg": b"\x00" * 4096,
            "texto.jpg": b"<html>no es una foto</html>",
            "truncada.jpg": datos[: len(datos) // 2],
            "con_cola.jpg": datos + b"SEFT" * 5000,     # datos tras el final: válida
        }
        for nombre, contenido in casos.items():
            (self.dir / nombre).write_bytes(contenido)

        def diag(nombre):
            ruta = self.dir / nombre
            resultado = diagnosticar(ruta, ruta.stat().st_size, imagen=True)
            return resultado[0] if resultado else None
        self.assertEqual(diag("vacia.jpg"), VACIO)
        self.assertEqual(diag("ceros.jpg"), VACIO)
        self.assertEqual(diag("texto.jpg"), SIN_CABECERA)
        self.assertEqual(diag("truncada.jpg"), TRUNCADO)
        self.assertIsNone(diag("con_cola.jpg"))
        self.assertIsNone(diag("buena.jpg"))


class Importacion(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.origen, self.bib = self.dir / "movil", self.dir / "bib"
        misc = self.origen / "2017" / "misc"
        buena = crear_foto(misc / "buena.jpg", tam=(800, 600))
        (misc / "vacia1.jpg").write_bytes(b"")
        (misc / "vacia2.jpg").write_bytes(b"")
        (misc / "truncada.jpg").write_bytes(buena.read_bytes()[:3000])
        crear_foto(self.origen / "otra" / "bien.jpg", color=(0, 0, 255), fecha="2020:01:01 10:00:00")

    def csv_danados(self):
        rutas = sorted((self.bib / ".exportador" / "informes").glob("danados_fotos_*.csv"))
        with open(rutas[-1], encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))

    def test_informe_aparte_resumen_y_origen_intacto(self):
        antes = {p: p.read_bytes() for p in self.origen.rglob("*") if p.is_file()}
        stats = procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=2))
        self.assertEqual((stats["procesados"], stats["danados"], stats["errores"]), (2, 3, 0))
        filas = self.csv_danados()
        self.assertEqual(sorted(f["problema"] for f in filas), [TRUNCADO, VACIO, VACIO])
        self.assertEqual({f["carpeta"] for f in filas}, {"2017/misc"})
        salida = self.consola.getvalue()
        self.assertIn("ARCHIVOS DAÑADOS (3)", salida)
        self.assertRegex(salida, r"2017/misc\s+3\s+\(2 vacío, 1 truncado\)")
        self.assertEqual({p: p.read_bytes() for p in self.origen.rglob("*") if p.is_file()}, antes)

    def test_segunda_ejecucion_no_los_vuelve_a_leer(self):
        procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=2))
        with mock.patch.object(fotos, "diagnosticar", side_effect=AssertionError("relee")), \
                mock.patch.object(fotos, "hash_archivo", side_effect=AssertionError("relee")):
            stats = procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=2))
        self.assertEqual((stats["procesados"], stats["ya_importados"], stats["danados"]), (0, 2, 3))
        self.assertTrue(all(f["ya_conocido"] == "sí" for f in self.csv_danados()))

    def test_simulacion_resume_sin_escribir(self):
        procesar_fotos(self.origen, self.bib, True)
        self.assertFalse(self.bib.exists())
        self.assertIn("ARCHIVOS DAÑADOS (3)", self.consola.getvalue())


class Videos(CasoConCarpeta):
    def test_video_vacio_o_cortado(self):
        origen, bib = self.dir / "v", self.dir / "bib"
        origen.mkdir()
        (origen / "vacio.mp4").write_bytes(b"")
        (origen / "cortado.mp4").write_bytes(b"\x00\x00\x00\x14ftypisom" + b"x" * 100)
        with mock.patch("videos.sondear", return_value=None), \
                mock.patch("videos.ejecutar_ffmpeg", return_value=(False, "moov atom not found")):
            stats = videos.procesar_videos(origen, bib, False)
        self.assertEqual((stats["danados"], stats["errores"]), (2, 0))
        self.assertTrue(list((bib / ".exportador" / "informes").glob("danados_videos_*.csv")))


if __name__ == "__main__":
    unittest.main()
