"""Google Takeout: emparejado de JSON, álbumes, fechas y metadatos grabados al exportar."""

import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from PIL import Image

import videos
from fotos import OpcionesFotos, guardar_optimizada, procesar_fotos
from media_utils import MetadatosExtra, elegir_fecha, metadatos_para_escribir
from metadatos import completar_xmp, jpeg_con_extra, leer_metadatos, leer_xmp
from takeout import IndiceTakeout, nombre_album
from tests.ayudas import XMP_PRUEBA, CasoConCarpeta, crear_foto


def marca(fecha: datetime) -> str:
    """Timestamp UTC de una hora local, como lo guarda Google."""
    return str(int(fecha.timestamp()))


def json_google(ruta: Path, titulo: str, fecha: datetime = None, gps=None, personas=(),
                descripcion="", **otros):
    datos = {"title": titulo, "description": descripcion, "imageViews": "3",
             "creationTime": {"timestamp": marca(datetime(2025, 1, 1)), "formatted": ""},
             "photoTakenTime": {"timestamp": marca(fecha) if fecha else "0", "formatted": ""},
             "geoData": {"latitude": gps[0] if gps else 0.0,
                         "longitude": gps[1] if gps else 0.0, "altitude": 0.0},
             "url": "https://photos.google.com/photo/x"}
    if personas:
        datos["people"] = [{"name": p} for p in personas]
    datos.update(otros)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return ruta


def album(carpeta: Path, titulo: str):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "metadatos.json").write_text(
        json.dumps({"title": titulo, "description": "", "access": "private",
                    "date": {"timestamp": "1365372083"}}), encoding="utf-8")


SUFIJO = ".supplemental-metadata.json"


class Emparejado(CasoConCarpeta):
    def test_nombres_que_usa_google(self):
        c = self.dir / "Fotos del 2019"
        casos = {
            "a.jpg": "a.jpg" + SUFIJO,
            "b(1).jpg": "b.jpg.supplemental-metadata(1).json",
            "07_04_13 - 1.jpg": "07_04_13 - 1" + SUFIJO,       # título sin extensión
            "viejo.jpg": "viejo.jpg.json",                     # Takeout antiguo
            "PXL_1.MP": "PXL_1.MP.jpg" + SUFIJO,               # clip de foto con movimiento
            "una_foto_con_un_nombre_bastante_largo_2019.jpg":
                "una_foto_con_un_nombre_bastante_largo_2019.jpg.supplemen.json",   # recortado
        }
        for foto, nombre_json in casos.items():
            (c / foto).parent.mkdir(parents=True, exist_ok=True)
            (c / foto).write_bytes(b"x")
            json_google(c / nombre_json, foto, datetime(2019, 1, 1))
        (c / "PXL_1.MP.jpg").write_bytes(b"x")
        (c / "renombrada.jpg").write_bytes(b"x")
        json_google(c / ("cualquier_cosa" + SUFIJO), "renombrada.jpg", datetime(2019, 1, 1))
        casos["renombrada.jpg"] = "cualquier_cosa" + SUFIJO   # por su "title"

        indice = IndiceTakeout(self.dir)
        for foto, nombre_json in casos.items():
            with self.subTest(foto=foto):
                self.assertEqual(indice.json_de(c / foto), c / nombre_json)

    def test_video_de_live_photo_usa_el_json_de_su_foto(self):
        c = self.dir / "Fotos del 2025"
        crear_foto(c / "IMG_0263.jpg", fecha="2025:03:01 12:48:03")
        (c / "IMG_0263.MP4").write_bytes(b"x")
        json_google(c / ("IMG_0263.jpg" + SUFIJO), "IMG_0263.jpg", datetime(2025, 3, 1),
                    gps=(37.4, -5.9))
        (c / "otro.MP4").write_bytes(b"x")   # sin foto al lado: sin JSON
        indice = IndiceTakeout(self.dir)
        self.assertEqual(indice.json_de(c / "IMG_0263.MP4"), c / ("IMG_0263.jpg" + SUFIJO))
        extra = indice.metadatos(c / "IMG_0263.MP4")
        self.assertEqual(extra.fecha, datetime(2025, 3, 1, 12, 48, 3))   # la de la foto
        self.assertTrue(extra.fecha_prioritaria)
        self.assertIsNone(indice.json_de(c / "otro.MP4"))

    def test_editada_se_omite_solo_si_esta_su_original(self):
        c = self.dir / "Fotos del 2014"
        for nombre in ("IMG_1.jpg", "IMG_1-editada.jpg", "solo-editada.jpg"):
            (c / nombre).parent.mkdir(parents=True, exist_ok=True)
            (c / nombre).write_bytes(b"x")
        json_google(c / ("IMG_1.jpg" + SUFIJO), "IMG_1.jpg", datetime(2014, 3, 30))
        indice = IndiceTakeout(self.dir)
        self.assertIn("editada", indice.omitir(c / "IMG_1-editada.jpg"))
        self.assertIsNone(indice.omitir(c / "IMG_1.jpg"))
        self.assertIsNone(indice.omitir(c / "solo-editada.jpg"))   # sin original: se importa
        # La editada usa el JSON del original
        self.assertEqual(indice.json_de(c / "IMG_1-editada.jpg"), c / ("IMG_1.jpg" + SUFIJO))

    def test_papelera_se_omite(self):
        c = self.dir / "Fotos del 2020"
        c.mkdir()
        (c / "borrada.jpg").write_bytes(b"x")
        json_google(c / ("borrada.jpg" + SUFIJO), "borrada.jpg", datetime(2020, 1, 1),
                    trashed=True)
        self.assertIn("papelera", IndiceTakeout(self.dir).omitir(c / "borrada.jpg"))


