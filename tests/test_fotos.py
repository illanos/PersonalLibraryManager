import os
import unittest
from datetime import datetime

from PIL import Image, IptcImagePlugin

from fotos import OpcionesFotos, guardar_optimizada, procesar_fotos
from metadatos import leer_metadatos
from tests.ayudas import CasoConCarpeta, crear_foto


class Metadatos(CasoConCarpeta):
    def test_lee_datetimeoriginal_del_sub_ifd(self):
        # Error anterior: se buscaba en el IFD principal y se acababa usando DateTime
        ruta = crear_foto(self.dir / "a.jpg", fecha="2015:06:07 08:09:10")
        with Image.open(ruta) as im:
            exif = im.getexif()
        exif[306] = "2020:01:01 00:00:00"   # fecha de edición, distinta
        with Image.open(ruta) as im:
            im.save(ruta, exif=exif)
        datos = leer_metadatos(ruta)
        self.assertEqual((datos["fecha"], datos["fuente"]), (datetime(2015, 6, 7, 8, 9, 10), "exif"))

    def test_extrae_etiquetas_personas_y_demas(self):
        datos = leer_metadatos(crear_foto(self.dir / "a.jpg", completa=True))
        self.assertEqual(datos["etiquetas"],
                         ["playa", "vacaciones", "Cadiz", "verano", "familia", "cumple"])
        self.assertEqual(datos["personas"], ["Ana"])
        self.assertEqual((datos["titulo"], datos["valoracion"]), ("Atardecer", 4))
        self.assertEqual(datos["camara"], "Apple iPhone 13")
        self.assertIn("front", datos["objetivo"])
        self.assertAlmostEqual(datos["gps"][0], 36.53, places=2)
        self.assertLess(datos["gps"][1], 0)

    def test_titulo_xmp_prefiere_x_default(self):
        from metadatos import leer_xmp
        xmp = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
               'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
               '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title><rdf:Alt>'
               '<rdf:li xml:lang="en">Sunset</rdf:li><rdf:li xml:lang="x-default">Atardecer</rdf:li>'
               '</rdf:Alt></dc:title></rdf:Description></rdf:RDF></x:xmpmeta>')
        self.assertEqual(leer_xmp(xmp)["titulo"], "Atardecer")

    def test_xmp_con_entidades_se_ignora(self):
        from metadatos import leer_xmp
        self.assertEqual(leer_xmp('<!DOCTYPE x [<!ENTITY a "aaaa">]><x/>')["etiquetas"], [])

    def test_sin_exif_usa_el_nombre(self):
        ruta = crear_foto(self.dir / "IMG-20240512-WA0001.jpg", fecha=None)
        datos = leer_metadatos(ruta)
        self.assertEqual((datos["fecha"], datos["fuente"]), (datetime(2024, 5, 12), "nombre"))


class Exportacion(CasoConCarpeta):
    def test_conserva_todos_los_metadatos_y_aplica_orientacion(self):
        origen = crear_foto(self.dir / "a.jpg", tam=(4000, 3000), orientacion=6, completa=True)
        destino = self.dir / "b.jpg"
        self.assertEqual(guardar_optimizada(origen, destino), [])
        with Image.open(destino) as im:
            self.assertEqual(im.size, (1920, 2560))          # girada y reducida
            exif = im.getexif()
            self.assertIn(exif.get(274), (None, 1))          # sin doble giro
            self.assertEqual(exif.get_ifd(0x8769)[36867], "2023:08:15 20:31:07")
            self.assertTrue(exif.get_ifd(0x8825))            # GPS
            self.assertTrue(im.info.get("icc_profile"))
            self.assertEqual(im.info.get("comment"), b"comentario")
            self.assertIn(b'tiff:Orientation="1"', im.info["xmp"])
            self.assertEqual(IptcImagePlugin.getiptcinfo(im)[(2, 25)], [b"Cadiz", b"verano"])
        datos = leer_metadatos(destino)
        self.assertEqual(datos["etiquetas"],
                         ["playa", "vacaciones", "Cadiz", "verano", "familia", "cumple"])
        self.assertEqual((datos["personas"], datos["valoracion"]), (["Ana"], 4))

    def test_webp_avisa_de_que_no_admite_iptc(self):
        origen = crear_foto(self.dir / "a.jpg", completa=True)
        avisos = guardar_optimizada(origen, self.dir / "b.webp", OpcionesFotos(formato="webp"))
        self.assertTrue(any("IPTC" in a for a in avisos))
        self.assertEqual(leer_metadatos(self.dir / "b.webp")["etiquetas"][:2],
                         ["playa", "vacaciones"])


