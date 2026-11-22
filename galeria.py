"""Galería web local: índice de la biblioteca, miniaturas y página HTML.

Crea en la carpeta indicada:
    - galeria.html          interfaz (línea de tiempo, buscador, favoritos, visor)
    - galeria.json          índice de fotos y vídeos con sus metadatos
    - _galeria/thumbs/      miniaturas para carga rápida
    - _galeria/favoritos.json  (al marcar favoritos con el servidor de la galería)

La regeneración es incremental: los archivos que no han cambiado reutilizan sus
metadatos y su miniatura, así que volver a generarla tras importar es rápido.

Para verla:  python main.py galeria <carpeta> --servir
"""

import hashlib
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from catalogo import originales_por_destino
from media_utils import CARPETA_GALERIA, fecha_desde_nombre, fecha_mtime, listar_archivos

EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
EXTENSIONES_VIDEO = {".mp4", ".webm", ".mov", ".m4v"}

VERSION_INDICE = 2
MINIATURA_ALTO = 400           # las filas de la galería miden ~200 px (x2 en pantallas HiDPI)
MINIATURA_ANCHO_MAX = 1200     # panorámicas
PLANTILLA = Path(__file__).with_name("galeria_plantilla.html")


# ----------------------------- Miniaturas -----------------------------

def _clave(rel: str) -> str:
    """Nombre de miniatura único por ruta (foto.jpg y foto.mp4 no chocan)."""
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:20]


def _miniatura_foto(ruta: Path, destino: Path):
    from PIL import Image, ImageOps
    with Image.open(ruta) as im:
        caja = (MINIATURA_ANCHO_MAX, MINIATURA_ALTO)
        if im.getexif().get(274) in (5, 6, 7, 8):   # se girará: caja traspuesta
            caja = caja[::-1]
        im.thumbnail(caja, Image.Resampling.LANCZOS)   # en JPEG decodifica ya reducido
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "PA", "P"):
            rgba = im.convert("RGBA")
            im = Image.new("RGB", im.size, (40, 40, 42))
            im.paste(rgba, mask=rgba.getchannel("A"))
        elif im.mode != "RGB":
            im = im.convert("RGB")
        tmp = destino.with_name(destino.stem + ".tmp.jpg")
        im.save(tmp, "JPEG", quality=78, optimize=True)
    os.replace(tmp, destino)


def _miniatura_video(ruta: Path, destino: Path, duracion: float):
    """Fotograma representativo (al 25 % o a los 3 s); en vídeos muy cortos, el primero."""
    tmp = destino.with_name(destino.stem + ".tmp.jpg")
    instantes = [min(3.0, duracion * 0.25) if duracion else 3.0, 0.0]
    for instante in dict.fromkeys(instantes):
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-ss", f"{instante:.2f}",
               "-i", str(ruta), "-frames:v", "1", "-vf", f"scale=-2:{MINIATURA_ALTO}",
               "-q:v", "4", "-loglevel", "error", str(tmp)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            break
        if tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, destino)
            return
    tmp.unlink(missing_ok=True)


# ----------------------------- Índice -----------------------------

def _metadatos_foto(ruta: Path) -> dict:
    from fotos import leer_metadatos
    try:
        datos = leer_metadatos(ruta)
    except Exception:
        fecha = fecha_desde_nombre(ruta.stem) or fecha_mtime(ruta)
        return {"fecha": fecha, "ancho": 0, "alto": 0}
    return {"fecha": datos["fecha"], "ancho": datos["ancho"], "alto": datos["alto"],
            "camara": datos["camara"], "gps": datos["gps"]}


def _metadatos_video(ruta: Path, hay_ffmpeg: bool) -> dict:
    from videos import fecha_video, sondear
    info = (sondear(ruta) if hay_ffmpeg else None) or {}
    fecha, _ = fecha_video(ruta, info)
    return {"fecha": fecha, "ancho": info.get("ancho", 0), "alto": info.get("alto", 0),
            "duracion": round(info.get("duracion", 0), 1)}


