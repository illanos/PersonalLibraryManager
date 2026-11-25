import io
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from notas import adjuntos as adj
from notas.errores import AdjuntoNoValido
from tests.ayudas import HTML, SVG, WEBM, png, wav

try:
    from PIL import Image
except ImportError:
    Image = None

RELLENO = b"\0" * 60


class Identificar(unittest.TestCase):
    def test_por_el_contenido(self):
        casos = [
            (b"\xff\xd8\xff\xe0" + RELLENO, ("imagen", "image/jpeg", ".jpg")),
            (png(), ("imagen", "image/png", ".png")),
            (b"GIF89a" + RELLENO, ("imagen", "image/gif", ".gif")),
            (b"RIFF\x10\0\0\0WEBPVP8 " + RELLENO, ("imagen", "image/webp", ".webp")),
            (b"BM\x10\0\0\0\0\0\0\0" + RELLENO, ("imagen", "image/bmp", ".bmp")),
            (b"\0\0\0\x1cftypavif" + RELLENO, ("imagen", "image/avif", ".avif")),
            (wav(), ("voz", "audio/wav", ".wav")),
            (b"OggS" + RELLENO, ("voz", "audio/ogg", ".ogg")),
            (b"fLaC" + RELLENO, ("voz", "audio/flac", ".flac")),
            (b"ID3\x03" + RELLENO, ("voz", "audio/mpeg", ".mp3")),
            (b"\xff\xfb\x90\x00" + RELLENO, ("voz", "audio/mpeg", ".mp3")),
            (b"\xff\xf1\x50\x80" + RELLENO, ("voz", "audio/aac", ".aac")),
            (b"\0\0\0\x1cftypM4A " + RELLENO, ("voz", "audio/mp4", ".m4a")),
        ]
        for cabecera, esperado in casos:
            with self.subTest(esperado=esperado):
                # El nombre y el tipo declarado no cambian nada
                self.assertEqual(adj.identificar(cabecera, "x.html", "text/html"), esperado)

    def test_opus_de_whatsapp(self):
        self.assertEqual(adj.identificar(b"OggS" + RELLENO, "PTT-20240810-WA0001.opus"),
                         ("voz", "audio/ogg", ".opus"))

    def test_contenedores_de_audio_o_video(self):
        mp4 = b"\0\0\0\x1cftypmp42" + RELLENO
        self.assertEqual(adj.identificar(WEBM, "x", "audio/webm;codecs=opus")[1], "audio/webm")
        self.assertEqual(adj.identificar(mp4, "nota.m4a")[1], "audio/mp4")
        for cabecera in (WEBM, mp4):
            with self.assertRaises(AdjuntoNoValido):
                adj.identificar(cabecera, "pelicula.mkv", "video/webm")

    def test_lo_que_no_se_admite(self):
        for cabecera, nombre, mime in ((HTML, "foto.png", "image/png"), (SVG, "x.svg", "image/svg+xml"),
                                       (b"%PDF-1.7" + RELLENO, "x.pdf", ""), (b"MZ" + RELLENO, "x.mp3", "audio/mpeg"),
                                       (b"a", "", ""), (b"\xff", "", "")):
            with self.subTest(nombre=nombre), self.assertRaises(AdjuntoNoValido):
                adj.identificar(cabecera, nombre, mime)

    def test_heic_dice_que_hacer(self):
        with self.assertRaisesRegex(AdjuntoNoValido, "JPEG"):
            adj.identificar(b"\0\0\0\x18ftypheic" + RELLENO, "IMG_1.HEIC")