class Procesamiento(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.origen = self.dir / "movil"
        self.destino = self.dir / "biblioteca"
        crear_foto(self.origen / "IMG_0001.jpg", tam=(3000, 2000), completa=True)
        crear_foto(self.origen / "sub" / "copia.jpg", tam=(3000, 2000), completa=True)
        crear_foto(self.origen / "IMG_0002.jpg", fecha="2024:01:02 03:04:05", color=(10, 90, 200))

    def procesar(self, **opciones):
        return procesar_fotos(self.origen, self.destino, False, OpcionesFotos(hilos=2, **opciones))

    def test_simular_no_toca_nada(self):
        antes = self.archivos(self.dir)
        stats = procesar_fotos(self.origen, self.destino, True)
        self.assertEqual(stats["procesados"], 2)
        self.assertEqual(self.archivos(self.dir), antes)
        self.assertFalse(self.destino.exists())

    def test_organiza_y_no_borra_duplicados_del_origen(self):
        stats = self.procesar()
        self.assertEqual((stats["procesados"], stats["duplicados"]), (2, 1))
        self.assertTrue((self.origen / "sub" / "copia.jpg").exists())
        archivos = self.archivos(self.destino)
        self.assertIn("2023/08-Agosto/20230815_203107.jpg", archivos)
        self.assertIn("2024/01-Enero/20240102_030405.jpg", archivos)
        self.assertFalse(any(a.startswith("originales/") for a in archivos))
        self.assertTrue(any(a.startswith(".exportador/informes/fotos_") for a in archivos))
        final = self.destino / "2023/08-Agosto/20230815_203107.jpg"
        self.assertEqual(datetime.fromtimestamp(final.stat().st_mtime),
                         datetime(2023, 8, 15, 20, 31, 7))   # fecha de archivo = captura

    def test_segunda_ejecucion_es_incremental(self):
        self.procesar()
        antes = self.archivos(self.destino)
        crear_foto(self.origen / "nueva.jpg", fecha="2025:02:03 04:05:06", color=(0, 200, 0))
        stats = self.procesar()
        self.assertEqual((stats["procesados"], stats["ya_importados"]), (1, 3))
        nuevos = set(self.archivos(self.destino)) - set(antes)
        self.assertIn("2025/02-Febrero/20250203_040506.jpg", nuevos)

    def test_si_se_borra_de_la_biblioteca_se_vuelve_a_importar(self):
        self.procesar()
        (self.destino / "2024/01-Enero/20240102_030405.jpg").unlink()
        stats = self.procesar()
        self.assertEqual(stats["procesados"], 1)
        self.assertTrue((self.destino / "2024/01-Enero/20240102_030405.jpg").exists())

    def test_origen_queda_intacto(self):
        antes = {r: (r.stat().st_size, r.stat().st_mtime_ns, r.read_bytes())
                 for r in self.origen.rglob("*") if r.is_file()}
        self.procesar()
        despues = {r: (r.stat().st_size, r.stat().st_mtime_ns, r.read_bytes())
                   for r in self.origen.rglob("*") if r.is_file()}
        self.assertEqual(despues, antes)

    def test_con_originales_guarda_copia(self):
        self.procesar(conservar_originales=True)
        self.assertIn("originales/2023/08-Agosto/IMG_0001.jpg", self.archivos(self.destino))
        self.assertTrue((self.origen / "IMG_0001.jpg").exists())

    def test_gif_animado_se_copia_tal_cual(self):
        fotogramas = [Image.new("RGB", (64, 64), c) for c in ((255, 0, 0), (0, 0, 255))]
        fotogramas[0].save(self.origen / "IMG_20240301_101010.gif", save_all=True,
                           append_images=fotogramas[1:], duration=200)
        self.procesar()
        gif = self.destino / "2024/03-Marzo/20240301_101010.gif"
        with Image.open(gif) as im:
            self.assertTrue(im.is_animated)

    def test_si_recomprimir_no_compensa_conserva_el_original(self):
        # Ruido guardado con calidad 20: recomprimir a calidad 88 solo engordaría
        pequena = self.origen / "IMG_20240401_101010.jpg"
        Image.effect_noise((300, 200), 80).convert("RGB").save(pequena, quality=20)
        stats = self.procesar()
        self.assertGreaterEqual(stats["sin_cambios"], 1)
        final = self.destino / "2024/04-Abril/20240401_101010.jpg"
        self.assertEqual(final.read_bytes(), pequena.read_bytes())

    def test_no_quedan_temporales(self):
        self.procesar()
        self.assertFalse([a for a in self.archivos(self.destino) if a.endswith(".part")])


if __name__ == "__main__":
    unittest.main()