def _cargar_indice_previo(carpeta: Path) -> dict:
    try:
        datos = json.loads((carpeta / "galeria.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(datos, dict) or datos.get("version") != VERSION_INDICE:
        return {}
    return {e["src"]: e for e in datos.get("elementos", [])
            if isinstance(e, dict) and "src" in e}


def _elemento(ruta: Path, carpeta: Path, previos: dict, hay_ffmpeg: bool):
    """(elemento, reutilizado). Reutiliza metadatos y miniatura si el archivo no cambió."""
    rel = ruta.relative_to(carpeta).as_posix()
    st = ruta.stat()
    tipo = "foto" if ruta.suffix.lower() in EXTENSIONES_FOTO else "video"
    thumb_rel = f"{CARPETA_GALERIA}/thumbs/{_clave(rel)}.jpg"
    thumb = carpeta / thumb_rel

    previo = previos.get(rel)
    reutilizado = bool(previo and previo.get("bytes") == st.st_size
                       and previo.get("mtime") == int(st.st_mtime))
    if reutilizado:
        elemento = dict(previo)
    else:
        meta = _metadatos_foto(ruta) if tipo == "foto" else _metadatos_video(ruta, hay_ffmpeg)
        padre = ruta.parent.relative_to(carpeta).as_posix()
        elemento = {
            "tipo": tipo, "src": rel, "nombre": ruta.stem,
            "carpeta": "" if padre == "." else padre,
            "fecha": meta.pop("fecha").isoformat(timespec="seconds"),
            "bytes": st.st_size, "mtime": int(st.st_mtime),
            **{k: v for k, v in meta.items() if v},
        }

    if not reutilizado or not thumb.exists():
        try:
            if tipo == "foto":
                _miniatura_foto(ruta, thumb)
            elif hay_ffmpeg:
                _miniatura_video(ruta, thumb, elemento.get("duracion", 0))
        except Exception as exc:
            print(f"  miniatura omitida para {rel}: {exc}")
    elemento["thumb"] = thumb_rel if thumb.exists() else ""
    return elemento, reutilizado


def construir_indice(carpeta: Path, regenerar: bool = False, hilos: int = 0):
    """Lista de elementos (más recientes primero) y estadísticas de la regeneración."""
    carpeta_thumbs = carpeta / CARPETA_GALERIA / "thumbs"
    carpeta_thumbs.mkdir(parents=True, exist_ok=True)
    previos = {} if regenerar else _cargar_indice_previo(carpeta)
    originales = originales_por_destino(carpeta)
    hay_ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

    rutas = listar_archivos(carpeta, EXTENSIONES_FOTO | EXTENSIONES_VIDEO)
    hilos = hilos or min(8, os.cpu_count() or 2)
    with ThreadPoolExecutor(hilos) as pool:
        resultados = list(pool.map(
            lambda r: _elemento(r, carpeta, previos, hay_ffmpeg), rutas))

    elementos = []
    for elemento, _ in resultados:
        original = originales.get(elemento["src"])
        if original and (carpeta / original).exists():
            elemento["original"] = original
        else:
            elemento.pop("original", None)
        elementos.append(elemento)
    elementos.sort(key=lambda e: (e["fecha"], e["src"]), reverse=True)

    # Miniaturas de archivos que ya no existen
    usadas = {Path(e["thumb"]).name for e in elementos if e["thumb"]}
    huerfanas = [t for t in carpeta_thumbs.iterdir() if t.name not in usadas]
    for thumb in huerfanas:
        thumb.unlink(missing_ok=True)

    stats = {
        "fotos": sum(e["tipo"] == "foto" for e in elementos),
        "videos": sum(e["tipo"] == "video" for e in elementos),
        "reutilizados": sum(r for _, r in resultados),
        "miniaturas_borradas": len(huerfanas),
        "videos_sin_miniatura": sum(e["tipo"] == "video" and not e["thumb"]
                                    for e in elementos),
        "hay_ffmpeg": hay_ffmpeg,
    }
    return elementos, stats


# ----------------------------- Generación -----------------------------

def _escribir(ruta: Path, texto: str):
    tmp = ruta.with_name(ruta.name + ".part")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, ruta)


def generar_galeria(carpeta: Path, regenerar: bool = False) -> bool:
    print(f"Explorando {carpeta} …")
    elementos, stats = construir_indice(carpeta, regenerar)

    if not elementos:
        print("No se encontraron fotos ni vídeos para la galería.")
        return False

    indice = {"version": VERSION_INDICE, "titulo": carpeta.name, "elementos": elementos}
    _escribir(carpeta / "galeria.json",
              json.dumps(indice, ensure_ascii=False, separators=(",", ":")))
    _escribir(carpeta / "galeria.html", PLANTILLA.read_text(encoding="utf-8"))

    nuevos = len(elementos) - stats["reutilizados"]
    print(f"Galería generada: {stats['fotos']} foto(s) y {stats['videos']} vídeo(s) "
          f"({nuevos} nuevo(s) o modificado(s), {stats['reutilizados']} sin cambios).")
    if stats["videos_sin_miniatura"] and not stats["hay_ffmpeg"]:
        print(f"AVISO: {stats['videos_sin_miniatura']} vídeo(s) sin miniatura: "
              "instala FFmpeg para generarlas.")
    return True