class Guardar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def archivos(self):
        return [p for p in self.dir.rglob("*") if p.is_file()]

    def test_copia_tal_cual(self):
        datos = wav(3)
        r = adj.guardar(self.dir, io.BytesIO(datos), "Mi nota.wav", longitud=len(datos))
        self.assertEqual((self.dir / r["archivo"]).read_bytes(), datos)
        self.assertEqual((r["bytes"], r["nombre"]), (len(datos), "Mi nota.wav"))
        self.assertRegex(r["archivo"], r"^adjuntos/\d{4}/\d\d/\d{8}_\d{6}_[0-9a-f]{8}\.wav$")

    def test_lee_solo_los_bytes_anunciados(self):
        datos = png()
        flujo = io.BytesIO(datos + b"lo siguiente")
        r = adj.guardar(self.dir, flujo, longitud=len(datos))
        self.assertEqual(r["bytes"], len(datos))
        self.assertEqual(flujo.read(), b"lo siguiente")

    def test_incompleto_vacio_o_no_valido_no_deja_restos(self):
        datos = wav()
        for flujo, longitud in ((io.BytesIO(datos[:500]), len(datos)), (io.BytesIO(b""), 0),
                                (io.BytesIO(HTML), len(HTML)), (io.BytesIO(datos), adj.MAX_BYTES + 1)):
            with self.assertRaises(AdjuntoNoValido):
                adj.guardar(self.dir, flujo, "x.wav", "audio/wav", longitud)
        self.assertEqual(self.archivos(), [])

    def test_limite_aunque_no_se_anuncie(self):
        with unittest.mock.patch.object(adj, "MAX_BYTES", 1000), self.assertRaises(AdjuntoNoValido):
            adj.guardar(self.dir, io.BytesIO(wav()), "x.wav")
        self.assertEqual(self.archivos(), [])

    def test_nombres(self):
        for nombre, esperado in (("C:\\fotos\\a.png", "a.png"), ("../../a.png", "a.png"),
                                 ('a<b>"c|?*.png', "abc.png"), ("a\r\nb.png", "ab.png"),
                                 ("", "def"), ("..", "def"), ("ñandú 😀.png", "ñandú 😀.png")):
            with self.subTest(nombre=nombre):
                self.assertEqual(adj.limpiar_nombre(nombre, "def"), esperado)
        largo = adj.limpiar_nombre("x" * 300 + ".png", "def")
        self.assertTrue(len(largo) <= 120 and largo.endswith(".png"))

    def test_rutas_fuera_de_la_carpeta(self):
        for relativa in ("../x.png", "notas.sqlite", "adjuntos/../notas.sqlite", "adjuntos"):
            with self.subTest(relativa=relativa), self.assertRaises(AdjuntoNoValido):
                adj.ruta_segura(self.dir, relativa)

    def test_sin_pillow_se_usa_la_original(self):
        with unittest.mock.patch.dict("sys.modules", {"PIL": None}):
            r = adj.guardar(self.dir, io.BytesIO(png()), longitud=len(png()))
            self.assertEqual((r["ancho"], r["alto"]), (None, None))
            self.assertIsNone(adj.miniatura(self.dir, r["archivo"]))

    def _imagen(self, tam, formato="JPEG", **kwargs):
        b = io.BytesIO()
        Image.new(kwargs.pop("modo", "RGB"), tam).save(b, formato, **kwargs)
        return adj.guardar(self.dir, io.BytesIO(b.getvalue()), longitud=len(b.getvalue()))

    @unittest.skipUnless(Image, "necesita Pillow")
    def test_miniatura_girada_segun_exif(self):
        exif = Image.Exif()
        exif[274] = 6
        r = self._imagen((2000, 1000), exif=exif)
        self.assertEqual((r["ancho"], r["alto"]), (1000, 2000))
        mini = adj.miniatura(self.dir, r["archivo"])
        with Image.open(mini) as im:
            self.assertEqual(im.size, (360, 720))
        self.assertEqual(adj.miniatura(self.dir, r["archivo"]), mini)        # ya hecha
        adj.borrar_archivos(self.dir, [r["archivo"]])
        self.assertEqual(self.archivos(), [])

    @unittest.skipUnless(Image, "necesita Pillow")
    def test_sin_miniatura_si_es_pequena_o_animada(self):
        self.assertIsNone(adj.miniatura(self.dir, self._imagen((300, 200))["archivo"]))
        animada = self._imagen((900, 900), "GIF", modo="P", save_all=True,
                               append_images=[Image.new("P", (900, 900), 5)])
        self.assertIsNone(adj.miniatura(self.dir, animada["archivo"]))

    @unittest.skipUnless(Image, "necesita Pillow")
    def test_miniatura_con_transparencia_y_paleta(self):
        for modo in ("RGBA", "LA", "P", "L", "1", "I;16"):
            with self.subTest(modo=modo):
                self.assertIsNotNone(adj.miniatura(
                    self.dir, self._imagen((900, 800), "PNG", modo=modo)["archivo"]))

    @unittest.skipUnless(Image, "necesita Pillow")
    def test_imagen_danada_no_rompe_nada(self):
        datos = b"\xff\xd8\xff\xe0" + b"basura" * 50
        r = adj.guardar(self.dir, io.BytesIO(datos), longitud=len(datos))
        self.assertIsNone(adj.miniatura(self.dir, r["archivo"]))


if __name__ == "__main__":
    unittest.main()
