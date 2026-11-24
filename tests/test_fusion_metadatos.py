"""Fusionar metadatos: la copia que se queda gana lo que saben las otras, sin recomprimir."""

import json
import os
import unittest
from datetime import datetime
from pathlib import Path

from PIL import Image

import fusionar
import galeria
from fotos import OpcionesFotos, procesar_fotos
from fusion_metadatos import Datos, aportar, escribir, gana_la_fecha, se_puede_completar
from fusionar import OpcionesFusion
from media_utils import MetadatosExtra
from metadatos import (IFD_EXIF, IFD_GPS, _segmentos_jpeg, completar_exif, completar_xmp,
                       gps_exif, jpeg_con_extra, leer_metadatos, leer_xmp)
from tests.ayudas import CasoConCarpeta
from tests.test_fusionar import copia, filas_catalogo, huella
from tests.test_similares import escena

CANON = {(0, 271): "Canon", (0, 272): "Canon EOS 5D", (IFD_EXIF, 42036): "EF 50mm f/1.8"}


def con_metadatos(ruta: Path, **extra) -> Path:
    """La misma foto (sin recomprimir) con más metadatos."""
    ruta.write_bytes(jpeg_con_extra(ruta.read_bytes(), MetadatosExtra(fuente="prueba", **extra)))
    return ruta


def imagen_jpeg(ruta: Path) -> bytes:
    """Los datos de la imagen (desde SOS): iguales = no se ha recomprimido."""
    datos = ruta.read_bytes()
    return datos[_segmentos_jpeg(datos)[1]:]


