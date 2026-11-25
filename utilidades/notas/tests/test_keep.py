import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path

from notas import keep
from notas.cuaderno import ARCHIVO_BD, ESQUEMA, VERSION_BD, Cuaderno
from notas.errores import ErrorNotas
from tests.ayudas import CasoConCuaderno, png, wav

try:
    from PIL import Image
except ImportError:
    Image = None

CREADA = 1_500_000_000_000_000                   # microsegundos: 14/07/2017 02:40 UTC
AMR = b"#!AMR\n" + b"\0" * 200


def jpeg(ancho, alto, giro=None) -> bytes:
    im = Image.effect_noise((ancho, alto), 80).convert("RGB")
    exif = Image.Exif()
    exif[0x0110] = "Cámara"
    exif.get_ifd(keep.IFD_EXIF).update({36867: "2017:07:14 02:40:00", keep.MAKER_NOTE: b"x" * 5000})
    if giro:
        exif[274] = giro
    b = io.BytesIO()
    im.save(b, "JPEG", quality=95, exif=exif.tobytes())
    return b.getvalue()


class CasoKeep(CasoConCuaderno):
    """Un Takeout inventado en self.keep."""

    def setUp(self):
        super().setUp()
        self.takeout = self.dir / "Takeout"
        self.keep = self.takeout / "Conservar"
        self.keep.mkdir(parents=True)
        self.n = 0

    def nota(self, archivo=None, **campos):
        self.n += 1
        datos = {"color": "DEFAULT", "isTrashed": False, "isPinned": False, "isArchived": False, "title": "",
                 "textContent": "", "createdTimestampUsec": CREADA + self.n,
                 "userEditedTimestampUsec": CREADA + self.n, **campos}
        datos = {k: v for k, v in datos.items() if v is not None}
        (self.keep / (archivo or f"{self.n}.json")).write_text(json.dumps(datos), encoding="utf-8")

    def archivo(self, nombre, datos):
        (self.keep / nombre).write_bytes(datos)
        return {"filePath": nombre, "mimetype": "image/png"}

    def importar(self, **opciones) -> keep.Resumen:
        return keep.importar(self.carpeta, keep.leer(self.takeout), **opciones)

    def unica(self, vista="todas") -> dict:
        notas = self.c.listar(vista)
        self.assertEqual(len(notas), 1)
        return notas[0]


class Leer(CasoKeep):
    def test_no_hay_notas(self):
        (self.keep / "otra.json").write_text('{"title": "una foto"}', encoding="utf-8")
        for carpeta, mensaje in ((self.takeout, "No hay notas"), (self.dir / "no", "No existe"),
                                 (self.dir / "t.zip", "Descomprime")):
            with self.subTest(carpeta=carpeta.name), self.assertRaisesRegex(ErrorNotas, mensaje):
                keep.leer(carpeta)

    def test_un_json_roto_no_para_lo_demas(self):
        self.nota(title="bien")
        (self.keep / "rota.json").write_text("{", encoding="utf-8")
        r = self.importar()
        self.assertEqual(r.importadas, 1)
        self.assertIn("rota.json", r.avisos[0])

    def test_momento_del_nombre(self):
        self.assertEqual(keep.momento_adjunto("15d3ef71800.abc123.jpg"),
                         datetime.fromtimestamp(0x15d3ef71800 / 1000, timezone.utc))
        self.assertEqual(keep.momento_adjunto("1500000000000.123.jpg"),
                         datetime.fromtimestamp(1_500_000_000, timezone.utc))
        for nombre in ("1Q948sP_GrOtZ.png", "c00a0100-718b-4c41.png", "00000000000.abc.jpg"):
            self.assertIsNone(keep.momento_adjunto(nombre))


