"""Mejora 8: lugares (sin conexión) y caras (agrupación incremental, nombres)."""

import http.client
import io
import json
import threading
import unittest
import zipfile
from unittest import mock

from PIL import Image

from exportador import caras
from exportador import galeria
from exportador import lugares
from exportador.fotos import OpcionesFotos, procesar_fotos
from exportador.servidor import crear_servidor
from tests.ayudas import CasoConCarpeta, crear_foto

# Formato de GeoNames (cities15000.txt): 19 columnas separadas por tabuladores
def _ciudad(nombre, lat, lon, pais, admin1):
    c = [""] * 19
    c[1], c[4], c[5], c[8], c[10] = nombre, str(lat), str(lon), pais, admin1
    return "\t".join(c)


def geonames_falso() -> tuple:
    texto = "\n".join([
        _ciudad("Chiclana de la Frontera", 36.4192, -6.1491, "ES", "51"),
        _ciudad("Cádiz", 36.5271, -6.2886, "ES", "51"),
        _ciudad("San Francisco", 37.7749, -122.4194, "US", "CA"),
    ]) + "\n"
    zbytes = io.BytesIO()
    with zipfile.ZipFile(zbytes, "w") as z:
        z.writestr("cities15000.txt", texto)
    admin1 = "ES.51\tAndalusia\tAndalusia\t1\nUS.CA\tCalifornia\tCalifornia\t2\n"
    paises = "#ISO\tISO3\tnum\tfips\tCountry\nES\tESP\t724\tSP\tSpain\nUS\tUSA\t840\tUS\tUnited States\n"
    return zbytes.getvalue(), admin1, paises


