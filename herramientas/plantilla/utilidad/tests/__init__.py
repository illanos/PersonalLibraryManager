"""Pruebas de @@titulo@@:  python -m unittest discover -s tests -t .   (en utilidades/@@nombre@@)

Usan el código de src/ de esta misma carpeta aunque no esté instalado.
"""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