class Importar(CasoKeep):
    def test_todo_lo_de_una_nota(self):
        self.nota("Compra.json", title="Compra\nsemanal", textContent="línea 1\nlínea 2\n", color="CERULEAN", isPinned=True,
                  userEditedTimestampUsec=CREADA + 5_000_000, labels=[{"name": "Casa"}, {"name": " Recetas  nuevas "}],
                  annotations=[{"url": "https://e.org/a", "title": "Página", "description": "Algo", "source": "WEBLINK"},
                               {"url": "https://e.org/a", "title": "Repetida"}, {"url": "javascript:x", "title": "no"}],
                  sharees=[{"email": "ana@e.org", "isOwner": True}, {"email": "luis@e.org", "isOwner": False}],
                  tasks=[{"id": "x"}])
        self.importar()
        n = self.unica()
        self.assertEqual((n["titulo"], n["texto"], n["color"]), ("Compra semanal", "línea 1\nlínea 2", "cielo"))
        self.assertEqual((n["fijada"], n["archivada"], n["papelera"]), (True, False, None))
        self.assertEqual((n["creada"], n["modificada"]),
                         ("2017-07-14T02:40:00.000+00:00", "2017-07-14T02:40:05.000+00:00"))
        self.assertEqual([c["nombre"] for c in n["categorias"]], ["Casa", "Recetas nuevas"])
        self.assertEqual(n["detalles"], {
            "fuente": "Google Keep", "archivo": "Compra.json", "color": "CERULEAN", "recordatorio": True,
            "enlaces": [{"url": "https://e.org/a", "titulo": "Página", "descripcion": "Algo"}],
            "compartida": ["ana@e.org", "luis@e.org"], "propietario": "ana@e.org"})

    def test_las_listas_son_casillas(self):
        self.nota(textContent=None, listContent=[
            {"text": "Pan", "isChecked": False}, {"text": "", "isChecked": False},
            {"text": "Leche\nentera", "isChecked": True}])
        self.nota(title="texto", textContent="normal")
        r = self.importar()
        self.assertEqual((r.importadas, r.tipos["lista"]), (2, 1))
        lista, = self.c.listar("todas", tipo="lista")
        self.assertEqual(lista["texto"], "☐ Pan\n☑ Leche\n   entera")
        self.assertEqual(self.c.estado()["totales"]["lista"], 1)

    def test_archivadas_papelera_y_vacias(self):
        self.nota(title="A", isArchived=True, isPinned=True)
        self.nota(title="B", isTrashed=True)
        self.nota(title=" ", textContent="\n")
        r = self.importar()
        self.assertEqual((r.importadas, r.vacias), (2, 1))
        self.assertEqual(self.titulos(vista="archivadas"), ["A"])
        self.assertFalse(self.c.listar("archivadas")[0]["fijada"])
        self.assertEqual(self.titulos(vista="papelera"), ["B"])

    def test_repetir_no_duplica_ni_pisa(self):
        self.nota(title="A")
        self.assertEqual(self.importar().importadas, 1)
        self.c.editar(self.unica()["id"], titulo="cambiada")
        self.nota(title="B")
        r = self.importar()
        self.assertEqual((r.importadas, r.repetidas), (1, 1))
        self.assertEqual(sorted(self.titulos()), ["B", "cambiada"])

    def test_simular_no_toca_nada(self):
        self.nota(title="A", labels=[{"name": "Casa"}])
        self.carpeta = self.dir / "otro"
        self.assertEqual(self.importar(simular=True).importadas, 1)
        self.assertFalse(self.carpeta.exists())

    def test_etiquetas_sin_notas(self):
        self.nota(title="A", labels=[{"name": "Trabajo"}])
        (self.keep / "Labels.txt").write_text("trabajo\nPersonal\n\n", encoding="utf-8")
        self.importar()
        self.assertEqual([(c["nombre"], c["total"]) for c in self.c.categorias()], [("Personal", 0), ("Trabajo", 1)])

    def test_fechas_al_reves(self):
        self.nota(title="A", userEditedTimestampUsec=CREADA - 10**9)
        self.importar()
        n = self.unica()
        self.assertEqual(n["creada"], n["modificada"])

    def test_se_busca_en_los_enlaces_y_al_editar_sigue(self):
        self.nota(title="A", annotations=[{"url": "https://e.org", "title": "Árboles", "description": ""}])
        self.importar()
        self.assertEqual(self.titulos(buscar="arboles"), ["A"])
        self.c.editar(self.unica()["id"], texto="otra cosa")
        self.assertEqual(self.titulos(buscar="arboles otra"), ["A"])

    def test_titulo_larguisimo_no_se_pierde(self):
        self.nota(title="t" * 600, textContent="x")
        self.importar()
        n = self.unica()
        self.assertEqual((len(n["titulo"]), n["texto"]), (500, "t" * 600 + "\nx"))