class Albumes(CasoConCarpeta):
    def test_album_por_carpeta_y_por_json_suelto(self):
        fecha = datetime(2019, 6, 1, 10, 10, 10)
        anio = self.dir / "Fotos del 2019"
        anio.mkdir()
        (anio / "IMG_1.jpg").write_bytes(b"x")
        json_google(anio / ("IMG_1.jpg" + SUFIJO), "IMG_1.jpg", fecha)
        # Álbum con la foto dentro
        album(self.dir / "Boda Moi", "Boda Moi")
        (self.dir / "Boda Moi" / "IMG_1.jpg").write_bytes(b"x")
        json_google(self.dir / "Boda Moi" / ("IMG_1.jpg" + SUFIJO), "IMG_1.jpg", fecha)
        # Álbum que solo trae el JSON (la foto está únicamente en Fotos del 2019)
        album(self.dir / "Viaje a Berlin", "Viaje a Berlín")
        json_google(self.dir / "Viaje a Berlin" / ("IMG_1.jpg" + SUFIJO), "IMG_1.jpg", fecha)
        # Álbum automático con nombre de fecha: no aporta etiqueta
        album(self.dir / "07-04-13", "07/04/13")
        json_google(self.dir / "07-04-13" / ("IMG_1.jpg" + SUFIJO), "IMG_1.jpg", fecha)

        indice = IndiceTakeout(self.dir)
        self.assertEqual(indice.metadatos(anio / "IMG_1.jpg").etiquetas,
                         ["Boda Moi", "Viaje a Berlín"])
        self.assertEqual(indice.metadatos(self.dir / "Boda Moi" / "IMG_1.jpg").etiquetas,
                         ["Boda Moi", "Viaje a Berlín"])
        self.assertEqual(indice.cuenta["albumes"], 2)

    def test_nombres_de_album(self):
        self.assertEqual(nombre_album("A drenar el pulpo :o)", "A drenar el pulpo _o)"),
                         "A drenar el pulpo :o)")
        self.assertEqual(nombre_album("", "Desconocido, Fátima"), "Desconocido, Fátima")
        for inutil in ("07/04/13", "2014-03-30", "18-4-14", "Sin título"):
            self.assertIsNone(nombre_album(inutil, inutil))


