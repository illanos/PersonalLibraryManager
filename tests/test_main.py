import unittest
import unittest.mock
from pathlib import Path

from main import construir_parser, main
from tests.ayudas import CasoConCarpeta, crear_foto


class LineaDeComandos(unittest.TestCase):
    def test_opciones(self):
        p = construir_parser()
        args = p.parse_args(["todo", "x", "--formato", "webp", "--codec", "h265",
                             "--max-lado", "2048", "--max-lado-video", "1280"])
        self.assertEqual((args.formato, args.codec), ("webp", "h265"))
        self.assertEqual((args.max_lado_fotos, args.max_lado_video), (2048, 1280))

    def test_videos_admite_max_lado_como_antes(self):
        args = construir_parser().parse_args(["videos", "x", "--max-lado", "2560"])
        self.assertEqual(args.max_lado_video, 2560)

    def test_originales_solo_si_se_piden(self):
        from main import opciones_fotos, opciones_videos
        p = construir_parser()
        for comando in ("fotos", "videos", "todo"):
            self.assertFalse(p.parse_args([comando, "x"]).con_originales)
        args = p.parse_args(["todo", "x", "--con-originales"])
        self.assertTrue(opciones_fotos(args).conservar_originales)
        self.assertTrue(opciones_videos(args).conservar_originales)
        args = p.parse_args(["fotos", "x", "--sin-originales"])   # opción antigua, aceptada
        self.assertFalse(opciones_fotos(args).conservar_originales)

    def test_calidad_fuera_de_rango(self):
        with self.assertRaises(SystemExit), unittest.mock.patch("sys.stderr"):
            construir_parser().parse_args(["fotos", "x", "--calidad", "150"])


class Ejecucion(CasoConCarpeta):
    def test_todo_en_simulacion_no_crea_destino(self):
        crear_foto(self.dir / "movil" / "a.jpg")
        main(["todo", str(self.dir / "movil"), "--simular"])
        self.assertFalse(Path(str(self.dir / "movil") + "_organizados").exists())

    def test_destino_dentro_del_origen(self):
        (self.dir / "movil").mkdir()
        with self.assertRaises(SystemExit):
            main(["fotos", str(self.dir / "movil"), "--destino", str(self.dir / "movil" / "x")])


if __name__ == "__main__":
    unittest.main()