class Adjuntos(CasoKeep):
    def test_imagenes_con_su_fecha(self):
        a = self.archivo("15d3ef71800.abc123.png", png())
        self.nota(title="A", attachments=[a])
        original = (self.keep / a["filePath"]).read_bytes()
        self.importar()
        adjunto, = self.unica()["adjuntos"]
        fecha = datetime.fromtimestamp(0x15d3ef71800 / 1000)
        self.assertEqual(adjunto["nombre"], f"Imagen {fecha:%Y-%m-%d %H.%M.%S}.png")
        self.assertTrue(adjunto["archivo"].startswith(f"adjuntos/{fecha:%Y/%m/%Y%m%d_%H%M%S}_"))
        self.assertEqual((self.keep / a["filePath"]).read_bytes(), original)      # el Takeout no se toca

    def test_la_fecha_de_la_nota_no_cambia(self):
        self.nota(title="A", attachments=[self.archivo("15d3ef71800.abc123.png", png())])
        self.importar()
        self.assertEqual(self.unica()["modificada"], "2017-07-14T02:40:00.000+00:00")

    def test_otra_extension_y_los_que_faltan(self):
        self.archivo("a1.png", png())
        self.nota("x.json", attachments=[{"filePath": "a1.jpeg"}, {"filePath": "no.jpg"}])
        r = self.importar()
        n = self.unica()
        self.assertEqual(len(n["adjuntos"]), 1)
        self.assertEqual(n["detalles"]["faltan"], ["no.jpg"])
        self.assertIn("no.jpg", r.avisos[0])

    def test_una_imagen_danada_no_deja_fuera_la_nota(self):
        self.nota(title="A", attachments=[self.archivo("a1.jpg", b"basura" * 30), self.archivo("a2.png", png())])
        r = self.importar()
        n = self.unica()
        self.assertEqual((len(n["adjuntos"]), n["detalles"]["faltan"]), (1, ["a1.jpg"]))
        self.assertIn("a1.jpg", r.avisos[0])

    def test_si_no_se_puede_guardar_no_quedan_restos(self):
        self.nota(title="A", attachments=[self.archivo("a1.png", png())])
        with unittest.mock.patch.object(Cuaderno, "_poner_categorias", side_effect=OSError("disco")):
            with self.assertRaises(OSError):
                self.importar()
        self.assertEqual((self.en_disco(), self.c.listar("todas")), ([], []))
        self.assertEqual(self.importar().importadas, 1)

    def test_el_original_de_un_dibujo_va_con_su_nota(self):
        self.archivo("15d3ef73f10.abc123.png", png())               # segundos antes de crearla
        self.nota(title="otra")
        self.nota(title="dibujada", attachments=[self.archivo("c00a0100-718b.png", png())])
        self.importar()
        n = next(n for n in self.c.listar() if n["titulo"] == "dibujada")
        self.assertEqual([a["nombre"].split(" 2")[0] for a in n["adjuntos"]], ["Dibujo", "Original sin dibujar"])

    def test_un_archivo_de_nadie_no_se_pierde(self):
        self.archivo("16000000000.abc123.png", png())
        self.nota(title="A")
        self.assertEqual(self.importar().importadas, 2)
        suelta, = self.c.listar("archivadas")
        self.assertEqual(len(suelta["adjuntos"]), 1)
        self.assertEqual(self.importar().repetidas, 2)

    def test_dos_de_la_misma_hora_no_se_llaman_igual(self):
        self.nota(attachments=[self.archivo("15d3ef71800.abc1.png", png()), self.archivo("15d3ef71800.abc2.png", png())])
        self.importar()
        nombres = [a["nombre"] for a in self.unica()["adjuntos"]]
        self.assertEqual(len(set(nombres)), 2)

    def test_audio_que_ya_vale(self):
        self.nota(attachments=[self.archivo("15d3ef71800.abc1.wav", wav())])
        self.importar()
        self.assertEqual(self.unica()["adjuntos"][0]["mime"], "audio/wav")

    def test_sin_ffmpeg_la_nota_de_voz_espera(self):
        self.nota("voz.json", title="voz", attachments=[self.archivo("15d3ef71800.abc1.3gp", AMR)])
        self.nota(title="otra")
        with unittest.mock.patch("notas.keep.shutil.which", return_value=None):
            r = self.importar()
        self.assertEqual(self.titulos(), ["otra"])
        self.assertIn("ffmpeg", r.avisos[0])
        with unittest.mock.patch("notas.keep.shutil.which", return_value="ffmpeg"), \
                unittest.mock.patch("notas.keep.convertir_audio", return_value=(wav(), ".wav", 2.5)):
            self.assertEqual(self.importar().importadas, 1)
        voz = next(n for n in self.c.listar() if n["titulo"] == "voz")
        self.assertEqual(voz["adjuntos"][0]["duracion"], 2.5)