class MetadatosDelJson(CasoConCarpeta):
    def test_lee_fecha_local_gps_personas_y_descripcion(self):
        c = self.dir / "Fotos del 2025"
        c.mkdir()
        (c / "a.jpg").write_bytes(b"x")
        fecha = datetime(2025, 8, 6, 20, 52, 26)
        json_google(c / ("a.jpg" + SUFIJO), "a.jpg", fecha, gps=(36.2682833, -6.0900833),
                    personas=["Javier", "Ana"], descripcion="  Atardecer en Vejer ",
                    favorited=True)
        extra = IndiceTakeout(self.dir).metadatos(c / "a.jpg")
        self.assertEqual(extra.fecha, fecha)
        self.assertRegex(extra.zona, r"^[+-]\d\d:\d\d$")
        self.assertEqual(extra.gps[:2], (36.2682833, -6.0900833))
        self.assertEqual(extra.personas, ["Javier", "Ana"])
        self.assertEqual(extra.descripcion, "Atardecer en Vejer")
        self.assertTrue(extra.favorita)

    def test_gps_a_cero_no_cuenta_y_sin_fecha_usa_la_de_subida(self):
        c = self.dir / "Alex de visita"
        c.mkdir()
        (c / "06_08_11 - 2.jpg").write_bytes(b"x")
        json_google(c / ("06_08_11 - 2" + SUFIJO), "06/08/11 - 2", None)   # "timestamp": "0"
        extra = IndiceTakeout(self.dir).metadatos(c / "06_08_11 - 2.jpg")
        self.assertIsNone(extra.gps)
        self.assertEqual(extra.fecha, datetime(2025, 1, 1))   # creationTime de json_google
        self.assertEqual((extra.fuente, extra.fecha_dudosa), ("google_subida", True))
        # Se usa antes que la fecha del archivo, pero no se graba como fecha de captura
        fecha, fuente = elegir_fecha(Path("x.jpg"), datetime(2026, 11, 22), "archivo", extra)
        self.assertEqual((fecha, fuente), (datetime(2025, 1, 1), "google_subida"))
        self.assertIsNone(metadatos_para_escribir(Path("x.jpg"), extra, fecha, fuente).fecha)

    def test_clip_toma_la_fecha_de_su_foto(self):
        c = self.dir / "al compás de la luna"
        crear_foto(c / "PXL_20260627_181032722.MP.jpg", fecha="2026:06:27 18:10:32")
        (c / "PXL_20260627_181032722.MP").write_bytes(b"x")
        json_google(c / ("PXL_20260627_181032722.MP.jpg" + SUFIJO),
                    "PXL_20260627_181032722.MP.jpg", datetime(2026, 6, 27, 16, 10, 32))
        indice = IndiceTakeout(self.dir)
        extra = indice.metadatos(c / "PXL_20260627_181032722.MP")
        self.assertEqual(extra.fecha, datetime(2026, 6, 27, 18, 10, 32))
        self.assertTrue(extra.fecha_prioritaria)
        self.assertEqual(indice.cuenta["clips"], 1)


class Fechas(unittest.TestCase):
    JSON = MetadatosExtra(fecha=datetime(2024, 5, 12, 18, 30))

    def test_orden(self):
        exif = datetime(2024, 5, 12, 17, 0)
        self.assertEqual(elegir_fecha(Path("a.jpg"), exif, "exif", self.JSON), (exif, "exif"))
        # Nombre con hora: manda sobre el JSON (en las fotos sin EXIF suele ser la subida)
        nombre = datetime(2024, 5, 12, 10, 20, 30)
        self.assertEqual(elegir_fecha(Path("PANO_20240512_102030.jpg"), nombre, "nombre",
                                      self.JSON), (nombre, "nombre"))
        # Nombre sin hora (WhatsApp) del mismo día: el JSON aporta la hora
        dia = datetime(2024, 5, 12)
        self.assertEqual(elegir_fecha(Path("IMG-20240512-WA0001.jpg"), dia, "nombre",
                                      self.JSON), (self.JSON.fecha, "google"))
        # ...de otro día: se queda el del nombre
        self.assertEqual(elegir_fecha(Path("IMG-20240101-WA0001.jpg"), datetime(2024, 1, 1),
                                      "nombre", self.JSON)[1], "nombre")
        # Sin nada mejor: el JSON antes que la fecha del archivo
        self.assertEqual(elegir_fecha(Path("scan.jpg"), datetime(2026, 11, 22), "archivo",
                                      self.JSON), (self.JSON.fecha, "google"))

    def test_solo_se_graba_una_fecha_con_hora(self):
        ruta = Path("IMG-20240101-WA0001.jpg")
        self.assertIsNone(metadatos_para_escribir(ruta, self.JSON, datetime(2024, 1, 1),
                                                  "nombre").fecha)
        self.assertEqual(metadatos_para_escribir(ruta, self.JSON, self.JSON.fecha,
                                                 "google").fecha, self.JSON.fecha)