class Reglas(unittest.TestCase):
    """Metadato a metadato, el que tenga más información."""

    FECHA = datetime(2024, 5, 12, 10)

    def test_fotos(self):
        k = Datos("foto", fecha=self.FECHA, descripcion="Playa", etiquetas=["viaje"], valoracion=2,
                  exif={(IFD_EXIF, 36867): "2024:05:12 10:00:00"})
        d = Datos("foto", fecha=self.FECHA, zona="+02:00", gps=[36.5, -6.3], camara="Canon EOS 5D",
                  descripcion="Playa de Bolonia", etiquetas=["Viaje", "Cádiz"], personas=["Ana"],
                  valoracion=4, autor="Pepe",
                  exif={(IFD_EXIF, 36867): "2024:05:12 10:00:00", (IFD_EXIF, 0x9011): "+02:00",
                        (IFD_GPS, 1): "N", (IFD_GPS, 2): (36.0, 30.0, 0.0), (0, 315): "Pepe",
                        **CANON})
        extra = MetadatosExtra(fuente="fusion")
        self.assertEqual(aportar(k, d, extra),
                         ["zona horaria", "ubicación", "cámara", "autor", "descripción",
                          "1 etiqueta", "1 persona", "valoración"])
        self.assertEqual(extra.exif[(IFD_EXIF, 0x9011)], "+02:00")
        self.assertEqual(extra.exif[(IFD_GPS, 2)], (36.0, 30.0, 0.0))
        self.assertEqual(extra.exif[(0, 271)], "Canon")
        self.assertNotIn((IFD_EXIF, 36867), extra.exif)        # ya tenía fecha: no se toca
        self.assertEqual((extra.descripcion, extra.etiquetas, extra.personas, extra.valoracion),
                         ("Playa de Bolonia", ["Cádiz"], ["Ana"], 4))
        # Otra copia con lo mismo (o menos) ya no aporta nada
        self.assertEqual(aportar(k, Datos("foto", descripcion="Playa", valoracion=1,
                                          etiquetas=["cádiz"]), extra), [])
        self.assertEqual(k.describir(), ["zona horaria", "ubicación", "cámara", "autor",
                                         "descripción", "1 etiqueta", "1 persona", "valoración"])

    def test_lo_que_ya_tiene_se_queda(self):
        k = Datos("foto", fecha=self.FECHA, gps=[40.4, -3.7], camara="Nikon D750",
                  descripcion="Cumpleaños de la abuela", titulo="Cumple", valoracion=5,
                  exif={(0, 271): "Nikon", (0, 272): "Nikon D750"})
        d = Datos("foto", fecha=datetime(2024, 5, 12, 11), gps=[36.5, -6.3], camara="Canon EOS 5D",
                  descripcion="Cumple", titulo="Cumpleaños", valoracion=3,
                  exif={(IFD_EXIF, 36867): "2024:05:12 11:00:00", (IFD_GPS, 1): "N", **CANON})
        extra = MetadatosExtra(fuente="fusion")
        self.assertEqual(aportar(k, d, extra), ["título"])   # otra cámara: sus datos no
        self.assertEqual(extra.exif, {})
        self.assertEqual(extra.titulo, "Cumpleaños")

    def test_misma_camara_completa_los_datos_de_la_toma(self):
        k = Datos("foto", camara="Canon EOS 5D", exif={(0, 271): "Canon", (0, 272): "Canon EOS 5D"})
        d = Datos("foto", camara="Canon EOS 5D", exif=dict(CANON))
        extra = MetadatosExtra(fuente="fusion")
        self.assertEqual(aportar(k, d, extra), ["datos de la cámara"])
        self.assertEqual(extra.exif, {(IFD_EXIF, 42036): "EF 50mm f/1.8"})

    def test_sin_fecha_gana_la_de_la_otra(self):
        k = Datos("foto")
        d = Datos("foto", fecha=self.FECHA, exif={(IFD_EXIF, 36867): "2024:05:12 10:00:00",
                                                  (IFD_EXIF, 0x9011): "+02:00"})
        extra = MetadatosExtra(fuente="fusion")
        self.assertEqual(aportar(k, d, extra), ["fecha"])
        self.assertEqual(set(extra.exif), {(IFD_EXIF, 36867), (IFD_EXIF, 0x9011)})

    def test_cuando_gana_la_fecha_de_la_otra(self):
        d = Datos("foto", fecha=datetime(2014, 2, 3, 22, 7, 20))

        def k(fecha, fuente):
            return Datos("foto", fecha_actual=fecha, fuente_actual=fuente)
        self.assertTrue(gana_la_fecha(k(datetime(2026, 11, 22, 0, 4, 30), "archivo"), d))
        self.assertTrue(gana_la_fecha(k(datetime(2014, 2, 3), "nombre"), d))        # gana la hora
        self.assertTrue(gana_la_fecha(k(datetime(2014, 2, 3, 20), "nombre+hora_archivo"), d))
        self.assertFalse(gana_la_fecha(k(datetime(2014, 2, 4), "nombre"), d))       # otro día
        self.assertFalse(gana_la_fecha(k(datetime(2014, 2, 3, 20, 7, 20), "nombre"), d))  # fiable
        self.assertFalse(gana_la_fecha(Datos("foto", fecha=datetime(2014, 1, 1)), d))     # la trae

    def test_videos(self):
        k = Datos("video", etiquetas=["Viaje"])
        d = Datos("video", fecha=self.FECHA, gps=[40.4168, -3.7038], descripcion="En la playa",
                  etiquetas=["viaje", "Ana"])
        extra = MetadatosExtra(fuente="fusion")
        self.assertEqual(aportar(k, d, extra), ["fecha", "ubicación", "descripción", "1 etiqueta"])
        # Las palabras clave de un vídeo se escriben enteras: van también las suyas
        self.assertEqual((extra.fecha, extra.gps, extra.etiquetas),
                         (self.FECHA, (40.4168, -3.7038), ["Viaje", "Ana"]))

    def test_que_formatos_se_pueden_completar_sin_recomprimir(self):
        self.assertTrue(se_puede_completar(Path("a.JPG"), "foto"))
        self.assertFalse(se_puede_completar(Path("a.png"), "foto"))
        self.assertTrue(se_puede_completar(Path("a.png"), "foto", convertir=True))
        self.assertTrue(se_puede_completar(Path("a.mov"), "video"))
        self.assertFalse(se_puede_completar(Path("a.webm"), "video"))


