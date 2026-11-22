"""Prueba de humo: crea una foto de ejemplo, la organiza y genera la galería."""
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw

BASE = Path(__file__).parent
PRUEBA = BASE / "_prueba"
PRUEBA.mkdir(exist_ok=True)

# 1. Foto de ejemplo grande (sin EXIF: usará la fecha de modificación)
im = Image.new("RGB", (3000, 2000), (120, 80, 200))
ImageDraw.Draw(im).ellipse((900, 500, 2100, 1500), fill=(255, 200, 60))
im.save(PRUEBA / "foto_ejemplo.jpg", quality=95)
print("Foto de prueba creada (3000x2000)")

# 2. Organizar fotos de verdad
r = subprocess.run([sys.executable, "main.py", "fotos", str(PRUEBA)],
                   capture_output=True, text=True, cwd=BASE)
print("--- main.py fotos ---")
print(r.stdout, r.stderr)
assert r.returncode == 0, "fotos devolvió error"

# 3. Galería sobre el resultado
destino = BASE / "_prueba_organizados"
r = subprocess.run([sys.executable, "main.py", "galeria", str(destino)],
                   capture_output=True, text=True, cwd=BASE)
print("--- main.py galeria ---")
print(r.stdout, r.stderr)
assert r.returncode == 0, "galeria devolvió error"
assert (destino / "galeria.html").exists(), "falta galeria.html"
assert (destino / "galeria.json").exists(), "falta galeria.json"

print("\nTodo OK: organización y galería funcionan.")