@unittest.skipUnless(Image, "necesita Pillow")
class Imagenes(CasoKeep):
    def reducir(self, datos, **opciones):
        ruta = self.dir / "imagen"
        ruta.write_bytes(datos)
        reducida = keep.reducir_imagen(ruta, **opciones)
        return reducida, Image.open(io.BytesIO(reducida))

    def test_se_reduce_se_gira_y_conserva_la_fecha(self):
        original = jpeg(900, 600, giro=6)
        datos, im = self.reducir(original, lado=450)
        self.assertEqual((im.format, im.size), ("JPEG", (300, 450)))
        self.assertLess(len(datos), len(original) / 2)
        exif = im.getexif()
        self.assertIsNone(exif.get(274))
        self.assertEqual(exif.get_ifd(keep.IFD_EXIF).get(36867), "2017:07:14 02:40:00")
        self.assertNotIn(keep.MAKER_NOTE, exif.get_ifd(keep.IFD_EXIF))

    def test_si_ya_ocupa_poco_se_queda_como_esta(self):
        self.assertEqual(self.reducir(png(40, 30))[0], png(40, 30))

    def test_lo_transparente_sigue_siendolo(self):
        b = io.BytesIO()
        im = Image.effect_noise((600, 600), 90).convert("RGBA")
        im.putalpha(128)
        im.save(b, "PNG")
        _, reducida = self.reducir(b.getvalue(), lado=200)
        self.assertEqual((reducida.format, reducida.mode, reducida.size), ("PNG", "RGBA", (200, 200)))

    def test_lado_cero_no_cambia_nada(self):
        original = jpeg(900, 600)
        self.nota(attachments=[self.archivo("15d3ef71800.abc1.jpg", original)])
        self.importar(lado=0)
        self.assertEqual(self.unica()["adjuntos"][0]["bytes"], len(original))


class Migracion(unittest.TestCase):
    def test_un_cuaderno_de_la_version_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.closing(sqlite3.connect(Path(tmp) / ARCHIVO_BD)) as db:
                db.executescript(ESQUEMA + "INSERT INTO notas (titulo, texto, busqueda, creada, modificada) VALUES "
                                 "('vieja', 'x', 'vieja\nx', '2026-01-01', '2026-01-01'); PRAGMA user_version = 1;")
            for _ in range(2):                       # abrirlo otra vez no vuelve a migrar
                c = Cuaderno(tmp)
            n, = c.listar()
            self.assertEqual((n["titulo"], n["detalles"]), ("vieja", {}))
            c.importar("keep:1", "nueva")
            with self.assertRaisesRegex(ErrorNotas, "ya está importada"):
                c.importar("keep:1", "otra vez")
            self.assertEqual(c.importadas(), {"keep:1"})
            with contextlib.closing(sqlite3.connect(Path(tmp) / ARCHIVO_BD)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], VERSION_BD)


if __name__ == "__main__":
    unittest.main()