class Escritura(CasoConCarpeta):
    EXTRA = MetadatosExtra(fecha=datetime(2013, 4, 6, 16, 35, 55), zona="+02:00",
                           gps=(36.2682833, -6.0900833, 55.5), descripcion="Cumple de Ana",
                           etiquetas=["Boda Moi", "Viaje a Berlín"],
                           personas=["Javier Aragón"], favorita=True)

    def test_foto_sin_exif_recibe_todo(self):
        origen = crear_foto(self.dir / "scan.jpg", fecha=None)
        destino = self.dir / "b.jpg"
        guardar_optimizada(origen, destino, extra=self.EXTRA)
        datos = leer_metadatos(destino)
        self.assertEqual((datos["fecha"], datos["fuente"]), (self.EXTRA.fecha, "exif"))
        self.assertAlmostEqual(datos["gps"][0], 36.268283, places=5)
        self.assertAlmostEqual(datos["gps"][1], -6.090083, places=5)
        self.assertEqual(datos["etiquetas"], ["Boda Moi", "Viaje a Berlín"])
        self.assertEqual(datos["personas"], ["Javier Aragón"])
        self.assertEqual(datos["descripcion"], "Cumple de Ana")
        self.assertEqual(datos["valoracion"], 5)
        with Image.open(destino) as im:
            self.assertEqual(im.getexif().get_ifd(0x8769).get(0x9011), "+02:00")

    def test_foto_sin_ningun_exif_recibe_la_fecha(self):
        # Error anterior: la fecha iba al sub-IFD, len(exif) seguía a 0 y no se guardaba
        Image.new("RGB", (64, 48), (90, 90, 90)).save(self.dir / "PANO_1.jpg")
        for nombre, opciones in (("b.jpg", None), ("c.jpg", OpcionesFotos(calidad=100))):
            guardar_optimizada(self.dir / "PANO_1.jpg", self.dir / nombre, opciones,
                               MetadatosExtra(fecha=datetime(2012, 7, 14, 12, 48, 17)))
            datos = leer_metadatos(self.dir / nombre)
            self.assertEqual((datos["fecha"], datos["fuente"]),
                             (datetime(2012, 7, 14, 12, 48, 17), "exif"))
        sin_recomprimir = jpeg_con_extra((self.dir / "PANO_1.jpg").read_bytes(),
                                         MetadatosExtra(gps=(36.5, -6.2, None)))
        (self.dir / "d.jpg").write_bytes(sin_recomprimir)
        self.assertAlmostEqual(leer_metadatos(self.dir / "d.jpg")["gps"][0], 36.5, places=4)

    def test_no_pisa_lo_que_ya_trae_la_foto(self):
        origen = crear_foto(self.dir / "a.jpg", completa=True)
        destino = self.dir / "b.jpg"
        guardar_optimizada(origen, destino, extra=self.EXTRA)
        datos = leer_metadatos(destino)
        self.assertEqual(datos["fecha"], datetime(2023, 8, 15, 20, 31, 7))   # la del EXIF
        self.assertAlmostEqual(datos["gps"][0], 36.53, places=2)             # su GPS
        self.assertEqual(datos["etiquetas"][:4], ["playa", "vacaciones", "Boda Moi",
                                                  "Viaje a Berlín"])
        self.assertEqual(datos["personas"], ["Ana", "Javier Aragón"])
        self.assertEqual(datos["valoracion"], 4)                              # su valoración
        self.assertEqual(datos["titulo"], "Atardecer")                        # resto del XMP

    def test_xmp_sin_nada_que_anadir_queda_igual(self):
        self.assertIs(completar_xmp(XMP_PRUEBA, MetadatosExtra()), XMP_PRUEBA)
        self.assertIsNone(completar_xmp(None, None))

    def test_xmp_no_repite_etiquetas(self):
        xmp = completar_xmp(XMP_PRUEBA, MetadatosExtra(etiquetas=["Playa", "Nueva"]))
        self.assertEqual(leer_xmp(xmp)["etiquetas"], ["playa", "vacaciones", "Nueva"])
        self.assertIn(b"xmlns:dc=", xmp)   # conserva los prefijos habituales

    def test_jpeg_sin_recomprimir(self):
        origen = crear_foto(self.dir / "a.jpg", fecha=None, completa=True)
        datos = origen.read_bytes() + b"VIDEO-DE-LA-FOTO-CON-MOVIMIENTO"
        nuevo = jpeg_con_extra(datos, self.EXTRA)
        imagen = datos[datos.index(b"\xff\xda"):]
        self.assertTrue(nuevo.endswith(imagen))   # píxeles y cola, byte a byte
        (self.dir / "b.jpg").write_bytes(nuevo)
        leidos = leer_metadatos(self.dir / "b.jpg")
        self.assertEqual(leidos["fecha"], self.EXTRA.fecha)
        self.assertIn("Boda Moi", leidos["etiquetas"])
        self.assertIn("Cadiz", leidos["etiquetas"])   # IPTC intacto
        self.assertAlmostEqual(leidos["gps"][0], 36.53, places=2)   # GPS propio intacto

    def test_jpeg_sin_nada_que_anadir_no_cambia(self):
        datos = crear_foto(self.dir / "a.jpg").read_bytes()
        self.assertIs(jpeg_con_extra(datos, MetadatosExtra()), datos)

    def test_foto_con_movimiento_pierde_el_anuncio_al_recomprimir(self):
        xmp = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
               b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
               b'<rdf:Description rdf:about="" xmlns:GCamera="http://ns.google.com/photos/1.0/camera/"'
               b' xmlns:Container="http://ns.google.com/photos/1.0/container/"'
               b' GCamera:MotionPhoto="1" GCamera:MotionPhotoVersion="1">'
               b'<Container:Directory><rdf:Seq><rdf:li>x</rdf:li></rdf:Seq></Container:Directory>'
               b'</rdf:Description></rdf:RDF></x:xmpmeta>')
        origen = crear_foto(self.dir / "PXL_1.MP.jpg", xmp=xmp)
        guardar_optimizada(origen, self.dir / "b.jpg")
        with Image.open(self.dir / "b.jpg") as im:
            salida = im.info["xmp"]
        self.assertNotIn(b"MotionPhoto", salida)
        self.assertNotIn(b"Container:Directory", salida)
        self.assertIn(b"rdf:Description", salida)


