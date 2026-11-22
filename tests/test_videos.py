"""Lógica de vídeo sin FFmpeg: se simulan ffprobe y la codificación."""

import json
import subprocess
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import videos
from tests.ayudas import CasoConCarpeta

CONTENIDO = b"\x00\x00\x00\x14ftypqt  " + b"v" * 984   # cabecera MOV válida, 1000 bytes

PROBE_IPHONE = {
    "format": {"duration": "12.5", "tags": {
        "creation_time": "2024-05-12T08:20:30.000000Z",
        "com.apple.quicktime.creationdate": "2024-05-12T10:20:30+0200",
        "com.apple.quicktime.make": "Apple", "com.apple.quicktime.model": "iPhone 13",
        "com.apple.quicktime.location.ISO6709": "+40.4168-003.7038+650.000/"}},
    "streams": [{"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080,
                 "side_data_list": [{"rotation": -90}]},
                {"codec_type": "audio"}],
}


class Sondeo(unittest.TestCase):
    def test_vertical_fecha_local_camara_y_gps(self):
        salida = subprocess.CompletedProcess([], 0, json.dumps(PROBE_IPHONE), "")
        with mock.patch("videos.subprocess.run", return_value=salida):
            info = videos.sondear(Path("x.mov"))
        self.assertEqual((info["ancho"], info["alto"]), (1080, 1920))   # se ve en vertical
        self.assertEqual(info["fecha"], datetime(2024, 5, 12, 10, 20, 30))
        self.assertEqual(info["camara"], "Apple iPhone 13")
        self.assertEqual(info["gps"], [40.4168, -3.7038])
        self.assertEqual(info["duracion"], 12.5)

    def test_ffprobe_falla(self):
        with mock.patch("videos.subprocess.run", side_effect=OSError):
            self.assertIsNone(videos.sondear(Path("x.mov")))


class Comando(unittest.TestCase):
    def test_escala_no_usa_dimensiones_fijas(self):
        # Error anterior: scale=1920:1080 deformaba los vídeos verticales de móvil
        filtro = videos.filtro_escala(1920)
        self.assertIn("if(gte(iw,ih)", filtro)
        self.assertIn("-2", filtro)
        self.assertNotIn("1080", filtro)

    def test_comando(self):
        cmd = videos.comando_codificacion(Path("a.mov"), Path("b.mp4.part"),
                                          videos.OpcionesVideos(codec="h265", crf=26))
        for esperado in ("-nostdin", "libx265", "hvc1", "-map_metadata"):
            self.assertIn(esperado, cmd)
        self.assertEqual(cmd[cmd.index("-crf") + 1], "26")
        self.assertEqual(cmd[-3:], ["-f", "mp4", "b.mp4.part"])

    def test_dimensiones_previstas(self):
        self.assertEqual(videos.dimensiones_objetivo(3840, 2160, 1920), (1920, 1080))
        self.assertEqual(videos.dimensiones_objetivo(1080, 1920, 1280), (720, 1280))
        self.assertEqual(videos.dimensiones_objetivo(1279, 721, 1920), (1278, 720))


class Procesamiento(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.origen, self.destino = self.dir / "videos", self.dir / "biblioteca"
        self.origen.mkdir()
        self.video = self.origen / "VID_20240512_102030.mov"
        self.video.write_bytes(CONTENIDO)

    def procesar(self, bytes_salida=None, ok=True, **opciones):
        def codificar(cmd, duracion=0, etiqueta=""):
            if bytes_salida is not None:
                Path(cmd[-1]).write_bytes(b"x" * bytes_salida)
            return ok, "" if ok else "Conversion failed!"
        with mock.patch("videos.sondear", return_value=None), \
                mock.patch("videos.ejecutar_ffmpeg", side_effect=codificar):
            return videos.procesar_videos(self.origen, self.destino, False,
                                          videos.OpcionesVideos(**opciones))

    def test_correcto_no_toca_el_original(self):
        stats = self.procesar(bytes_salida=100)
        self.assertEqual(stats["procesados"], 1)
        self.assertEqual(self.video.read_bytes(), CONTENIDO)
        archivos = self.archivos(self.destino)
        self.assertIn("2024/05-Mayo/20240512_102030.mp4", archivos)
        self.assertFalse(any(a.startswith("originales/") for a in archivos))
        self.assertFalse([a for a in archivos if a.endswith(".part")])

    def test_con_originales_copia_el_original(self):
        self.procesar(bytes_salida=100, conservar_originales=True)
        self.assertTrue(self.video.exists())
        self.assertIn("originales/2024/05-Mayo/VID_20240512_102030.mov",
                      self.archivos(self.destino))

    def test_segunda_ejecucion_no_reimporta(self):
        self.procesar(bytes_salida=100)
        stats = self.procesar(bytes_salida=100)
        self.assertEqual((stats["procesados"], stats["ya_importados"]), (0, 1))

    def test_si_no_reduce_peso_entra_el_original(self):
        stats = self.procesar(bytes_salida=5000)
        self.assertEqual(stats["sin_cambios"], 1)
        self.assertIn("2024/05-Mayo/20240512_102030.mov", self.archivos(self.destino))
        self.assertNotIn("2024/05-Mayo/20240512_102030.mp4", self.archivos(self.destino))
        self.assertTrue(self.video.exists())

    def test_error_no_toca_el_original(self):
        stats = self.procesar(bytes_salida=100, ok=False)
        self.assertEqual(stats["errores"], 1)
        self.assertTrue(self.video.exists())
        self.assertFalse([a for a in self.archivos(self.destino)
                          if a.endswith((".mp4", ".part"))])

    def test_segunda_ejecucion_no_repite(self):
        self.procesar(bytes_salida=100)
        self.video.write_bytes(CONTENIDO)   # mismo contenido vuelve a aparecer
        stats = self.procesar(bytes_salida=100)
        self.assertEqual((stats["procesados"], stats["ya_importados"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
