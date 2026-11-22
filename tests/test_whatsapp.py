"""Mejora 2: contenido de WhatsApp separado del resto, pegatinas y capturas."""

import json
import unittest
from pathlib import Path, PurePath
from unittest import mock

from PIL import Image

import galeria
from catalogo import Catalogo
from clasificacion import ambito, categoria, es_pegatina, es_whatsapp
from fotos import OpcionesFotos, procesar_fotos
from main import main
from reorganizar import reorganizar
from tests.ayudas import CasoConCarpeta, crear_foto


def pegatina(ruta: Path):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (512, 512), (255, 0, 0, 128)).save(ruta, "WEBP")
    return ruta


class Clasificacion(unittest.TestCase):
    def test_reglas(self):
        self.assertTrue(es_whatsapp(PurePath("IMG-20240512-WA0001.jpg")))
        self.assertTrue(es_whatsapp(PurePath("WhatsApp Images/Sent/foto.jpg")))
        self.assertFalse(es_whatsapp(PurePath("Camera/IMG_20240512_101010.jpg")))
        self.assertTrue(es_pegatina(PurePath("STK-20250114-WA0008.webp")))
        self.assertTrue(es_pegatina(PurePath("WhatsApp Images/x.webp"), 512, 512))
        self.assertFalse(es_pegatina(PurePath("WhatsApp Images/x.webp"), 1600, 1200))
        self.assertFalse(es_pegatina(PurePath("Camera/x.webp"), 300, 300))
        self.assertEqual(categoria(PurePath("Screenshot_20240305-101112.jpg")), "captura")
        self.assertEqual(categoria(PurePath("Camera/IMG_1.jpg")), "")

    def test_ambito_en_galeria(self):
        self.assertEqual(ambito("WhatsApp/2024/05-Mayo/a.jpg"), "whatsapp")
        self.assertEqual(ambito("2024/05-Mayo/a.jpg", r"C:\m\WhatsApp Images\IMG-1.jpg"), "whatsapp")
        # La raíz del origen no cuenta: solo las últimas carpetas
        self.assertEqual(ambito("2024/05-Mayo/a.jpg", r"C:\Copia WhatsApp\a\b\c\IMG_1.jpg"), "")


class Importacion(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.origen, self.bib = self.dir / "movil", self.dir / "bib"
        crear_foto(self.origen / "Camera" / "IMG_1.jpg", fecha="2024:05:12 10:20:30")
        crear_foto(self.origen / "WhatsApp" / "Media" / "WhatsApp Images" / "IMG-20240512-WA0001.jpg",
                   fecha="2024:05:12 11:00:00", color=(10, 200, 30))
        pegatina(self.origen / "WhatsApp" / "Media" / "WhatsApp Stickers" / "STK-20240512-WA0002.webp")
        crear_foto(self.origen / "Screenshot_20240513-101112.jpg", tam=(300, 650), fecha=None,
                   color=(90, 90, 250))

    def foto(self, **op):
        return procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=2, **op))

    def test_whatsapp_va_aparte_y_la_pegatina_tal_cual(self):
        antes = {p: p.read_bytes() for p in self.origen.rglob("*") if p.is_file()}
        self.foto()
        archivos = self.archivos(self.bib)
        self.assertIn("2024/05-Mayo/20240512_102030.jpg", archivos)
        self.assertIn("WhatsApp/2024/05-Mayo/20240512_110000.jpg", archivos)
        self.assertIn("2024/05-Mayo/20240513_101112.jpg", archivos)   # captura: línea de tiempo
        pegatinas = [a for a in archivos if a.endswith(".webp")]
        self.assertEqual(len(pegatinas), 1)
        self.assertTrue(pegatinas[0].startswith("WhatsApp/2024/05-Mayo/"))
        self.assertEqual((self.bib / pegatinas[0]).read_bytes(),
                         antes[self.origen / "WhatsApp" / "Media" / "WhatsApp Stickers" /
                               "STK-20240512-WA0002.webp"])
        self.assertFalse([a for a in archivos if a.startswith("20") and "WA" in a])
        self.assertEqual({p: p.read_bytes() for p in self.origen.rglob("*") if p.is_file()}, antes)
        stats = self.foto()
        self.assertEqual((stats["procesados"], stats["ya_importados"]), (0, 4))

    def test_pegatinas_aparte(self):
        self.foto(pegatinas_aparte=True)
        self.assertTrue(any(a.startswith("WhatsApp/Pegatinas/2024/05-Mayo/")
                            for a in self.archivos(self.bib)))

    def test_galeria_marca_ambito_y_etiquetas(self):
        self.foto()
        galeria.generar_galeria(self.bib)
        datos = json.loads((self.bib / "galeria.json").read_text(encoding="utf-8"))
        por = {e["nombre_original"]: e for e in datos["elementos"]}
        wa = por["IMG-20240512-WA0001.jpg"]
        self.assertEqual(wa["ambito"], "whatsapp")
        self.assertIn("WhatsApp", wa["auto"])
        stk = por["STK-20240512-WA0002.webp"]
        self.assertEqual(stk["ambito"], "whatsapp")
        self.assertIn("Pegatinas", stk["auto"])
        self.assertNotIn("ambito", por["IMG_1.jpg"])
        self.assertIn("Capturas", por["Screenshot_20240513-101112.jpg"]["auto"])


