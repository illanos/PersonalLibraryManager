"""Mejora 5: vídeos en paralelo y aceleración por hardware (FFmpeg simulado)."""

import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from exportador import videos
from exportador.cli import construir_parser, opciones_videos
from tests.ayudas import CasoConCarpeta
from tests.test_videos import CONTENIDO

LISTA_ENCODERS = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V....D hevc_nvenc           NVIDIA NVENC hevc encoder (codec hevc)
 V....D h264_qsv             H.264 / AVC (Intel Quick Sync Video acceleration) (codec h264)
"""


def ffmpeg_falso(funcionan):
    """subprocess.run falso: lista encoders y solo 'funcionan' los indicados."""
    def run(cmd, **kwargs):
        if "-encoders" in cmd:
            return subprocess.CompletedProcess(cmd, 0, LISTA_ENCODERS, "")
        nombre = cmd[cmd.index("-c:v") + 1]
        return subprocess.CompletedProcess(cmd, 0 if nombre in funcionan else 1, b"", b"")
    return run


class Deteccion(unittest.TestCase):
    def setUp(self):
        videos._cache_hw.clear()

    def test_auto_elige_la_primera_que_funciona(self):
        with mock.patch("exportador.videos.subprocess.run", side_effect=ffmpeg_falso({"h264_qsv"})):
            self.assertEqual(videos.detectar_hw(), ["qsv"])   # nvenc listado pero sin GPU
            self.assertEqual(videos.elegir_hw("auto", "h264"), ("qsv", ""))

    def test_pedida_no_disponible_avisa_y_usa_software(self):
        with mock.patch("exportador.videos.subprocess.run", side_effect=ffmpeg_falso(set())):
            familia, aviso = videos.elegir_hw("amf", "h264")
        self.assertIsNone(familia)
        self.assertIn("software", aviso)
        self.assertEqual(videos.elegir_hw("auto", "vp9")[0], None)
        self.assertEqual(videos.elegir_hw("no", "h264"), (None, ""))

    def test_comando_hardware(self):
        op = videos.OpcionesVideos(codec="h265", crf=26)
        cmd = videos.comando_codificacion(Path("a.mov"), Path("b.mp4.part"), op, hw="nvenc")
        self.assertIn("hevc_nvenc", cmd)
        self.assertEqual(cmd[cmd.index("-cq") + 1], "26")
        self.assertNotIn("-crf", cmd)
        self.assertIn("hvc1", cmd)
        self.assertIn("h264_qsv", videos.comando_codificacion(
            Path("a"), Path("b"), videos.OpcionesVideos(), hw="qsv"))

    def test_opciones_de_linea_de_comandos(self):
        args = construir_parser().parse_args(["todo", "x", "--hilos-video", "3", "--hw", "auto"])
        op = opciones_videos(args)
        self.assertEqual((op.hilos, op.hw), (3, "auto"))
        self.assertEqual(opciones_videos(construir_parser().parse_args(["videos", "x"])).hw, "no")


class Procesamiento(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        videos._cache_hw.clear()
        self.origen, self.destino = self.dir / "videos", self.dir / "biblioteca"
        self.origen.mkdir()
        for i in range(4):
            (self.origen / f"VID_2024051{i}_102030.mp4").write_bytes(CONTENIDO + bytes([i]))
        self.comandos = []
        self.simultaneos = self.max_simultaneos = 0
        self.lock = threading.Lock()

    def codificar(self, falla_hw=False):
        def ejecutar(cmd, duracion=0, etiqueta="", video=""):
            with self.lock:
                self.comandos.append(cmd)
                self.simultaneos += 1
                self.max_simultaneos = max(self.max_simultaneos, self.simultaneos)
            time.sleep(0.05)
            with self.lock:
                self.simultaneos -= 1
            if falla_hw and "h264_nvenc" in cmd:
                return False, "No NVENC capable devices found"
            Path(cmd[-1]).write_bytes(b"x" * 100)
            return True, ""
        return ejecutar

    def procesar(self, falla_hw=False, **op):
        with mock.patch("exportador.videos.sondear", return_value=None), \
                mock.patch("exportador.videos.elegir_hw", return_value=("nvenc", "")), \
                mock.patch("exportador.videos.ejecutar_ffmpeg", side_effect=self.codificar(falla_hw)):
            return videos.procesar_videos(self.origen, self.destino, False,
                                          videos.OpcionesVideos(**op))

    def test_en_paralelo(self):
        stats = self.procesar(hilos=3)
        self.assertEqual(stats["procesados"], 4)
        self.assertGreater(self.max_simultaneos, 1)
        self.assertEqual(len([a for a in self.archivos(self.destino) if a.endswith(".mp4")]), 4)

    def test_hardware_y_vuelta_al_software_si_falla(self):
        stats = self.procesar(hw="nvenc", hilos=2)
        self.assertEqual(stats.get("por_hardware"), 4)
        self.comandos.clear()
        for f in self.destino.rglob("*.mp4"):
            f.unlink()
        stats = self.procesar(falla_hw=True, hw="nvenc", hilos=2)
        self.assertEqual((stats["procesados"], stats["errores"], stats.get("hw_fallidos")),
                         (4, 0, 4))
        self.assertEqual(sum("libx264" in c for c in self.comandos), 4)
        self.assertFalse([a for a in self.archivos(self.destino) if a.endswith(".part")])

    def test_origen_intacto_y_segunda_ejecucion_no_recodifica(self):
        antes = {p: p.read_bytes() for p in self.origen.iterdir()}
        self.procesar(hilos=2)
        self.comandos.clear()
        stats = self.procesar(hilos=2)
        self.assertEqual((stats["procesados"], stats["ya_importados"]), (0, 4))
        self.assertEqual(self.comandos, [])
        self.assertEqual({p: p.read_bytes() for p in self.origen.iterdir()}, antes)


if __name__ == "__main__":
    unittest.main()
