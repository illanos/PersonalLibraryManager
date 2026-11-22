"""Descargas únicas de datos opcionales (ciudades, modelos de caras).

Todo se guarda en la carpeta `datos/` junto al programa, solo se descarga cuando se
pide explícitamente (--descargar-lugares, --descargar-modelos-caras) y después todo
funciona sin conexión.
"""

import os
import urllib.request
from pathlib import Path

CARPETA_DATOS = Path(__file__).with_name("datos")
AGENTE = "Exportador (descarga de datos para uso local)"


def descargar(url: str, destino: Path, timeout: int = 120) -> Path:
    """Descarga `url` en `destino` de forma atómica (primero a .part)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".part")
    print(f"  descargando {url} …")
    peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as resp, open(tmp, "wb") as f:
            while bloque := resp.read(1024 * 256):
                f.write(bloque)
        os.replace(tmp, destino)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    print(f"  guardado en {destino} ({destino.stat().st_size / 1e6:.1f} MB)")
    return destino
