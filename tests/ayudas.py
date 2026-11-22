"""Utilidades para crear fotos de prueba con metadatos."""

import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageCms

XMP_PRUEBA = b'''<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:tiff="http://ns.adobe.com/tiff/1.0/"
 xmlns:mwg-rs="http://www.metadataworkinggroup.com/schemas/regions/"
 xmp:Rating="4" tiff:Orientation="6">
<dc:subject><rdf:Bag><rdf:li>playa</rdf:li><rdf:li>vacaciones</rdf:li></rdf:Bag></dc:subject>
<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Atardecer</rdf:li></rdf:Alt></dc:title>
<mwg-rs:Regions><rdf:Description><mwg-rs:RegionList><rdf:Bag>
<rdf:li><rdf:Description mwg-rs:Name="Ana" mwg-rs:Type="Face"/></rdf:li>
</rdf:Bag></mwg-rs:RegionList></rdf:Description></mwg-rs:Regions>
</rdf:Description></rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>'''


def segmento_iptc(palabras_clave) -> bytes:
    """Segmento APP13 con palabras clave IPTC (2:25)."""
    datos = b"".join(b"\x1c\x02\x19" + struct.pack(">H", len(k)) + k for k in palabras_clave)
    irb = b"8BIM" + struct.pack(">H", 0x0404) + b"\x00\x00" + struct.pack(">I", len(datos)) + datos
    if len(datos) % 2:
        irb += b"\x00"
    cuerpo = b"Photoshop 3.0\x00" + irb
    return b"\xff\xed" + struct.pack(">H", len(cuerpo) + 2) + cuerpo


def crear_foto(ruta: Path, tam=(400, 300), color=(200, 120, 60), fecha="2023:08:15 20:31:07",
               orientacion=None, completa=False, **kwargs_guardado):
    """JPEG de prueba. Con `completa`, lleva EXIF, GPS, XMP, IPTC, ICC y comentario."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", tam, color)
    im.paste((255 - color[0], 30, 30), (0, 0, tam[0] // 4, tam[1] // 4))   # marca esquina
    exif = Image.Exif()
    exif[271], exif[272] = "Apple", "iPhone 13"
    if orientacion:
        exif[274] = orientacion
    if fecha:
        exif.get_ifd(0x8769)[36867] = fecha
    kwargs = {"quality": 95, "exif": exif}
    if completa:
        exif[0x9C9E] = "familia;cumple".encode("utf-16-le") + b"\x00\x00"
        exif.get_ifd(0x8769)[42036] = "iPhone 13 front camera 2.71mm f/2.2"
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2], gps[3], gps[4] = "N", (36.0, 31.0, 48.0), "W", (6.0, 17.0, 31.0)
        kwargs.update(
            icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes(),
            xmp=XMP_PRUEBA, comment="comentario", extra=segmento_iptc([b"Cadiz", b"verano"]))
    kwargs.update(kwargs_guardado)
    im.save(ruta, **kwargs)
    return ruta


class CasoConCarpeta(unittest.TestCase):
    """Test con carpeta temporal `self.dir` y salida de consola silenciada."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._silencio = contextlib.redirect_stdout(io.StringIO())
        self.consola = self._silencio.__enter__()

    def tearDown(self):
        self._silencio.__exit__(None, None, None)
        self._tmp.cleanup()

    def archivos(self, carpeta: Path) -> list:
        return sorted(p.relative_to(carpeta).as_posix() for p in carpeta.rglob("*") if p.is_file())