class Lugares(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.ruta = self.dir / "lugares.tsv"
        lugares.guardar(lugares.preparar(*geonames_falso()), self.ruta)
        self.geo = lugares.Geocodificador(self.ruta)

    def test_ciudad_mas_cercana(self):
        self.assertEqual(self.geo.buscar(36.53, -6.29),
                         {"ciudad": "Cádiz", "region": "Andalusia", "pais": "España"})
        self.assertEqual(self.geo.buscar(37.80, -122.40)["pais"], "Estados Unidos")
        self.assertIsNone(self.geo.buscar(0.5, 0.5))   # en mitad del mar

    def test_en_la_galeria_y_sin_recalcular(self):
        origen, bib = self.dir / "movil", self.dir / "bib"
        crear_foto(origen / "IMG_1.jpg", completa=True)   # GPS cerca de Cádiz
        procesar_fotos(origen, bib, False, OpcionesFotos(hilos=1))
        with mock.patch.object(lugares, "cargar", return_value=self.geo):
            galeria.generar_galeria(bib)
            datos = json.loads((bib / "galeria.json").read_text(encoding="utf-8"))
            self.assertEqual((datos["elementos"][0]["lugar"], datos["elementos"][0]["pais"]),
                             ("Cádiz", "España"))
            with mock.patch.object(self.geo, "buscar", side_effect=AssertionError("recalcula")):
                galeria.generar_galeria(bib)

    def test_sin_datos_avisa(self):
        origen, bib = self.dir / "movil", self.dir / "bib"
        crear_foto(origen / "IMG_1.jpg", completa=True)
        procesar_fotos(origen, bib, False, OpcionesFotos(hilos=1))
        with mock.patch.object(lugares, "cargar", return_value=None):
            galeria.generar_galeria(bib)
        self.assertIn("--descargar-lugares", self.consola.getvalue())

    def test_ya_descargados_no_se_descargan_otra_vez(self):
        with mock.patch.object(lugares, "ARCHIVO", self.ruta), \
                mock.patch.object(lugares, "descargar", side_effect=AssertionError("descarga")):
            lugares.descargar_lugares()
        self.assertIn("ya descargados", self.consola.getvalue())

    def test_sin_conexion_la_galeria_se_genera_igual(self):
        import urllib.error
        from exportador.cli import main
        crear_foto(self.dir / "bib" / "2023" / "IMG_1.jpg")
        sin_red = urllib.error.URLError("sin conexión")
        with mock.patch("exportador.lugares.descargar_lugares", side_effect=sin_red), \
                mock.patch("exportador.caras.descargar_modelos", side_effect=sin_red):
            main(["galeria", str(self.dir / "bib"), "--descargar-lugares",
                  "--descargar-modelos-caras"])
        self.assertTrue((self.dir / "bib" / "galeria.html").exists())
        self.assertEqual(self.consola.getvalue().count("AVISO: no se han podido descargar"), 2)


class MotorFalso(caras.Motor):
    """Una 'cara' por foto; su vector es el color dominante (misma persona = mismo color)."""
    nombre = "sface"

    def __init__(self):
        self.llamadas = 0

    def caras(self, ruta):
        self.llamadas += 1
        with Image.open(ruta) as im:
            r, g, b = im.convert("RGB").resize((1, 1)).getpixel((0, 0))
        return [(0.25, 0.2, 0.3, 0.4, [r, g, b])]


class Caras(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.origen, self.bib = self.dir / "movil", self.dir / "bib"
        rojo, azul = (220, 20, 20), (20, 20, 220)
        crear_foto(self.origen / "a.jpg", color=rojo, fecha="2024:01:01 10:00:00")
        crear_foto(self.origen / "b.jpg", color=rojo, fecha="2024:01:02 10:00:00")
        crear_foto(self.origen / "c.jpg", color=azul, fecha="2024:01:03 10:00:00")
        procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=1))
        self.motor = MotorFalso()

    def generar(self):
        with mock.patch.object(caras, "MotorOpenCV", return_value=self.motor), \
                mock.patch.object(caras, "disponible", return_value=True):
            self.motor.con_modelos = True
            galeria.generar_galeria(self.bib, caras=True)
        return {e["src"]: e for e in json.loads(
            (self.bib / "galeria.json").read_text(encoding="utf-8"))["elementos"]}

    def test_agrupa_y_no_reanaliza(self):
        por = self.generar()
        grupo = {src: e["caras"][0][0] for src, e in por.items()}
        a, b, c = (grupo[f"2024/01-Enero/2024010{i}_100000.jpg"] for i in (1, 2, 3))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(self.motor.llamadas, 3)
        crear_foto(self.origen / "d.jpg", color=(200, 30, 30), fecha="2024:01:04 10:00:00")
        procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=1))
        por = self.generar()
        self.assertEqual(self.motor.llamadas, 4)   # solo la nueva
        self.assertEqual(por["2024/01-Enero/20240104_100000.jpg"]["caras"][0][0], a)

    def test_sin_opencv_se_omite_con_aviso(self):
        with mock.patch.object(caras, "disponible", return_value=False):
            galeria.generar_galeria(self.bib, caras=True)
        self.assertIn("pip install opencv-python", self.consola.getvalue())

    def test_nombres_por_el_servidor(self):
        self.generar()
        servidor = crear_servidor(self.bib, puerto=0, intentos=1)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            def pedir(metodo, cuerpo=None):
                con = http.client.HTTPConnection("127.0.0.1", servidor.server_address[1], timeout=5)
                con.request(metodo, "/api/caras", body=cuerpo,
                            headers={"Content-Type": "application/json"})
                r = con.getresponse()
                datos = r.read()
                con.close()
                return r.status, datos
            self.assertEqual(pedir("POST", json.dumps({"grupo": "1", "nombre": " Ana "})),
                             (200, b'{"1": "Ana"}'))
            self.assertEqual(json.loads(pedir("GET")[1]), {"1": "Ana"})
            self.assertEqual(pedir("POST", json.dumps({"grupo": "x", "nombre": "A"}))[0], 400)
            pedir("POST", json.dumps({"grupo": "1", "nombre": ""}))
            self.assertEqual(json.loads(pedir("GET")[1]), {})
        finally:
            servidor.shutdown()
            servidor.server_close()
        # El nombre se incluye también en galeria.json para verla sin servidor
        (self.bib / "_galeria" / "personas.json").write_text('{"1": "Ana"}', encoding="utf-8")
        galeria.generar_galeria(self.bib)
        datos = json.loads((self.bib / "galeria.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["nombres_caras"], {"1": "Ana"})


if __name__ == "__main__":
    unittest.main()
