"""Mejora 6: notas de voz y audio."""

import json
import os
import unittest
from datetime import datetime
from unittest import mock

import audio
import galeria
from main import main
from tests.ayudas import CasoConCarpeta

OGG = b"OggS\x00\x02" + b"\x00" * 20 + b"opus-falso" * 50
MP3 = b"ID3\x03\x00" + b"\x00" * 20 + b"mp3-falso" * 50


def poner_mtime(ruta, fecha):
    os.utime(ruta, (fecha.timestamp(), fecha.timestamp()))


class Importacion(CasoConCarpeta):
    def setUp(self):
        super().setUp()
        self.origen, self.bib = self.dir / "movil", self.dir / "bib"
        notas = self.origen / "WhatsApp" / "Media" / "WhatsApp Voice Notes" / "202501"
        notas.mkdir(parents=True)
        self.nota = notas / "PTT-20250114-WA0003.opus"
        self.nota.write_bytes(OGG)
        poner_mtime(self.nota, datetime(2025, 1, 14, 21, 5, 9))
        (self.origen / "Musica").mkdir()
        self.mp3 = self.origen / "Musica" / "cancion.mp3"
        self.mp3.write_bytes(MP3)
        poner_mtime(self.mp3, datetime(2023, 3, 4, 5, 6, 7))
        self.sin_ffprobe = mock.patch("audio.hay_ffprobe", return_value=False)
        self.sin_ffprobe.start()
        self.addCleanup(self.sin_ffprobe.stop)

    def test_copia_tal_cual_por_fecha_y_whatsapp_aparte(self):
        antes = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.origen.rglob("*")
                 if p.is_file()}
        stats = audio.procesar_audio(self.origen, self.bib, False)
        self.assertEqual(stats["procesados"], 2)
        nota = self.bib / "WhatsApp/Audio/2025/01-Enero/20250114_210509.opus"
        cancion = self.bib / "Audio/2023/03-Marzo/20230304_050607.mp3"
        self.assertEqual(nota.read_bytes(), OGG)          # sin recomprimir
        self.assertEqual(cancion.read_bytes(), MP3)
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in self.origen.rglob("*") if p.is_file()}, antes)

    def test_segunda_ejecucion_no_reprocesa(self):
        audio.procesar_audio(self.origen, self.bib, False)
        with mock.patch("audio.hash_archivo", side_effect=AssertionError("relee")):
            stats = audio.procesar_audio(self.origen, self.bib, False)
        self.assertEqual((stats["procesados"], stats["ya_importados"]), (0, 2))

    def test_audio_vacio_es_danado(self):
        (self.origen / "Musica" / "roto.m4a").write_bytes(b"")
        stats = audio.procesar_audio(self.origen, self.bib, False)
        self.assertEqual(stats["danados"], 1)

    def test_galeria_tipo_audio(self):
        audio.procesar_audio(self.origen, self.bib, False)
        galeria.generar_galeria(self.bib)
        datos = json.loads((self.bib / "galeria.json").read_text(encoding="utf-8"))
        por = {e["src"]: e for e in datos["elementos"]}
        nota = por["WhatsApp/Audio/2025/01-Enero/20250114_210509.opus"]
        self.assertEqual((nota["tipo"], nota["ambito"], nota["thumb"]), ("audio", "whatsapp", ""))
        self.assertEqual(nota["fecha"], "2025-01-14T21:05:09")
        self.assertNotIn("ambito", por["Audio/2023/03-Marzo/20230304_050607.mp3"])

    def test_todo_incluye_audio_salvo_sin_audio(self):
        main(["todo", str(self.origen), "--destino", str(self.bib), "--sin-audio", "--sin-galeria"])
        self.assertFalse([a for a in self.archivos(self.bib) if a.endswith((".opus", ".mp3"))])
        main(["todo", str(self.origen), "--destino", str(self.bib), "--sin-galeria"])
        self.assertEqual(len([a for a in self.archivos(self.bib)
                              if a.endswith((".opus", ".mp3"))]), 2)


if __name__ == "__main__":
    unittest.main()
