"""Fusionar colecciones: por días, la copia de más calidad, papelera, vídeos y CLI."""

import json
import os
import shutil
import sqlite3
import subprocess
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest import mock

from PIL import Image

import fusionar
import galeria
from catalogo import ruta_catalogo
from fotos import OpcionesFotos, procesar_fotos
from fusionar import Elemento, OpcionesFusion, comparar, planificar
from limpieza import Limpieza
from videos import filtro_escala, sondear
from main import construir_parser, main
from tests.ayudas import CasoConCarpeta
from tests.test_similares import escena


def huella(carpeta: Path) -> dict:
    return {p.relative_to(carpeta).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in carpeta.rglob("*") if p.is_file()}


def copia(origen: Path, destino: Path, tam=None, calidad=80, exif=True):
    """Otra copia de la misma foto: reducida y recomprimida, con o sin su EXIF."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(origen) as im:
        datos = im.getexif() if exif else None
        nueva = im.resize(tam) if tam else im.copy()
    kwargs = {"quality": calidad}
    if datos:
        kwargs["exif"] = datos
    nueva.save(destino, **kwargs)
    return destino


def filas_catalogo(biblioteca: Path, tabla: str = "archivos") -> list:
    with closing(sqlite3.connect(ruta_catalogo(biblioteca))) as db:
        db.row_factory = sqlite3.Row
        return [dict(f) for f in db.execute(f"SELECT * FROM {tabla}")]


def foto(src, lado="b", ancho=1000, alto=750, bytes_=100_000, **extra):
    e = Elemento(lado, "foto", Path(src), src, fecha=datetime(2024, 5, 12, 10), ancho=ancho,
                 alto=alto, bytes=bytes_)
    for k, v in extra.items():
        setattr(e, k, v)
    return e


class Calidad(unittest.TestCase):
    def test_resolucion_y_luego_exif_whatsapp_y_peso(self):
        self.assertEqual(comparar(foto("a", ancho=2000, alto=1500), foto("b")),
                         (1, "más resolución"))
        self.assertEqual(comparar(foto("a", ancho=1010), foto("b"))[0], 0)   # ±5 %: igual
        self.assertEqual(comparar(foto("a", camara=True), foto("b")), (1, "tiene EXIF de cámara"))
        self.assertEqual(comparar(foto("a", whatsapp=True), foto("b")),
                         (-1, "no viene de WhatsApp"))
        self.assertEqual(comparar(foto("a", bytes_=150_000), foto("b")),
                         (1, "más peso (menos comprimida)"))
        self.assertEqual(comparar(foto("a", bytes_=105_000), foto("b")),
                         (0, "copias equivalentes"))

    def test_lo_que_se_reduce_al_anadir_cuenta_reducido(self):
        grande = foto("a", lado="c", ancho=4000, alto=3000, bytes_=9_000_000, convertir=True)
        en_biblioteca = foto("b", ancho=3200, alto=2400)
        self.assertEqual(comparar(grande, en_biblioteca, max_lado=3200), (0, "copias equivalentes"))
        self.assertEqual(comparar(grande, en_biblioteca, max_lado=0)[1], "más resolución")

    def test_videos_resolucion_whatsapp_bitrate(self):
        def video(src, ancho=1920, alto=1080, bytes_=10_000_000, duracion=10.0, **extra):
            e = foto(src, ancho=ancho, alto=alto, bytes_=bytes_, **extra)
            e.tipo, e.duracion = "video", duracion
            return e
        self.assertEqual(comparar(video("a"), video("b", 1280, 720))[1], "más resolución")
        self.assertEqual(comparar(video("a"), video("b", whatsapp=True)),
                         (1, "no viene de WhatsApp"))
        self.assertEqual(comparar(video("a", bytes_=30_000_000), video("b")),
                         (1, "más bitrate (menos comprimido)"))
        # Un 4K de la colección se exporta a 1920 px: cuenta ya reducido
        cuatro_k = video("a", 3840, 2160, lado="c", convertir=True)
        self.assertEqual(comparar(cuatro_k, video("b"))[0], 0)
        self.assertEqual(comparar(cuatro_k, video("b"), max_lado_video=0)[1], "más resolución")


class Plan(unittest.TestCase):
    """Decisiones sin archivos: por días, ráfagas, mismo original y copias en la colección."""

    def test_por_dias_y_otra_toma(self):
        bib = [foto("bib.jpg", dhash="f0" * 16, fuente="exif")]
        mismo_dia = foto("c1.jpg", "c", ancho=600, alto=450, dhash="f0" * 15 + "f1",
                         fuente="exif")
        otro_dia = foto("c2.jpg", "c", dhash="f0" * 16, fecha=datetime(2024, 5, 20, 10))
        rafaga = foto("c3.jpg", "c", dhash="f0" * 16, fuente="exif",
                      fecha=datetime(2024, 5, 12, 10, 0, 4))
        planificar([mismo_dia, otro_dia, rafaga], bib)
        self.assertEqual((mismo_dia.accion, mismo_dia.pareja.rel), ("ya_esta", "bib.jpg"))
        self.assertEqual(otro_dia.accion, "anadir")
        self.assertEqual(rafaga.accion, "anadir")
        self.assertEqual(rafaga.parecida[1], 0)   # muy parecida, pero es otra toma

    def test_mismo_original_por_nombre_y_hora_aunque_el_hash_difiera(self):
        # Cada biblioteca redujo y recomprimió el original a su manera: 10 bits
        bib = [foto("bib.jpg", dhash="f0" * 16, fuente="exif", nombre_original="img_20240512_100000")]
        c = foto("c.jpg", "c", ancho=600, alto=450, dhash="0f" + "f0" * 14 + "f3",
                 fuente="exif", nombre_original="img_20240512_100000")
        planificar([c], bib)
        self.assertEqual((c.accion, c.como), ("ya_esta", "mismo original (nombre y hora)"))
        # Mismo nombre pero otra foto (más de 12 bits) u otra hora: no
        otra = foto("d.jpg", "c", dhash="0f" * 16, fuente="exif",
                    nombre_original="img_20240512_100000")
        planificar([otra], bib)
        self.assertEqual(otra.accion, "anadir")

    def test_un_segundo_de_diferencia_en_el_exif_es_otra_toma(self):
        bib = [foto("bib.jpg", dhash="f0" * 16, fuente="exif")]
        c = foto("c.jpg", "c", dhash="f0" * 15 + "f1", fuente="exif",
                 fecha=datetime(2024, 5, 12, 10, 0, 1))
        planificar([c], bib)
        self.assertEqual((c.accion, c.parecida[1]), ("anadir", 1))

    def test_margen_de_dias(self):
        bib = [foto("bib.jpg", dhash="f0" * 16)]
        manana = foto("c.jpg", "c", ancho=600, alto=450, dhash="f0" * 16,
                      fecha=datetime(2024, 5, 13, 0, 30))
        planificar([manana], bib, opciones=OpcionesFusion(margen_dias=0))
        self.assertEqual(manana.accion, "anadir")
        manana.accion = ""
        planificar([manana], bib, opciones=OpcionesFusion(margen_dias=1))
        self.assertEqual(manana.accion, "ya_esta")

    def test_mismo_original_aunque_no_se_parezca_el_hash(self):
        bib = [foto("bib.jpg", hash_original="abc", fecha=datetime(2020, 1, 1))]
        c = foto("c.jpg", "c", ancho=2000, alto=1500, hash_original="abc")
        planificar([c], bib)
        self.assertEqual((c.accion, c.sustituye.rel, c.como), ("sustituir", "bib.jpg",
                                                               "mismo original"))

    def test_de_varias_copias_en_la_coleccion_entra_la_mejor(self):
        peor = foto("peor.jpg", "c", ancho=800, alto=600, dhash="0f" * 16)
        mejor = foto("mejor.jpg", "c", ancho=1600, alto=1200, dhash="0f" * 16)
        en_bib = foto("bib.jpg", ancho=1000, alto=750, dhash="0f" * 16)
        planificar([peor, mejor], [en_bib])
        self.assertEqual((mejor.accion, mejor.sustituye), ("sustituir", en_bib))
        self.assertEqual((peor.accion, peor.pareja), ("repetida", mejor))

    def test_igual_a_una_quitada_a_mano(self):
        quitada = foto("x.jpg", "p", dhash="3c" * 16)
        c = foto("c.jpg", "c", dhash="3c" * 16)
        planificar([c], [], papelera=[quitada])
        self.assertEqual(c.accion, "quitada")
        d = foto("d.jpg", "c", dhash="00" * 16, hash_original="h1")
        planificar([d], [], descartadas={"h1"})
        self.assertEqual(d.accion, "quitada")


class ConArchivos(CasoConCarpeta):
    """Casos que se confirman abriendo las fotos (vistos en bibliotecas reales)."""

    def elemento(self, ruta, lado, **extra):
        from similares import dhash
        with Image.open(ruta) as im:
            ancho, alto = im.size
        e = Elemento(lado, "foto", ruta, ruta.name, fecha=datetime(2008, 9, 15, 9, 34, 49),
                     fuente="exif", ancho=ancho, alto=alto, bytes=ruta.stat().st_size,
                     dhash=dhash(ruta))
        for k, v in extra.items():
            setattr(e, k, v)
        return e

    def test_mismo_original_girado_y_con_el_1_de_takeout(self):
        self.assertEqual(fusionar.normalizar_nombre("DSCN0169(1)"), "dscn0169")
        grande = escena(self.dir / "bib" / "a.jpg", 1, tam=(1600, 1200))
        (self.dir / "col").mkdir()
        with Image.open(grande) as im:
            im.resize((800, 600)).rotate(90, expand=True).save(self.dir / "col" / "a.jpg")
        bib = [self.elemento(grande, "b", nombre_original="dscn0169")]
        c = self.elemento(self.dir / "col" / "a.jpg", "c",
                          nombre_original=fusionar.normalizar_nombre("DSCN0169(1)"))
        planificar([c], bib)
        self.assertEqual(c.accion, "ya_esta")
        self.assertIn("girada", c.como)
        # Girada pero otra hora: no es la misma
        c2 = self.elemento(self.dir / "col" / "a.jpg", "c", nombre_original="dscn0169",
                           fecha=datetime(2008, 9, 15, 9, 34, 50))
        planificar([c2], bib)
        self.assertEqual(c2.accion, "anadir")

    def test_hashes_guardados_dudosos_se_confirman_con_los_archivos(self):
        foto_bib = escena(self.dir / "bib" / "b.jpg", 2)
        foto_col = copia(foto_bib, self.dir / "col" / "b.jpg", (900, 675))
        e = self.elemento(foto_bib, "b")
        c = self.elemento(foto_col, "c", fuente="google")
        c.dhash = f"{int(e.dhash, 16) ^ 0xFF:032x}"   # guardado de otro origen: 8 bits
        planificar([c], [e])
        self.assertEqual(c.accion, "ya_esta")
        self.assertIn("bit", c.como)


class Fotos(CasoConCarpeta):
    """Biblioteca importada de un móvil y otra colección (p. ej. Google Fotos) con:
    una copia peor, una mejor, una nueva, la misma escena otro día, otra toma de una
    ráfaga, una de WhatsApp y dos copias de la misma foto nueva."""

    def setUp(self):
        super().setUp()
        movil, self.bib, self.col = self.dir / "movil", self.dir / "bib", self.dir / "google"
        a = escena(movil / "a.jpg", 1, fecha="2024:05:12 10:00:00")
        b_grande = escena(self.col / "b_grande.jpg", 2, tam=(1600, 1200),
                          fecha="2024:05:12 11:00:00")
        copia(b_grande, movil / "b.jpg", (800, 600))
        procesar_fotos(movil, self.bib, False, OpcionesFotos(hilos=2))
        galeria.generar_galeria(self.bib)

        copia(a, self.col / "copia_a.jpg", (800, 600))                     # peor: ya está
        escena(self.col / "nueva.jpg", 3, fecha="2024:05:12 12:00:00")       # nueva
        escena(self.col / "otro_dia.jpg", 1, fecha="2024:06:20 10:00:00")   # mismo dibujo, otro día
        escena(self.col / "rafaga.jpg", 1, fecha="2024:05:12 10:00:05")     # otra toma
        wa = escena(self.dir / "tmp" / "wa.jpg", 4)
        copia(wa, self.col / "WhatsApp Images" / "IMG-20240512-WA0001.jpg", (640, 480), exif=False)
        dup = escena(self.col / "dup1.jpg", 5, tam=(1000, 750), fecha="2024:05:13 09:00:00")
        copia(dup, self.col / "dup2.jpg", (600, 450))
        self.src_a = "2024/05-Mayo/20240512_100000.jpg"
        self.src_b = "2024/05-Mayo/20240512_110000.jpg"
        (self.bib / "_galeria" / "favoritos.json").write_text(json.dumps([self.src_b]),
                                                               encoding="utf-8")
        self.huella_col = huella(self.col)

    def tearDown(self):
        self.assertEqual(huella(self.col), self.huella_col)   # la colección nunca se toca
        super().tearDown()

    def fusionar(self, simular=False, **opciones):
        return fusionar.fusionar(self.col, self.bib, simular, OpcionesFusion(hilos=2, **opciones))

    def test_fusion(self):
        with Image.open(self.bib / self.src_b) as im:
            self.assertEqual(im.size, (800, 600))
        stats = self.fusionar()
        self.assertEqual((stats["anadidas"], stats["sustituidas"], stats["ya_estaban"],
                          stats["repetidas"], stats["errores"]), (5, 1, 1, 1, 0))
        self.assertEqual(stats["parecidas"], 1)   # la ráfaga
        archivos = set(self.archivos(self.bib))
        self.assertIn(self.src_a, archivos)
        # La mejor ocupa el sitio (y el nombre) de la peor, que va a la papelera
        with Image.open(self.bib / self.src_b) as im:
            self.assertEqual(im.size, (1600, 1200))
        self.assertIn(".exportador/papelera/2024/05-Mayo/20240512_110000_sustituida.jpg", archivos)
        self.assertIn("WhatsApp/2024/05-Mayo/20240512_WA0001.jpg", archivos)   # WhatsApp aparte
        self.assertIn("2024/06-Junio/20240620_100000.jpg", archivos)
        self.assertIn("2024/05-Mayo/20240512_100005.jpg", archivos)            # la ráfaga
        self.assertIn("2024/05-Mayo/20240512_120000.jpg", archivos)
        self.assertIn("2024/05-Mayo/20240513_090000.jpg", archivos)            # solo dup1
        self.assertNotIn("2024/05-Mayo/20240513_090000_01.jpg", archivos)
        with Image.open(self.bib / "2024/05-Mayo/20240513_090000.jpg") as im:
            self.assertEqual(im.size, (1000, 750))
        # Copiadas tal cual, sin recomprimir
        self.assertEqual((self.bib / "2024/05-Mayo/20240512_120000.jpg").read_bytes(),
                         (self.col / "nueva.jpg").read_bytes())
        # Galería al día, sin la sustituida; el favorito sigue (mismo nombre)
        datos = json.loads((self.bib / "galeria.json").read_text(encoding="utf-8"))
        srcs = {e["src"] for e in datos["elementos"]}
        self.assertEqual(len(srcs), 7)
        self.assertNotIn("2024/05-Mayo/20240512_110000_sustituida.jpg", srcs)
        self.assertEqual(json.loads((self.bib / "_galeria" / "favoritos.json").read_text(
            encoding="utf-8")), [self.src_b])
        # Catálogo: lo nuevo, con su origen; lo descartado, para no volver a compararlo
        origenes = {Path(f["origen"]).name for f in filas_catalogo(self.bib)}
        self.assertTrue({"nueva.jpg", "b_grande.jpg", "dup1.jpg"} <= origenes)
        descartes = {Path(f["origen"]).name: f for f in filas_catalogo(self.bib, "descartes")}
        self.assertEqual(descartes["copia_a.jpg"]["referencia"], self.src_a)
        self.assertEqual(descartes["dup2.jpg"]["referencia"], "2024/05-Mayo/20240513_090000.jpg")

    def test_simular_no_toca_nada_y_da_el_mismo_plan(self):
        antes = huella(self.bib)
        stats = self.fusionar(simular=True)
        self.assertEqual(huella(self.bib), antes)
        self.assertEqual((stats["anadidas"], stats["sustituidas"], stats["ya_estaban"],
                          stats["repetidas"]), (5, 1, 1, 1))
        salida = self.consola.getvalue()
        self.assertIn("SUSTITUIR", salida)
        informe = [l for l in salida.splitlines() if l.startswith("Informe CSV")][-1]
        ruta = Path(informe.split(":", 1)[1].strip())
        try:
            self.assertIn("SUSTITUYE", ruta.read_text(encoding="utf-8-sig"))
        finally:
            ruta.unlink()

    def test_segunda_vez_no_repite_nada(self):
        self.fusionar()
        antes = huella(self.bib)
        stats = self.fusionar()
        self.assertEqual((stats["anadidas"], stats["sustituidas"]), (0, 0))
        self.assertEqual((stats["ya_fusionadas"], stats["ya_comparadas"]), (6, 2))

        def sin_catalogo(h):   # abrir el catálogo cambia su fecha; los informes son nuevos
            return {k: v for k, v in h.items() if not k.startswith(".exportador/")}
        self.assertEqual(sin_catalogo(huella(self.bib)), sin_catalogo(antes))

    def test_la_sustituida_se_restaura_y_la_peor_no_se_reimporta(self):
        self.fusionar()
        limpieza = Limpieza(self.bib)
        papelera = limpieza.contenido_papelera()["fotos"]
        self.assertEqual([f["src"] for f in papelera], ["2024/05-Mayo/20240512_110000_sustituida.jpg"])
        restauradas = limpieza.restaurar()["restauradas"]
        self.assertEqual(restauradas, ["2024/05-Mayo/20240512_110000_sustituida.jpg"])
        with Image.open(self.bib / restauradas[0]) as im:
            self.assertEqual(im.size, (800, 600))
        with Image.open(self.bib / self.src_b) as im:
            self.assertEqual(im.size, (1600, 1200))

    def test_lo_quitado_antes_a_mano_no_vuelve(self):
        datos = json.loads((self.bib / "galeria.json").read_text(encoding="utf-8"))
        elemento = next(e for e in datos["elementos"] if e["src"] == self.src_a)
        Limpieza(self.bib).mover_a_papelera(self.src_a, "prueba", elemento)
        self.fusionar()
        archivos = set(self.archivos(self.bib))
        # copia_a (peor) y la ráfaga se parecen a la quitada: la copia no vuelve, la ráfaga sí
        self.assertNotIn(self.src_a, archivos)
        self.assertNotIn("2024/05-Mayo/20240512_100000_01.jpg", archivos)
        self.assertIn("2024/05-Mayo/20240512_100005.jpg", archivos)
        self.assertIn("QUITADA", self.consola.getvalue())

    def test_sin_espacio_no_copia_nada(self):
        antes = huella(self.bib)
        poco = mock.Mock(free=fusionar.MARGEN_DISCO + 10_000)
        with mock.patch("fusionar.shutil.disk_usage", return_value=poco):
            stats = self.fusionar(simular=True)
            self.assertIn("No hay espacio suficiente", stats["aviso_espacio"])
            self.assertIn("AVISO: No hay espacio", self.consola.getvalue())
            with self.assertRaisesRegex(fusionar.EspacioInsuficiente, "No se ha copiado nada"):
                self.fusionar()
            with self.assertRaises(SystemExit) as salida:
                main(["fusionar", str(self.col), "--destino", str(self.bib)])
            self.assertIn("No hay espacio suficiente", str(salida.exception))
        self.assertEqual({k: v for k, v in huella(self.bib).items() if not k.startswith(".exportador/")},
                         {k: v for k, v in antes.items() if not k.startswith(".exportador/")})
        # Con espacio de sobra, no avisa
        stats = self.fusionar(simular=True)
        self.assertNotIn("aviso_espacio", stats)
        self.assertGreater(stats["espacio_necesario"], 0)

    def test_umbral_cero_solo_copias_casi_exactas(self):
        stats = self.fusionar(simular=True, umbral=0)
        self.assertGreaterEqual(stats["anadidas"], 5)

    def test_foto_grande_o_en_otro_formato_se_convierte(self):
        escena(self.col / "enorme.jpg", 6, tam=(4000, 3000), fecha="2024:07:01 10:00:00")
        otra = escena(self.dir / "tmp" / "escaner.jpg", 7)
        with Image.open(otra) as im:
            im.save(self.col / "escaner.tif")
        os.utime(self.col / "escaner.tif", (datetime(2024, 7, 2, 9).timestamp(),) * 2)
        self.huella_col = huella(self.col)
        self.fusionar()
        with Image.open(self.bib / "2024/07-Julio/20240701_100000.jpg") as im:
            self.assertEqual(max(im.size), 3200)
        convertida = [p for p in self.archivos(self.bib) if p.startswith("2024/07-Julio/20240702")]
        self.assertEqual(len(convertida), 1)
        self.assertTrue(convertida[0].endswith(".jpg"))


class Videos(CasoConCarpeta):
    """Vídeos con ffprobe y los fotogramas simulados."""

    INFO = {   # nombre -> (ancho, alto, duración, firma de los fotogramas)
        "20240512_100000.mp4": (1280, 720, 10.0, "a"),
        "mejor.mp4": (1920, 1080, 10.3, "a"),
        "peor.mp4": (640, 360, 10.0, "a"),
        "otro.mp4": (1280, 720, 10.0, "b"),
        "largo.mp4": (1280, 720, 30.0, "a"),
        "viejo.avi": (640, 480, 5.0, "c"),
        "enorme.mp4": (3840, 2160, 8.0, "d"),
    }
    FIRMAS = {"a": "f0e1d2c3b4a5968778695a4b3c2d1e0f", "b": "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
              "c": "33cc33cc55aa55aa33cc33cc55aa55aa", "d": "5a5a5a5aa5a5a5a5f00ff00f0ff00ff0"}

    def setUp(self):
        super().setUp()
        self.bib, self.col = self.dir / "bib", self.dir / "col"
        self.video(self.bib / "2024/05-Mayo/20240512_100000.mp4", 5_000_000)
        for nombre, tam in (("mejor.mp4", 20_000_000), ("peor.mp4", 2_000_000),
                            ("otro.mp4", 5_000_001), ("largo.mp4", 15_000_000),
                            ("viejo.avi", 3_000_000)):
            self.video(self.col / nombre, tam)

    def video(self, ruta: Path, tam: int):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(ruta.name.encode() * (tam // len(ruta.name.encode())))
        marca = datetime(2024, 5, 12, 10).timestamp()
        os.utime(ruta, (marca, marca))

    def sondear(self, ruta):
        ancho, alto, duracion, _ = self.INFO[ruta.name]
        return {"fecha": datetime(2024, 5, 12, 10), "ancho": ancho, "alto": alto,
                "duracion": duracion, "camara": "Pixel", "gps": None, "rotacion": 0, "codec": "h264"}

    def fotograma(self, ruta, instante):
        nombre = ruta.name.replace("_sustituida", "")
        return self.FIRMAS[self.INFO[nombre][3]]

    @staticmethod
    def codificar(cmd, duracion=0, etiqueta=""):
        Path(cmd[-1]).write_bytes(b"mp4 convertido")
        return True, ""

    def test_fusion_de_videos(self):
        with mock.patch("fusionar.shutil.which", return_value="ffmpeg"), \
                mock.patch("fusionar.sondear", side_effect=self.sondear), \
                mock.patch("fusionar.hash_fotograma", side_effect=self.fotograma), \
                mock.patch("fusionar.ejecutar_ffmpeg", side_effect=self.codificar):
            stats = fusionar.fusionar(self.col, self.bib, False, OpcionesFusion(hilos=2))
        self.assertEqual((stats["sustituidas"], stats["repetidas"], stats["anadidas"],
                          stats["errores"]), (1, 1, 3, 0))
        archivos = set(self.archivos(self.bib))
        # mejor.mp4 sustituye a la de la biblioteca (mismo nombre); peor.mp4 no entra
        self.assertEqual((self.bib / "2024/05-Mayo/20240512_100000.mp4").stat().st_size,
                         (self.col / "mejor.mp4").stat().st_size)
        self.assertIn(".exportador/papelera/2024/05-Mayo/20240512_100000_sustituida.mp4", archivos)
        # otro (otros fotogramas) y largo (otra duración) se añaden; el .avi se convierte
        nuevos = [p for p in archivos if p.startswith("2024/05-Mayo/") and "100000.mp4" not in p]
        self.assertEqual(len(nuevos), 3, nuevos)
        convertido = [p for p in nuevos if (self.bib / p).read_bytes() == b"mp4 convertido"]
        self.assertEqual(len(convertido), 1)
        # La papelera también restaura vídeos
        restauradas = Limpieza(self.bib).restaurar()["restauradas"]
        self.assertEqual(restauradas, ["2024/05-Mayo/20240512_100000_sustituida.mp4"])

    def test_lo_que_pasa_del_limite_se_exporta_y_los_metadatos_van_sin_recodificar(self):
        self.video(self.col / "enorme.mp4", 30_000_000)
        comandos = []

        def codificar(cmd, duracion=0, etiqueta=""):
            comandos.append(cmd)
            return self.codificar(cmd)

        def sondear(ruta):   # la peor trae ubicación y álbum; las demás, no
            info = self.sondear(ruta)
            if ruta.name == "peor.mp4":
                info.update(gps=[40.4168, -3.7038], etiquetas=["Viaje"])
            return info

        with mock.patch("fusionar.shutil.which", return_value="ffmpeg"),                 mock.patch("fusionar.sondear", side_effect=sondear),                 mock.patch("fusionar.hash_fotograma", side_effect=self.fotograma),                 mock.patch("fusionar.ejecutar_ffmpeg", side_effect=codificar),                 mock.patch("fusion_metadatos.ejecutar_ffmpeg", side_effect=codificar):
            stats = fusionar.fusionar(self.col, self.bib, False, OpcionesFusion(hilos=2))
        self.assertEqual((stats["sustituidas"], stats["anadidas"], stats["convertidas"],
                          stats["metadatos"], stats["errores"]), (1, 4, 2, 1, 0))
        por_entrada = {Path(c[c.index("-i") + 1]).name: c for c in comandos}
        # El 4K se recodifica al límite de la exportación (1920), como al importar
        self.assertIn(filtro_escala(1920), por_entrada["enorme.mp4"])
        # La mejor entra tal cual (remux, sin recodificar) con lo que sabía la peor
        remux = por_entrada["mejor.mp4"]
        self.assertIn("copy", remux)
        self.assertIn("location=+40.4168-003.7038/", remux)
        self.assertIn("keywords=Viaje", remux)
        self.assertIn("sus metadatos completan la que se queda: ubicación, 1 etiqueta",
                      self.consola.getvalue())

    def test_sin_ffmpeg_se_omiten_los_videos(self):
        with mock.patch("fusionar.shutil.which", return_value=None):
            stats = fusionar.fusionar(self.col, self.bib, True)
        self.assertEqual((stats["omitidos"], stats["anadidas"]), (5, 0))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requiere FFmpeg")
class VideosReales(CasoConCarpeta):
    """Con FFmpeg de verdad: el mismo vídeo a dos resoluciones es el mismo; otro no."""

    def generar(self, ruta: Path, fuente: str, tam: str, metadatos=()):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                        "-i", f"{fuente}=size={tam}:rate=25", "-t", "4", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-metadata", "creation_time=2024-05-12T10:00:00Z",
                        *metadatos, "-movflags", "+use_metadata_tags",
                        str(ruta)], check=True, capture_output=True, stdin=subprocess.DEVNULL)

    def test_fotogramas(self):
        bib, col = self.dir / "bib", self.dir / "col"
        self.generar(bib / "2024/05-Mayo/20240512_120000.mp4", "testsrc2", "640x360")
        self.generar(col / "grande.mp4", "testsrc2", "1280x720")
        self.generar(col / "otro.mp4", "smptebars", "640x360")
        stats = fusionar.fusionar(col, bib, True, OpcionesFusion(hilos=2))
        self.assertEqual((stats["sustituidas"], stats["anadidas"]), (1, 1))

    def test_la_de_la_biblioteca_gana_los_metadatos_sin_recodificar(self):
        bib, col = self.dir / "bib", self.dir / "col"
        video = bib / "2024/05-Mayo/20240512_120000.mp4"
        self.generar(video, "testsrc2", "1280x720")
        self.generar(col / "pequeno.mp4", "testsrc2", "640x360", [
            "-metadata", "location=+40.4168-003.7038/", "-metadata", "keywords=Viaje, Ana",
            "-metadata", "description=En la playa"])
        antes = sondear(video)
        stats = fusionar.fusionar(col, bib, False, OpcionesFusion(hilos=2))
        self.assertEqual((stats["ya_estaban"], stats["metadatos"], stats["errores"]), (1, 1, 0))
        despues = sondear(video)
        self.assertEqual((despues["gps"], despues["etiquetas"], despues["descripcion"]),
                         ([40.4168, -3.7038], ["Viaje", "Ana"], "En la playa"))
        self.assertEqual((despues["ancho"], despues["codec"], despues["fecha"]),
                         (1280, antes["codec"], antes["fecha"]))


class LineaDeComandos(CasoConCarpeta):
    def test_opciones(self):
        args = construir_parser().parse_args(["fusionar", "g", "--destino", "b", "--umbral", "3",
                                              "--margen-dias", "0", "--simular"])
        self.assertEqual((args.umbral, args.margen_dias, args.simular), (3, 0, True))
        self.assertEqual((args.max_lado_video, args.sin_metadatos), (1920, False))
        args = construir_parser().parse_args(["fusionar", "g", "--destino", "b",
                                              "--max-lado-video", "0", "--sin-metadatos"])
        self.assertEqual((args.max_lado_video, args.sin_metadatos), (0, True))
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            construir_parser().parse_args(["fusionar", "g"])              # falta --destino
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            construir_parser().parse_args(["fusionar", "g", "--destino", "b", "--umbral", "20"])

    def test_carpetas_anidadas_o_inexistentes(self):
        (self.dir / "bib" / "google").mkdir(parents=True)
        for coleccion, destino in (("bib/google", "bib"), ("bib", "bib/google"), ("bib", "bib"),
                                   ("no_existe", "bib"), ("bib/google", "no_existe")):
            with self.subTest(coleccion=coleccion, destino=destino), self.assertRaises(SystemExit):
                main(["fusionar", str(self.dir / coleccion), "--destino", str(self.dir / destino)])

    def test_simular_desde_la_linea_de_comandos(self):
        escena(self.dir / "col" / "a.jpg", 1, fecha="2024:05:12 10:00:00")
        (self.dir / "bib").mkdir()
        main(["fusionar", str(self.dir / "col"), "--destino", str(self.dir / "bib"), "--simular"])
        self.assertEqual(list((self.dir / "bib").iterdir()), [])
        self.assertIn("AÑADIR", self.consola.getvalue())


if __name__ == "__main__":
    unittest.main()