class ImportacionGoogle(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.origen = self.dir / "Takeout" / "Google Fotos"
        self.destino = self.dir / "Pruebas google"
        anio = self.origen / "Fotos del 2019"
        # WhatsApp sin EXIF: la hora sale del JSON (mismo día que el nombre)
        crear_foto(anio / "IMG-20190512-WA0001.jpg", fecha=None, color=(10, 200, 30))
        json_google(anio / ("IMG-20190512-WA0001.jpg" + SUFIJO), "IMG-20190512-WA0001.jpg",
                    datetime(2019, 5, 12, 18, 30), gps=(40.4168, -3.7038), personas=["Ana"])
        # La misma foto en un álbum
        album(self.origen / "Boda Moi", "Boda Moi")
        (self.origen / "Boda Moi" / "IMG-20190512-WA0001.jpg").write_bytes(
            (anio / "IMG-20190512-WA0001.jpg").read_bytes())
        json_google(self.origen / "Boda Moi" / ("IMG-20190512-WA0001.jpg" + SUFIJO),
                    "IMG-20190512-WA0001.jpg", datetime(2019, 5, 12, 18, 30))
        # Foto con EXIF, su versión editada y un álbum que solo trae su JSON
        crear_foto(anio / "IMG_20190601_101010.jpg", fecha="2019:06:01 10:10:10",
                   color=(30, 30, 220))
        crear_foto(anio / "IMG_20190601_101010-editada.jpg", fecha="2019:06:01 10:10:10",
                   color=(200, 200, 20))
        json_google(anio / ("IMG_20190601_101010.jpg" + SUFIJO), "IMG_20190601_101010.jpg",
                    datetime(2019, 6, 1, 10, 10, 10))
        album(self.origen / "Viaje a Berlin", "Viaje a Berlín")
        json_google(self.origen / "Viaje a Berlin" / ("IMG_20190601_101010.jpg" + SUFIJO),
                    "IMG_20190601_101010.jpg", datetime(2019, 6, 1, 10, 10, 10))
        # Escaneada, sin EXIF ni fecha en el nombre, con contador
        crear_foto(anio / "scan(1).jpg", fecha=None, color=(120, 10, 120))
        json_google(anio / "scan.jpg.supplemental-metadata(1).json", "scan.jpg",
                    datetime(2019, 2, 3, 4, 5, 6))

    def test_importa_con_los_metadatos_y_sin_json(self):
        indice = IndiceTakeout(self.origen)
        stats = procesar_fotos(self.origen, self.destino, False, OpcionesFotos(externos=indice))
        fotos = [f for f in self.archivos(self.destino) if not f.startswith(".exportador")]
        self.assertEqual(fotos, ["2019/02-Febrero/20190203_040506.jpg",
                                 "2019/06-Junio/20190601_101010.jpg",
                                 "WhatsApp/2019/05-Mayo/20190512_183000.jpg"])
        self.assertEqual((stats["editadas"], stats["duplicados"], stats["con_json"]), (1, 1, 3))

        wa = leer_metadatos(self.destino / "WhatsApp/2019/05-Mayo/20190512_183000.jpg")
        self.assertEqual(wa["fecha"], datetime(2019, 5, 12, 18, 30))
        self.assertEqual(wa["etiquetas"], ["Boda Moi"])
        self.assertEqual(wa["personas"], ["Ana"])
        self.assertAlmostEqual(wa["gps"][0], 40.4168, places=4)
        exif = leer_metadatos(self.destino / "2019/06-Junio/20190601_101010.jpg")
        self.assertEqual(exif["etiquetas"], ["Viaje a Berlín"])
        scan = leer_metadatos(self.destino / "2019/02-Febrero/20190203_040506.jpg")
        self.assertEqual((scan["fecha"], scan["fuente"]), (datetime(2019, 2, 3, 4, 5, 6), "exif"))

        informe = next((self.destino / ".exportador" / "informes").glob("fotos_*.csv"))
        texto = informe.read_text(encoding="utf-8-sig")
        self.assertIn("OMITIDA", texto)
        self.assertIn("añade: ", texto)
        self.assertIn("1 álbum(es)", texto)

    def test_si_recomprimir_no_compensa_mete_los_metadatos_sin_recomprimir(self):
        # Ruido muy comprimido: con calidad 100 pesaría más
        ruido = Image.effect_noise((400, 300), 80).convert("RGB")
        ruido.save(self.origen / "Fotos del 2019" / "scan(1).jpg", quality=30)
        indice = IndiceTakeout(self.origen)
        opciones = OpcionesFotos(externos=indice, calidad=100)   # recomprimida pesa más
        procesar_fotos(self.origen, self.destino, False, opciones)
        original = (self.origen / "Fotos del 2019" / "scan(1).jpg").read_bytes()
        salida = (self.destino / "2019/02-Febrero/20190203_040506.jpg").read_bytes()
        self.assertTrue(salida.endswith(original[original.index(b"\xff\xda"):]))
        self.assertEqual(leer_metadatos(self.destino / "2019/02-Febrero/20190203_040506.jpg")
                         ["fecha"], datetime(2019, 2, 3, 4, 5, 6))

    def test_comando_google_en_simulacion_no_crea_nada(self):
        from main import main
        main(["google", str(self.origen), "--destino", str(self.destino), "--simular"])
        self.assertFalse(self.destino.exists())
        self.assertIn("Editadas (va el original)", self.consola.getvalue())


class ClipsDeFotosConMovimiento(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.origen, self.destino = self.dir / "Google Fotos", self.dir / "biblioteca"
        c = self.origen / "al compás de la luna"
        album(c, "al compás de la luna")
        crear_foto(c / "PXL_20260627_181032722.MP.jpg", fecha="2026:06:27 18:10:32")
        (c / "PXL_20260627_181032722.MP").write_bytes(
            b"\x00\x00\x00\x14ftypisom" + b"v" * 984)
        json_google(c / ("PXL_20260627_181032722.MP.jpg" + SUFIJO),
                    "PXL_20260627_181032722.MP.jpg", datetime(2026, 6, 27, 18, 10, 32),
                    gps=(36.27, -6.09))

    def procesar(self, bytes_salida):
        comandos = []

        def ffmpeg(cmd, duracion=0, etiqueta="", video=""):
            comandos.append(cmd)
            Path(cmd[-1]).write_bytes(b"x" * bytes_salida)
            return True, ""
        info = {"fecha": datetime(2026, 6, 27, 18, 10, 31), "ancho": 1920, "alto": 1080,
                "duracion": 1.5, "gps": None}
        with mock.patch("videos.sondear", return_value=info), \
                mock.patch("videos.ejecutar_ffmpeg", side_effect=ffmpeg):
            videos.procesar_videos(self.origen, self.destino, False,
                                   videos.OpcionesVideos(externos=IndiceTakeout(self.origen)))
        return comandos

    def test_clip_se_llama_como_su_foto_y_lleva_metadatos(self):
        comandos = self.procesar(bytes_salida=100)
        self.assertTrue((self.destino / "2026/06-Junio/20260627_181032.mp4").exists())
        cmd = " ".join(comandos[0])
        self.assertIn("keywords=al compás de la luna", cmd)
        self.assertIn("location=+36.2700-006.0900/", cmd)
        self.assertNotIn("creation_time", cmd)   # el clip ya trae la suya

    def test_si_no_compensa_se_remultiplexa_como_mp4(self):
        comandos = self.procesar(bytes_salida=5000)
        self.assertTrue((self.destino / "2026/06-Junio/20260627_181032.mp4").exists())
        self.assertIn("copy", comandos[-1])   # sin recodificar, con los metadatos

    def test_argumentos_solo_lo_que_falta(self):
        extra = MetadatosExtra(fecha=datetime(2024, 5, 12, 10, 0), gps=(40.0, -3.5, None),
                               descripcion="Hola", etiquetas=["Boda"], personas=["Ana"])
        args = videos.argumentos_metadatos(extra, {"fecha": None, "gps": None})
        texto = " ".join(args)
        self.assertRegex(texto, r"creation_time=2024-05-12T\d\d:00:00Z")
        self.assertIn("location=+40.0000-003.5000/", texto)
        self.assertIn("description=Hola", texto)
        self.assertIn("keywords=Boda, Ana", texto)
        args = videos.argumentos_metadatos(extra, {"fecha": datetime(2024, 1, 1),
                                                   "gps": [1.0, 2.0]})
        self.assertNotIn("creation_time", " ".join(args))
        self.assertNotIn("location", " ".join(args))


class FechaIsoRepetida(unittest.TestCase):
    def test_ffmpeg_repite_creation_time(self):
        from media_utils import parsear_fecha_iso
        fecha = parsear_fecha_iso("2024-05-12T08:20:30.000000Z;2024-05-12T08:20:30.000000Z")
        self.assertIsNotNone(fecha)


if __name__ == "__main__":
    unittest.main()
