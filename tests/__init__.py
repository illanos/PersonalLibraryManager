"""Pruebas del exportador:  python -m unittest discover -s tests -t .

Usan el código de src/ de este mismo proyecto aunque no esté instalado (o haya otra
copia instalada en modo editable desde otra carpeta).
"""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
