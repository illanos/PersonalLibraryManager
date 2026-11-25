"""Utilidades de las pruebas: cuaderno temporal y archivos de ejemplo."""

import contextlib
import io
import struct
import tempfile
import unittest
import wave
import zlib
from pathlib import Path

from notas.cuaderno import Cuaderno


def png(ancho=4, alto=3) -> bytes:
    """PNG válido sin necesidad de Pillow."""
    def trozo(tipo, datos):
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos)))
    filas = b"".join(b"\0" + b"\x40\x80\xc0" * ancho for _ in range(alto))
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0))
            + trozo(b"IDAT", zlib.compress(filas)) + trozo(b"IEND", b""))


def wav(segundos=1.0) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * int(8000 * segundos))
    return b.getvalue()


WEBM = b"\x1a\x45\xdf\xa3" + b"\0" * 200
HTML = b"<!doctype html><script>alert(1)</script>" + b" " * 100
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>' + b" " * 100


class CasoConCuaderno(unittest.TestCase):
    """Test con un cuaderno temporal en `self.c` y la salida de consola en `self.consola`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.carpeta = self.dir / "cuaderno"
        self.c = Cuaderno(self.carpeta)
        self._silencio = contextlib.redirect_stdout(io.StringIO())
        self.consola = self._silencio.__enter__()

    def tearDown(self):
        self._silencio.__exit__(None, None, None)
        self._tmp.cleanup()

    def adjuntar(self, nota, datos, nombre="", mime="", duracion=None):
        return self.c.adjuntar(nota["id"], io.BytesIO(datos), nombre, mime, duracion, len(datos))

    def en_disco(self) -> list:
        """Archivos de adjuntos que hay de verdad en la carpeta."""
        raiz = self.carpeta / "adjuntos"
        return sorted(p.relative_to(self.carpeta).as_posix() for p in raiz.rglob("*") if p.is_file())

    def titulos(self, **filtros) -> list:
        return [n["titulo"] for n in self.c.listar(**filtros)]
