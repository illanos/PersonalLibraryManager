"""Descargas únicas de datos opcionales (ciudades, modelos de caras).

Todo se guarda en la carpeta de datos (ver `carpeta_datos`), solo se descarga cuando se
pide explícitamente (--descargar-lugares, --descargar-modelos-caras) y después todo
funciona sin conexión.
"""

import os
import urllib.request
from pathlib import Path

VARIABLE_DATOS = "EXPORTADOR_DATOS"


def carpeta_datos() -> Path:
    """Dónde se guardan las descargas y las preferencias del panel.

    1. La variable de entorno EXPORTADOR_DATOS, si está definida.
    2. `datos/` en la raíz del proyecto, si se ejecuta desde él (src/exportador).
    3. Si el paquete está instalado en otro sitio, una carpeta del usuario:
       %LOCALAPPDATA%\\exportador en Windows, ~/.local/share/exportador en los demás.
    """
    if os.environ.get(VARIABLE_DATOS):
        return Path(os.environ[VARIABLE_DATOS]).expanduser()
    raiz = Path(__file__).resolve().parents[2]
    if (raiz / "pyproject.toml").is_file() and (raiz / "src" / "exportador").is_dir():
        return raiz / "datos"
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "exportador"


CARPETA_DATOS = carpeta_datos()
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