class Escritura(CasoConCarpeta):
    def test_exif_de_otra_copia_solo_lo_que_falta(self):
        exif = Image.Exif()
        exif[271] = "Nikon"
        extra = MetadatosExtra(fuente="fusion", exif={
            (0, 271): "Canon", (0, 272): "Canon EOS 5D", (IFD_GPS, 1): "N",
            (IFD_GPS, 2): (40.0, 25.0, 0.0), (IFD_GPS, 3): "W", (IFD_GPS, 4): (3.0, 42.0, 0.0)})
        self.assertTrue(completar_exif(exif, extra))
        self.assertEqual((exif[271], exif[272]), ("Nikon", "Canon EOS 5D"))
        self.assertEqual(gps_exif(exif), [40.416667, -3.7])
        # Si ya tiene ubicación, la suya se queda entera
        otra = MetadatosExtra(fuente="fusion", exif={(IFD_GPS, 2): (1.0, 0.0, 0.0)})
        self.assertFalse(completar_exif(exif, otra))
        self.assertEqual(gps_exif(exif), [40.416667, -3.7])

    def test_xmp_titulo_y_valoracion(self):
        xmp = completar_xmp(None, MetadatosExtra(fuente="f", titulo="Cumple", valoracion=3))
        self.assertEqual((leer_xmp(xmp)["titulo"], leer_xmp(xmp)["valoracion"]), ("Cumple", 3))
        xmp = completar_xmp(xmp, MetadatosExtra(fuente="f", titulo="Cumpleaños", valoracion=5))
        self.assertEqual((leer_xmp(xmp)["titulo"], leer_xmp(xmp)["valoracion"]), ("Cumpleaños", 5))
        # Nunca baja; la favorita de Google no pisa una valoración que ya tenga
        xmp = completar_xmp(xmp, MetadatosExtra(fuente="f", valoracion=2, favorita=True,
                                                etiquetas=["x"]))
        self.assertEqual(leer_xmp(xmp)["valoracion"], 5)

    def test_escribir_en_su_sitio_sin_recomprimir(self):
        foto = escena(self.dir / "a.jpg", 1, fecha="2024:05:12 10:00:00")
        os.utime(foto, (1_600_000_000, 1_600_000_000))
        imagen = imagen_jpeg(foto)
        extra = MetadatosExtra(fuente="fusion", etiquetas=["Viaje"], exif={
            (IFD_GPS, 1): "N", (IFD_GPS, 2): (40.0, 25.0, 0.0), (IFD_GPS, 3): "W",
            (IFD_GPS, 4): (3.0, 42.0, 0.0)})
        self.assertTrue(escribir(foto, foto, "foto", extra))
        self.assertEqual(imagen_jpeg(foto), imagen)
        self.assertEqual(foto.stat().st_mtime, 1_600_000_000)
        datos = leer_metadatos(foto)
        self.assertEqual((datos["etiquetas"], datos["gps"]), (["Viaje"], [40.416667, -3.7]))
        self.assertFalse(escribir(foto, foto, "foto", extra))   # ya lo tiene todo
        self.assertEqual(list(self.dir.glob("*.part")), [])


