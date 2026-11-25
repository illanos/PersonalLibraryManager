"""Pruebas de Notas:  python -m unittest discover -s tests -t .   (en utilidades/notas)

Usan el código de src/ de esta misma carpeta aunque no esté instalado (o haya otra copia
instalada en modo editable desde otro sitio).
"""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
