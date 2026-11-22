"""Mejora 3: fechas aproximadas (nombre con fecha pero sin hora, como WhatsApp)."""

import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import videos
from catalogo import Catalogo
from fotos import OpcionesFotos, procesar_fotos
from main import main
from media_utils import fecha_y_nombre, nombre_tiene_hora
from tests.ayudas import CasoConCarpeta, crear_foto


def poner_mtime(ruta: Path, fecha: datetime):
    marca = fecha.timestamp()
    os.utime(ruta, (marca, marca))


class Reglas(CasoConCarpeta):
    def test_misma_fecha_usa_la_hora_del_archivo(self):
        ruta = self.dir / "IMG-20260121-WA0011.jpg"
        ruta.write_bytes(b"x")
        poner_mtime(ruta, datetime(2026, 1, 21, 18, 30, 12))
        self.assertEqual(fecha_y_nombre(ruta, datetime(2026, 1, 21), "nombre"),
                         (datetime(2026, 1, 21, 18, 30, 12), "nombre+hora_archivo",
                          "20260121_183012"))

    def test_otro_dia_nombre_claro(self):
        ruta = self.dir / "IMG-20260121-WA0011.jpg"
        ruta.write_bytes(b"x")
        poner_mtime(ruta, datetime(2026, 3, 1, 9, 0, 0))
        self.assertEqual(fecha_y_nombre(ruta, datetime(2026, 1, 21), "nombre"),
                         (datetime(2026, 1, 21), "nombre", "20260121_WA0011"))
        otro = self.dir / "2026-01-21 cumple Ana.jpg"
        otro.write_bytes(b"x")
        poner_mtime(otro, datetime(2026, 3, 1))
        self.assertEqual(fecha_y_nombre(otro, datetime(2026, 1, 21), "nombre")[2],
                         "20260121_cumple-Ana")

    def test_con_hora_o_exif_no_cambia(self):
        self.assertTrue(nombre_tiene_hora("IMG_20240512_102030"))
        self.assertFalse(nombre_tiene_hora("IMG-20240512-WA0001"))
        ruta = self.dir / "IMG_20240512_000000.jpg"
        ruta.write_bytes(b"x")
        self.assertEqual(fecha_y_nombre(ruta, datetime(2024, 5, 12), "nombre")[2],
                         "20240512_000000")
        self.assertEqual(fecha_y_nombre(ruta, datetime(2024, 5, 12), "exif")[2], "20240512_000000")


class Importacion(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.origen, self.bib = self.dir / "movil", self.dir / "bib"
        wa = self.origen / "WhatsApp Images"
        poner_mtime(crear_foto(wa / "IMG-20260121-WA0011.jpg", fecha=None),
                    datetime(2026, 1, 21, 18, 30, 12))
        poner_mtime(crear_foto(wa / "IMG-20260121-WA0012.jpg", fecha=None, color=(0, 90, 0)),
                    datetime(2026, 2, 5, 8, 0, 0))

    def test_fotos_nuevas(self):
        procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=1))
        archivos = self.archivos(self.bib)
        self.assertIn("WhatsApp/2026/01-Enero/20260121_183012.jpg", archivos)
        self.assertIn("WhatsApp/2026/01-Enero/20260121_WA0012.jpg", archivos)
        self.assertFalse([a for a in archivos if "_000000" in a])

    def test_videos_nuevos(self):
        (self.origen / "WhatsApp Video").mkdir()
        video = self.origen / "WhatsApp Video" / "VID-20260121-WA0003.mp4"
        video.write_bytes(b"v" * 500)
        poner_mtime(video, datetime(2026, 4, 1))

        def codificar(cmd, duracion=0, etiqueta=""):
            Path(cmd[-1]).write_bytes(b"x" * 100)
            return True, ""
        with mock.patch("videos.sondear", return_value=None), \
                mock.patch("videos.ejecutar_ffmpeg", side_effect=codificar):
            videos.procesar_videos(self.origen, self.bib, False)
        self.assertIn("WhatsApp/2026/01-Enero/20260121_WA0003.mp4", self.archivos(self.bib))

    def test_lo_ya_importado_solo_se_renombra_si_se_pide(self):
        procesar_fotos(self.origen, self.bib, False, OpcionesFotos(hilos=1))
        # Como lo habría dejado la versión anterior
        viejo = "WhatsApp/2026/01-Enero/20260121_183012.jpg"
        antiguo = "WhatsApp/2026/01-Enero/20260121_000000.jpg"
        (self.bib / viejo).replace(self.bib / antiguo)
        with Catalogo(self.bib) as cat:
            cat.cambiar_destino(viejo, antiguo, datetime(2026, 1, 21).isoformat(), "nombre")
        origen_antes = {p: p.read_bytes() for p in self.origen.rglob("*") if p.is_file()}

        main(["fotos", str(self.origen), "--destino", str(self.bib)])   # sin la opción
        self.assertIn(antiguo, self.archivos(self.bib))

        main(["fotos", str(self.origen), "--destino", str(self.bib), "--renombrar-aproximadas"])
        archivos = self.archivos(self.bib)
        self.assertNotIn(antiguo, archivos)
        self.assertIn(viejo, archivos)
        with Catalogo(self.bib) as cat:
            fila = {f["destino"]: f for f in cat.filas()}[viejo]
        self.assertEqual((fila["fecha"], fila["fuente_fecha"]),
                         ("2026-01-21T18:30:12", "nombre+hora_archivo"))
        self.assertEqual({p: p.read_bytes() for p in self.origen.rglob("*") if p.is_file()},
                         origen_antes)


if __name__ == "__main__":
    unittest.main()
