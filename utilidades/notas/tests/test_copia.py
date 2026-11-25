import json
import unittest
import unittest.mock
import zipfile

from notas.copia import crear_copia
from notas.cuaderno import Cuaderno
from notas.errores import ErrorNotas
from tests.ayudas import CasoConCuaderno, png, wav


class Copia(CasoConCuaderno):
    def test_se_puede_restaurar_entera(self):
        n = self.c.crear("A", "texto", "menta", True, ["Casa"])
        self.adjuntar(n, png(), "a.png")
        self.adjuntar(n, wav(), "b.wav", duracion=1)
        borrada = self.c.crear("B")
        self.adjuntar(borrada, wav())
        self.c.lote([borrada["id"]], "papelera")
        ruta = crear_copia(self.c)
        self.assertEqual(ruta.parent, self.carpeta / "copias")

        with zipfile.ZipFile(ruta) as z:
            self.assertIsNone(z.testzip())
            z.extractall(self.dir / "restaurada")
        otra = Cuaderno(self.dir / "restaurada", crear=False)
        self.assertEqual(otra.nota(n["id"]), self.c.nota(n["id"]))
        for a in self.c.nota(n["id"])["adjuntos"] + self.c.nota(borrada["id"])["adjuntos"]:
            self.assertEqual(otra.adjunto(a["id"])["ruta"].read_bytes(),
                             self.c.adjunto(a["id"])["ruta"].read_bytes())
        legible = json.loads((self.dir / "restaurada" / "notas.json").read_text(encoding="utf-8"))
        self.assertEqual([x["titulo"] for x in legible], ["A", "B"])

    def test_un_adjunto_perdido_no_impide_la_copia(self):
        a = self.adjuntar(self.c.crear("A"), png())
        (self.carpeta / a["archivo"]).unlink()
        with zipfile.ZipFile(crear_copia(self.c)) as z:
            self.assertNotIn(a["archivo"], z.namelist())

    def test_a_una_carpeta_y_sin_pisar(self):
        destino = self.dir / "copias mías"
        destino.mkdir()
        ruta = crear_copia(self.c, destino)
        self.assertEqual(ruta.parent, destino)
        with self.assertRaises(ErrorNotas):
            crear_copia(self.c, ruta)

    def test_si_falla_no_deja_restos(self):
        with unittest.mock.patch("notas.copia.zipfile.ZipFile", side_effect=OSError("disco lleno")):
            with self.assertRaises(OSError):
                crear_copia(self.c)
        self.assertEqual(list((self.carpeta / "copias").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