class Fusion(CasoConCarpeta):
    """Una biblioteca y otra colección (p. ej. Google Fotos) con dos fotos repetidas:
    - a: la de la biblioteca es mejor; la de la colección trae ubicación, álbumes,
      persona, descripción y favorita -> la de la biblioteca los gana, sin recomprimir.
    - b: la de la colección es mejor (y entra tal cual); la de la biblioteca tiene
      ubicación, descripción y una etiqueta -> la nueva los gana."""

    def setUp(self):
        super().setUp()
        movil, self.bib, self.col = self.dir / "movil", self.dir / "bib", self.dir / "google"
        a = con_metadatos(escena(movil / "a.jpg", 1, fecha="2024:05:12 10:00:00"), exif=CANON)
        self.b_grande = con_metadatos(escena(self.col / "b_grande.jpg", 2, tam=(1600, 1200),
                                             fecha="2024:05:12 11:00:00"), etiquetas=["Google"])
        con_metadatos(copia(self.b_grande, movil / "b.jpg", (800, 600)), gps=(40.4168, -3.7038, 650.0),
                      descripcion="Cumpleaños de la abuela", etiquetas=["Familia"])
        procesar_fotos(movil, self.bib, False, OpcionesFotos(hilos=2))
        galeria.generar_galeria(self.bib)
        con_metadatos(copia(a, self.col / "copia_a.jpg", (800, 600)), gps=(36.5271, -6.2886, None),
                      etiquetas=["Viaje", "Playa"], personas=["Ana"],
                      descripcion="Atardecer en Cádiz", favorita=True)
        self.src_a = "2024/05-Mayo/20240512_100000.jpg"
        self.src_b = "2024/05-Mayo/20240512_110000.jpg"
        self.huella_col = huella(self.col)

    def tearDown(self):
        self.assertEqual(huella(self.col), self.huella_col)   # la colección nunca se toca
        super().tearDown()

    def fusionar(self, simular=False, **opciones):
        return fusionar.fusionar(self.col, self.bib, simular, OpcionesFusion(hilos=2, **opciones))

    def test_la_que_se_queda_gana_los_metadatos(self):
        a = self.bib / self.src_a
        imagen_a, mtime_a = imagen_jpeg(a), a.stat().st_mtime_ns
        stats = self.fusionar()
        self.assertEqual((stats["ya_estaban"], stats["sustituidas"], stats["metadatos"],
                          stats["errores"]), (1, 1, 2, 0))
        # a: la de la biblioteca, sin recomprimir y con la misma fecha de archivo
        self.assertEqual((imagen_jpeg(a), a.stat().st_mtime_ns), (imagen_a, mtime_a))
        datos = leer_metadatos(a)
        self.assertEqual(datos["gps"], [36.5271, -6.2886])
        self.assertEqual(set(datos["etiquetas"]), {"Viaje", "Playa"})
        self.assertEqual((datos["personas"], datos["descripcion"], datos["valoracion"]),
                         (["Ana"], "Atardecer en Cádiz", 5))
        self.assertEqual(datos["camara"], "Canon EOS 5D")                  # lo suyo sigue
        # b: la nueva (la de la colección, tal cual) con lo que sabía la sustituida
        b = self.bib / self.src_b
        self.assertEqual(imagen_jpeg(b), imagen_jpeg(self.b_grande))
        datos = leer_metadatos(b)
        self.assertEqual((datos["ancho"], datos["gps"], datos["descripcion"]),
                         (1600, [40.4168, -3.7038], "Cumpleaños de la abuela"))
        self.assertEqual(set(datos["etiquetas"]), {"Google", "Familia"})
        # La galería ya lo muestra; el informe lo cuenta
        elementos = {e["src"]: e for e in json.loads(
            (self.bib / "galeria.json").read_text(encoding="utf-8"))["elementos"]}
        self.assertIn("Viaje", elementos[self.src_a].get("etiquetas", []))
        self.assertTrue(elementos[self.src_a].get("gps"))
        salida = self.consola.getvalue()
        self.assertIn(f"METADATOS  {self.src_a}", salida)
        self.assertIn("ubicación, descripción, 2 etiquetas, 1 persona, valoración", salida)
        informe = sorted((self.bib / ".exportador" / "informes").glob("*fusion*.csv"))[-1]
        texto = informe.read_text(encoding="utf-8-sig")
        self.assertIn("METADATOS", texto)
        self.assertIn("sus metadatos completan la que se queda", texto)
        self.assertIn("con los metadatos de las otras copias: ubicación", texto)

    def test_simular_lo_cuenta_sin_tocar_nada(self):
        antes = huella(self.bib)
        stats = self.fusionar(simular=True)
        self.assertEqual(huella(self.bib), antes)
        self.assertEqual(stats["metadatos"], 2)
        self.assertIn(f"METADATOS  {self.src_a}", self.consola.getvalue())
        Path(stats["informe"]).unlink()

    def test_sin_metadatos(self):
        a = self.bib / self.src_a
        contenido = a.read_bytes()
        stats = self.fusionar(metadatos=False)
        self.assertEqual((stats["metadatos"], stats["sustituidas"]), (0, 1))
        self.assertEqual(a.read_bytes(), contenido)
        self.assertEqual((self.bib / self.src_b).read_bytes(), self.b_grande.read_bytes())

    def test_segunda_vez_no_cambia_nada(self):
        self.fusionar()
        antes = huella(self.bib)
        stats = self.fusionar()
        self.assertEqual((stats["metadatos"], stats["anadidas"], stats["sustituidas"]), (0, 0, 0))

        def sin_catalogo(h):
            return {k: v for k, v in h.items() if not k.startswith(".exportador/")}
        self.assertEqual(sin_catalogo(huella(self.bib)), sin_catalogo(antes))

    def test_sin_fecha_gana_la_de_la_otra_tambien_en_el_catalogo(self):
        # El mismo original importado en las dos, sin fecha EXIF (la del archivo, 2026);
        # en la de Google lleva la del JSON (2014): la de la biblioteca la gana
        movil, bib, google = self.dir / "movil3", self.dir / "bib3", self.dir / "google3"
        foto = escena(movil / "IMG_0001.jpg", 4)
        os.utime(foto, (datetime(2026, 11, 22, 0, 4, 30).timestamp(),) * 2)
        procesar_fotos(movil, bib, False, OpcionesFotos(hilos=2))
        procesar_fotos(movil, google, False, OpcionesFotos(hilos=2))
        rel = "2026/11-Noviembre/20261122_000430.jpg"
        con_metadatos(google / rel, exif={(IFD_EXIF, 36867): "2014:08:13 12:10:27"})
        self.assertEqual(filas_catalogo(bib)[0]["fuente_fecha"], "archivo")
        stats = fusionar.fusionar(google, bib, False, OpcionesFusion(hilos=2))
        self.assertEqual((stats["ya_estaban"], stats["metadatos"]), (1, 1))
        self.assertEqual(leer_metadatos(bib / rel)["fecha"], datetime(2014, 8, 13, 12, 10, 27))
        fila = filas_catalogo(bib)[0]
        self.assertEqual((fila["destino"], fila["fecha"], fila["fuente_fecha"]),
                         (rel, "2014-08-13T12:10:27", "exif"))
        self.assertIn("; fecha 2014-08-13 12:10:27, sigue en su carpeta", self.consola.getvalue())

    def test_formato_que_no_se_puede_completar(self):
        # Una mejor en PNG entra tal cual: no se le pueden añadir metadatos sin recomprimirla
        png = escena(self.col / "c.png", 3, tam=(1600, 1200), fecha="2024:05:12 12:00:00")
        movil = self.dir / "movil2"
        con_metadatos(copia(png, movil / "c.jpg", (800, 600)), gps=(40.4168, -3.7038, None))
        procesar_fotos(movil, self.bib, False, OpcionesFotos(hilos=2))
        self.huella_col = huella(self.col)
        stats = self.fusionar(simular=True)
        self.assertEqual((stats["sustituidas"], stats["metadatos"], stats["metadatos_sin_poder"]),
                         (2, 2, 1))
        informe = Path(stats["informe"])
        self.assertIn("a un PNG no se le pueden añadir sin recomprimirlo",
                      informe.read_text(encoding="utf-8-sig"))
        informe.unlink()

if __name__ == "__main__":
    unittest.main()
