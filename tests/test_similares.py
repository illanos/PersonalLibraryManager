"""Mejora 1: fotos casi idénticas (hash perceptual)."""

import csv
import json
import sqlite3
import unittest
from contextlib import closing

from PIL import Image, ImageDraw, ImageFilter

import galeria
from catalogo import Catalogo, ruta_catalogo
from fotos import OpcionesFotos, procesar_fotos
from similares import agrupar, dhash, distancia
from tests.ayudas import CasoConCarpeta


def escena(ruta, semilla=0, tam=(1200, 900), calidad=92, fecha=None):
    """Foto con formas (no lisa) reproducible; misma semilla = misma escena."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", tam, (30 + semilla * 40 % 200, 90, 160))
    d = ImageDraw.Draw(im)
    for i in range(12):
        x = (i * 97 + semilla * 211) % tam[0]
        y = (i * 53 + semilla * 137) % tam[1]
        d.ellipse((x, y, x + 180, y + 120), fill=((i * 40 + semilla * 70) % 255, 200 - i * 10, 40))
        d.rectangle((y % tam[0], x % tam[1], y % tam[0] + 90, x % tam[1] + 200),
                    fill=(250 - i * 15, (i * 60) % 255, 120))
    im = im.filter(ImageFilter.GaussianBlur(2))
    kwargs = {"quality": calidad}
    if fecha:
        exif = Image.Exif()
        exif.get_ifd(0x8769)[36867] = fecha
        kwargs["exif"] = exif
    im.save(ruta, **kwargs)
    return ruta


class Hash(CasoConCarpeta):
    def test_recomprimida_y_reducida_se_parece_y_otra_no(self):
        a = escena(self.dir / "a.jpg", 1)
        with Image.open(a) as im:
            im.resize((600, 450)).save(self.dir / "b.jpg", quality=55)   # "WhatsApp"
        c = escena(self.dir / "c.jpg", 2)
        self.assertLessEqual(distancia(dhash(a), dhash(self.dir / "b.jpg")), 6)
        self.assertGreater(distancia(dhash(a), dhash(c)), 20)

    def test_agrupar_por_bandas(self):
        base = int("f0" * 16, 16)
        hashes = {"a": f"{base:032x}", "b": f"{base ^ 0b1011:032x}",   # 3 bits
                  "c": f"{base ^ (2**100 - 1):032x}",                   # muy distinta
                  "lisa": "0" * 32}                                     # sin detalle
        self.assertEqual([sorted(g) for g in agrupar(hashes)], [["a", "b"]])

    def test_proporcion_distinta_no_agrupa(self):
        h = f"{int('f0' * 16, 16):032x}"
        self.assertEqual(agrupar({"a": h, "b": h}, {"a": 1.33, "b": 0.56}), [])


class Importacion(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.origen, self.bib = self.dir / "movil", self.dir / "bib"
        buena = escena(self.origen / "WhatsApp Images" / "IMG-20240512-WA0001.jpg", 3,
                       fecha="2024:05:12 10:00:00")
        sent = self.origen / "WhatsApp Images" / "Sent"
        sent.mkdir()
        with Image.open(buena) as im:   # la misma foto, reducida y recomprimida
            im.resize((800, 600)).save(sent / "IMG-20240512-WA0002.jpg", quality=60,
                                       exif=im.getexif())
        escena(self.origen / "otra.jpg", 4, fecha="2024:05:13 10:00:00")

    def procesar(self, **op):
        return procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=2, **op))

    def informe(self):
        ruta = sorted((self.bib / ".exportador" / "informes").glob("fotos_*.csv"))[-1]
        with open(ruta, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))

    def test_marca_parecidas_en_informe_y_catalogo_sin_omitir(self):
        stats = self.procesar()
        self.assertEqual((stats["procesados"], stats["parecidas"]), (3, 2))
        filas = {f["origen"].replace("\\", "/").split("/")[-1]: f for f in self.informe()}
        self.assertIn("IMG-20240512-WA0002.jpg", filas["IMG-20240512-WA0001.jpg"]["parecidas"])
        self.assertEqual(filas["otra.jpg"]["parecidas"], "")
        with closing(sqlite3.connect(ruta_catalogo(self.bib))) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM archivos WHERE phash IS NOT NULL").fetchone()[0], 3)

    def test_omitir_parecidas_deja_la_mejor_y_no_reanaliza(self):
        stats = self.procesar(omitir_parecidas=True)
        self.assertEqual((stats["procesados"], stats["parecidas_omitidas"]), (2, 1))
        with Catalogo(self.bib) as cat:
            origenes = {f["origen"] for f in cat.filas()}
        self.assertTrue(any(o.endswith("WA0001.jpg") for o in origenes))   # la grande
        self.assertFalse(any(o.endswith("WA0002.jpg") for o in origenes))
        self.assertTrue((self.origen / "WhatsApp Images" / "Sent" / "IMG-20240512-WA0002.jpg").exists())
        import fotos
        from unittest import mock
        with mock.patch.object(fotos, "dhash", side_effect=AssertionError("reanaliza")):
            stats = self.procesar(omitir_parecidas=True)
        self.assertEqual((stats["procesados"], stats["ya_importados"],
                          stats["parecidas_omitidas"]), (0, 2, 1))

    def test_nueva_peor_que_una_ya_importada_se_omite(self):
        sent = self.origen / "WhatsApp Images" / "Sent"
        guardada = self.dir / "aparte.jpg"
        (sent / "IMG-20240512-WA0002.jpg").replace(guardada)
        self.procesar(omitir_parecidas=True)
        guardada.replace(sent / "IMG-20240512-WA0002.jpg")
        stats = self.procesar(omitir_parecidas=True)
        self.assertEqual((stats["procesados"], stats["parecidas_omitidas"]), (0, 1))

    def test_rafaga_se_marca_pero_no_se_omite(self):
        # Dos tomas casi idénticas, cada una con su fecha EXIF: son fotos distintas
        escena(self.origen / "Camera" / "PXL_1.jpg", 9, fecha="2025:02:07 19:54:40")
        escena(self.origen / "Camera" / "PXL_2.jpg", 9, fecha="2025:02:07 19:54:42", calidad=80)
        stats = self.procesar(omitir_parecidas=True)
        self.assertEqual((stats["procesados"], stats["parecidas_omitidas"]), (4, 1))
        filas = {f["origen"].replace("\\", "/").split("/")[-1]: f for f in self.informe()}
        self.assertIn("PXL_2.jpg", filas["PXL_1.jpg"]["parecidas"])
        self.assertEqual(filas["PXL_1.jpg"]["accion"], "OK")
        self.assertEqual(filas["PXL_2.jpg"]["accion"], "OK")

    def test_catalogo_antiguo_se_migra(self):
        ruta = ruta_catalogo(self.bib)
        ruta.parent.mkdir(parents=True)
        with closing(sqlite3.connect(ruta)) as db:   # esquema de la versión 1
            db.executescript("""CREATE TABLE archivos (hash TEXT PRIMARY KEY, tipo TEXT NOT NULL,
                origen TEXT NOT NULL, tamano INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                destino TEXT NOT NULL, original TEXT, fecha TEXT, fuente_fecha TEXT,
                bytes_antes INTEGER, bytes_despues INTEGER, importado TEXT NOT NULL);
                INSERT INTO archivos VALUES ('x','foto','o',1,1,'d',NULL,NULL,NULL,1,1,'hoy');""")

        self.assertEqual(self.procesar()["procesados"], 3)
        with closing(sqlite3.connect(ruta)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM archivos").fetchone()[0], 4)



class Galeria(CasoConCarpeta):
    def test_grupo_en_json_y_hash_reutilizado(self):
        bib = self.dir / "bib"
        a = escena(bib / "2024" / "a.jpg", 5)
        with Image.open(a) as im:
            im.resize((640, 480)).save(bib / "2024" / "b.jpg", quality=50)
        escena(bib / "2024" / "c.jpg", 6)
        galeria.generar_galeria(bib)
        datos = json.loads((bib / "galeria.json").read_text(encoding="utf-8"))
        por = {e["src"]: e for e in datos["elementos"]}
        self.assertEqual(por["2024/a.jpg"]["parecidas"], por["2024/b.jpg"]["parecidas"])
        self.assertIn("Parecidas", por["2024/a.jpg"]["auto"])
        self.assertNotIn("parecidas", por["2024/c.jpg"])
        from unittest import mock
        with mock.patch.object(galeria, "dhash", side_effect=AssertionError("recalcula")):
            elementos, _ = galeria.construir_indice(bib)
        self.assertEqual(sum("parecidas" in e for e in elementos), 2)


if __name__ == "__main__":
    unittest.main()