class Reorganizar(CasoConCarpeta):
    """Bibliotecas importadas antes de separar WhatsApp."""

    def setUp(self):
        super().setUp()
        self.origen, self.bib = self.dir / "movil", self.dir / "bib"
        crear_foto(self.origen / "WhatsApp Images" / "IMG-20240512-WA0001.jpg",
                   fecha="2024:05:12 11:00:00")
        crear_foto(self.origen / "Camera" / "IMG_1.jpg", fecha="2024:05:12 10:20:30",
                   color=(0, 0, 200))
        procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=1))
        # Como lo habría dejado la versión anterior: mezclado en Año/Mes
        viejo, mezclado = "WhatsApp/2024/05-Mayo/20240512_110000.jpg", "2024/05-Mayo/20240512_110000.jpg"
        (self.bib / viejo).replace(self.bib / mezclado)
        (self.bib / "WhatsApp" / "2024" / "05-Mayo").rmdir()
        with Catalogo(self.bib) as cat:
            cat.cambiar_destino(viejo, mezclado)
        galeria.generar_galeria(self.bib)
        (self.bib / "_galeria" / "favoritos.json").write_text(json.dumps([mezclado]), encoding="utf-8")
        self.mezclado = mezclado

    def test_simular_no_mueve(self):
        antes = self.archivos(self.bib)
        stats = reorganizar(self.bib, simular=True, whatsapp=True)
        self.assertEqual(stats["movidos"], 1)
        self.assertEqual(self.archivos(self.bib), antes)

    def test_separa_y_actualiza_catalogo_galeria_y_favoritos(self):
        origen_antes = {p: p.read_bytes() for p in self.origen.rglob("*") if p.is_file()}
        main(["reorganizar", str(self.bib), "--whatsapp"])
        nuevo = "WhatsApp/2024/05-Mayo/20240512_110000.jpg"
        self.assertTrue((self.bib / nuevo).exists())
        self.assertFalse((self.bib / self.mezclado).exists())
        self.assertTrue((self.bib / "2024/05-Mayo/20240512_102030.jpg").exists())   # cámara: igual
        with Catalogo(self.bib) as cat:
            self.assertIn(nuevo, {f["destino"] for f in cat.filas()})
        favs = json.loads((self.bib / "_galeria" / "favoritos.json").read_text(encoding="utf-8"))
        self.assertEqual(favs, [nuevo])
        with mock.patch("metadatos.leer_metadatos") as leer:   # reutiliza metadatos y miniatura
            elementos, stats = galeria.construir_indice(self.bib)
        leer.assert_not_called()
        self.assertEqual(stats["reutilizados"], 2)
        self.assertEqual({e["src"]: e.get("ambito") for e in elementos}[nuevo], "whatsapp")
        self.assertEqual({p: p.read_bytes() for p in self.origen.rglob("*") if p.is_file()},
                         origen_antes)
        self.assertEqual(reorganizar(self.bib, whatsapp=True)["movidos"], 0)   # ya está


if __name__ == "__main__":
    unittest.main()
