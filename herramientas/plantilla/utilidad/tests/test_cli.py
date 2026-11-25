import contextlib
import io
import unittest

from @@nombre@@.cli import main


class LineaDeComandos(unittest.TestCase):
    def salida(self, *args) -> str:
        with contextlib.redirect_stdout(io.StringIO()) as consola:
            main(list(args))
        return consola.getvalue()

    def test_estado(self):
        self.assertIn("todo en orden", self.salida("estado"))

    def test_sin_comando_ensena_la_ayuda(self):
        self.assertIn("estado", self.salida())


if __name__ == "__main__":
    unittest.main()
