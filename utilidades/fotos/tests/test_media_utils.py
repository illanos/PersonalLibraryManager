import unittest
from datetime import datetime, timezone

from exportador.media_utils import (fecha_desde_nombre, listar_archivos, nombre_libre,
                         parsear_fecha_iso, subcarpeta_fecha)
from tests.ayudas import CasoConCarpeta


class FechaDesdeNombre(unittest.TestCase):
    def test_patrones_habituales(self):
        casos = {
            "IMG_20240512_102030": datetime(2024, 5, 12, 10, 20, 30),
            "VID-20240512-102030": datetime(2024, 5, 12, 10, 20, 30),
            "PXL_20240512_102030123": datetime(2024, 5, 12, 10, 20, 30),
            "Screenshot_2024-05-12-10-20-30": datetime(2024, 5, 12, 10, 20, 30),
            "Screenshot 2024-05-12 at 10.20.30": datetime(2024, 5, 12, 10, 20, 30),
            "2024-05-12 10.20.30": datetime(2024, 5, 12, 10, 20, 30),
            "IMG-20240512-WA0001": datetime(2024, 5, 12),
        }
        for nombre, esperada in casos.items():
            with self.subTest(nombre=nombre):
                self.assertEqual(fecha_desde_nombre(nombre), esperada)

    def test_sin_fecha_o_imposible(self):
        for nombre in ("IMG_1234", "DSC00042", "foto_20241399", "19700101_000000", "30000101"):
            with self.subTest(nombre=nombre):
                self.assertIsNone(fecha_desde_nombre(nombre))


class FechaIso(unittest.TestCase):
    def test_utc_pasa_a_hora_local(self):
        esperada = datetime(2024, 5, 12, 10, 20, 30, tzinfo=timezone.utc).astimezone()
        self.assertEqual(parsear_fecha_iso("2024-05-12T10:20:30.000000Z"),
                         esperada.replace(tzinfo=None))

    def test_con_zona_conserva_la_hora_de_reloj(self):
        self.assertEqual(parsear_fecha_iso("2024-05-12T10:20:30+0200"),
                         datetime(2024, 5, 12, 10, 20, 30))

    def test_fechas_a_cero_se_descartan(self):
        self.assertIsNone(parsear_fecha_iso("1904-01-01T00:00:00Z"))
        self.assertIsNone(parsear_fecha_iso("no es una fecha"))


class Nombres(CasoConCarpeta):
    def test_nombre_libre_respeta_existentes_y_reservados(self):
        (self.dir / "a.jpg").write_bytes(b"x")
        reservados = set()
        self.assertEqual(nombre_libre(self.dir, "a", ".jpg", reservados).name, "a_01.jpg")
        self.assertEqual(nombre_libre(self.dir, "a", ".jpg", reservados).name, "a_02.jpg")

    def test_subcarpeta(self):
        self.assertEqual(subcarpeta_fecha(datetime(2024, 5, 1)), "2024/05-Mayo")

    def test_listar_excluye_internas_y_basura_de_macos(self):
        for rel in ("a.jpg", "sub/b.JPG", "._a.jpg", "originales/c.jpg", ".exportador/d.jpg",
                    "_galeria/thumbs/e.jpg", ".oculta/f.jpg", "notas.txt"):
            ruta = self.dir / rel
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(b"x")
        encontrados = [p.relative_to(self.dir).as_posix()
                       for p in listar_archivos(self.dir, {".jpg"})]
        self.assertEqual(encontrados, ["a.jpg", "sub/b.JPG"])


if __name__ == "__main__":
    unittest.main()
