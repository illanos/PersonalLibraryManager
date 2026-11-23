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
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from catalogo import info_por_destino
from media_utils import (CARPETA_GALERIA, fecha_desde_nombre, fecha_mtime, listar_archivos,
                         progreso)
from clasificacion import RE_CAPTURA, ambito, es_pegatina
import lugares
from similares import UMBRAL, _proporciones_compatibles, agrupar, con_detalle, dhash

EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
EXTENSIONES_VIDEO = {".mp4", ".webm", ".mov", ".m4v"}
EXTENSIONES_AUDIO = {".opus", ".mp3", ".m4a", ".aac", ".ogg", ".wav"}

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

CAMPOS_FOTO = ("ancho", "alto", "camara", "objetivo", "exposicion", "gps", "etiquetas",
               "personas", "titulo", "descripcion", "autor", "valoracion")


def _metadatos_foto(ruta: Path) -> dict:
    from metadatos import leer_metadatos
    try:
        datos = leer_metadatos(ruta)
    except Exception:
        return {"fecha": fecha_desde_nombre(ruta.stem) or fecha_mtime(ruta)}
    return {"fecha": datos["fecha"], **{c: datos[c] for c in CAMPOS_FOTO}}


def _metadatos_audio(ruta: Path, hay_ffmpeg: bool) -> dict:
    """Fecha del nombre que le dio la importación (AAAAMMDD_HHMMSS) y duración."""
    from videos import sondear
    info = (sondear(ruta) if hay_ffmpeg else None) or {}
    fecha = fecha_desde_nombre(ruta.stem) or info.get("fecha") or fecha_mtime(ruta)
    return {"fecha": fecha, "duracion": round(info.get("duracion", 0), 1)}


def _tipo(ruta: Path) -> str:
    ext = ruta.suffix.lower()
    if ext in EXTENSIONES_FOTO:
        return "foto"
    return "audio" if ext in EXTENSIONES_AUDIO else "video"


def _metadatos_video(ruta: Path, hay_ffmpeg: bool) -> dict:
    from videos import fecha_video, sondear
    info = (sondear(ruta) if hay_ffmpeg else None) or {}
    fecha, _ = fecha_video(ruta, info)
    return {"fecha": fecha, "ancho": info.get("ancho", 0), "alto": info.get("alto", 0),
            "duracion": round(info.get("duracion", 0), 1),
            "camara": info.get("camara", ""), "gps": info.get("gps")}


# Etiquetas automáticas: casi ninguna foto de móvil trae etiquetas propias, pero
# sus metadatos permiten agruparlas igualmente.
_RE_WHATSAPP = re.compile(r"-WA\d{4}|whatsapp", re.IGNORECASE)


def etiquetas_automaticas(e: dict) -> list:
    nombres = f"{e.get('nombre_original', '')} {e.get('nombre', '')}"
    ancho, alto = e.get("ancho") or 0, e.get("alto") or 0
    pegatina = e.get("tipo", "foto") == "foto" and any(
        es_pegatina(n, ancho, alto) for n in (e.get("src", ""), e.get("nombre_original", ""))
        if n) or "/Pegatinas/" in f"/{e.get('src', '')}"
    reglas = [
        ("Selfies", re.search(r"front|frontal|selfie", e.get("objetivo", ""), re.IGNORECASE)),
        ("Capturas", RE_CAPTURA.search(nombres)),
        ("WhatsApp", e.get("ambito") == "whatsapp" or _RE_WHATSAPP.search(nombres)),
        ("Pegatinas", pegatina),
        ("Con ubicación", e.get("gps")),
        ("Con estrellas", e.get("valoracion")),
        ("Verticales", alto > ancho * 1.1 > 0),
        ("Panorámicas", alto and ancho / alto >= 2),   # no las capturas de móvil (verticales)
        ("Fecha dudosa", e.get("fuente_fecha") == "archivo"),
        ("Hora aproximada", e.get("fuente_fecha") == "nombre+hora_archivo"),
        ("Parecidas", e.get("parecidas")),
    ]
    return [nombre for nombre, cumple in reglas if cumple]


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
    tipo = _tipo(ruta)
    thumb_rel = f"{CARPETA_GALERIA}/thumbs/{_clave(rel)}.jpg"
    thumb = carpeta / thumb_rel

    previo = previos.get(rel)
    reutilizado = bool(previo and previo.get("bytes") == st.st_size
                       and previo.get("mtime") == int(st.st_mtime))
    if reutilizado:
        elemento = dict(previo)
    else:
        meta = (_metadatos_foto(ruta) if tipo == "foto" else
                _metadatos_audio(ruta, hay_ffmpeg) if tipo == "audio" else
                _metadatos_video(ruta, hay_ffmpeg))
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
            elif tipo == "video" and hay_ffmpeg:
                _miniatura_video(ruta, thumb, elemento.get("duracion", 0))
        except Exception as exc:
            print(f"  miniatura omitida para {rel}: {exc}")
    elemento["thumb"] = thumb_rel if thumb.exists() else ""
    if tipo == "foto" and "dhash" not in elemento:
        # Hash perceptual: de la miniatura si existe (mucho más rápido; da el mismo hash)
        try:
            elemento["dhash"] = dhash(thumb if thumb.exists() else ruta)
        except Exception:
            pass
    return elemento, reutilizado


def construir_indice(carpeta: Path, regenerar: bool = False, hilos: int = 0):
    """Lista de elementos (más recientes primero) y estadísticas de la regeneración."""
    carpeta_thumbs = carpeta / CARPETA_GALERIA / "thumbs"
    carpeta_thumbs.mkdir(parents=True, exist_ok=True)
    previos = {} if regenerar else _cargar_indice_previo(carpeta)
    catalogo = info_por_destino(carpeta)
    hay_ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

    rutas = listar_archivos(carpeta, EXTENSIONES_FOTO | EXTENSIONES_VIDEO | EXTENSIONES_AUDIO)
    hilos = hilos or min(8, os.cpu_count() or 2)
    resultados = []
    with ThreadPoolExecutor(hilos) as pool:
        for n, resultado in enumerate(pool.map(
                lambda r: _elemento(r, carpeta, previos, hay_ffmpeg), rutas), 1):
            resultados.append(resultado)
            progreso("avance", "galeria", paso="Miniaturas", hecho=n, total=len(rutas),
                     archivo=resultado[0]["src"])

    grupos = marcar_parecidas([e for e, _ in resultados])

    elementos = []
    for elemento, _ in resultados:
        for clave in ("original", "nombre_original", "fuente_fecha", "auto", "ambito"):
            elemento.pop(clave, None)
        info = catalogo.get(elemento["src"], {})
        # WhatsApp va aparte: la galería solo lo muestra en su propia vista
        if ambito(elemento["src"], info.get("origen") or ""):
            elemento["ambito"] = "whatsapp"
        if info.get("original") and (carpeta / info["original"]).exists():
            elemento["original"] = info["original"]
        if info.get("origen"):
            elemento["nombre_original"] = Path(info["origen"]).name
        if info.get("fuente_fecha"):
            elemento["fuente_fecha"] = info["fuente_fecha"]
        auto = etiquetas_automaticas(elemento)
        if auto:
            elemento["auto"] = auto
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
        "audios": sum(e["tipo"] == "audio" for e in elementos),
        "reutilizados": sum(r for _, r in resultados),
        "miniaturas_borradas": len(huerfanas),
        "videos_sin_miniatura": sum(e["tipo"] == "video" and not e["thumb"]
                                    for e in elementos),
        "hay_ffmpeg": hay_ffmpeg,
        "grupos_parecidas": grupos,
    }
    return elementos, stats


def marcar_parecidas(elementos: list) -> int:
    """Pone `parecidas` (número de grupo) a las fotos casi idénticas. Devuelve cuántos grupos."""
    fotos = {e["src"]: e for e in elementos if e.get("dhash")}
    proporciones = {src: e["ancho"] / e["alto"] for src, e in fotos.items()
                    if e.get("ancho") and e.get("alto")}
    for e in elementos:
        e.pop("parecidas", None)
    grupos = agrupar({src: e["dhash"] for src, e in fotos.items()}, proporciones)
    for n, grupo in enumerate(sorted(sorted(g) for g in grupos), 1):
        for src in grupo:
            fotos[src]["parecidas"] = n
    return len(grupos)


def actualizar_parecidas(elementos: list, numeros_quitados=(), nuevos=()):
    """Como `marcar_parecidas`, pero rehace solo los grupos afectados: los de número en
    `numeros_quitados` (de fotos que se han quitado) y los que tocan las fotos `nuevos`
    (srcs añadidos). Da el mismo agrupamiento sin comparar toda la biblioteca entre sí,
    que con decenas de miles de fotos tarda más de un minuto."""
    fotos = {e["src"]: e for e in elementos if e.get("dhash")}
    proporciones = {src: e["ancho"] / e["alto"] for src, e in fotos.items()
                    if e.get("ancho") and e.get("alto")}
    por_numero = {}
    for src, e in fotos.items():
        if e.get("parecidas"):
            por_numero.setdefault(e["parecidas"], set()).add(src)
    tocados = {n for n in numeros_quitados if n}
    afectados = set()
    valores = {src: int(e["dhash"], 16) for src, e in fotos.items() if con_detalle(e["dhash"])}
    for nuevo in nuevos:
        if nuevo not in fotos:
            continue
        afectados.add(nuevo)
        v = valores.get(nuevo)
        if v is None:
            continue
        for src, w in valores.items():
            if (src != nuevo and (v ^ w).bit_count() <= UMBRAL
                    and _proporciones_compatibles(proporciones.get(nuevo), proporciones.get(src))):
                afectados.add(src)
                if fotos[src].get("parecidas"):
                    tocados.add(fotos[src]["parecidas"])
    for n in tocados:
        afectados |= por_numero.get(n, set())
    for src in afectados:
        fotos[src].pop("parecidas", None)
    libres = sorted(tocados)
    siguiente = max(por_numero, default=0) + 1
    for grupo in sorted(sorted(g) for g in agrupar({s: fotos[s]["dhash"] for s in afectados},
                                                    proporciones)):
        if libres:
            n = libres.pop(0)
        else:
            n, siguiente = siguiente, siguiente + 1
        for src in grupo:
            fotos[src]["parecidas"] = n


# ----------------------------- Generación -----------------------------

def _escribir(ruta: Path, texto: str):
    tmp = ruta.with_name(ruta.name + ".part")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, ruta)


def generar_galeria(carpeta: Path, regenerar: bool = False, caras: bool = False) -> bool:
    print(f"Explorando {carpeta} …")
    elementos, stats = construir_indice(carpeta, regenerar)

    if not elementos:
        print("No se encontraron fotos ni vídeos para la galería.")
        return False

    avisos = []
    geo = lugares.cargar()
    if geo:
        nuevos = lugares.asignar_lugares(elementos, geo)
        if nuevos:
            print(f"Lugares: {nuevos} elemento(s) con GPS localizados (sin conexión).")
    elif any(e.get("gps") for e in elementos):
        avisos.append("AVISO: sin lugares (nombre de la ciudad a partir del GPS). Para "
                      "obtenerlos, una sola vez:  python main.py galeria <carpeta> "
                      "--descargar-lugares")
    if caras:
        from caras import aplicar_caras
        analizadas, aviso = aplicar_caras(carpeta, elementos)
        if aviso:
            avisos.append(aviso)
        if analizadas:
            print(f"Caras: {analizadas} foto(s) analizadas ahora "
                  "(el resto, de ejecuciones anteriores).")

    from caras import leer_nombres
    indice = {"version": VERSION_INDICE, "titulo": carpeta.name, "elementos": elementos,
              "nombres_caras": leer_nombres(carpeta)}
    _escribir(carpeta / "galeria.json",
              json.dumps(indice, ensure_ascii=False, separators=(",", ":")))
    _escribir(carpeta / "galeria.html", PLANTILLA.read_text(encoding="utf-8"))

    nuevos = len(elementos) - stats["reutilizados"]
    progreso("resumen", "galeria", resumen={
        "fotos": stats["fotos"], "videos": stats["videos"], "audios": stats["audios"],
        "nuevos": nuevos, "reutilizados": stats["reutilizados"],
        "grupos_parecidas": stats["grupos_parecidas"]})
    print(f"Galería generada: {stats['fotos']} foto(s), {stats['videos']} vídeo(s) "
          f"y {stats['audios']} audio(s) "
          f"({nuevos} nuevo(s) o modificado(s), {stats['reutilizados']} sin cambios).")
    if stats["grupos_parecidas"]:
        print(f"Fotos parecidas: {stats['grupos_parecidas']} grupo(s) "
              "(filtro «Parecidas» en la galería; no se ha borrado nada).")
    for aviso in avisos:
        print(aviso)
    if stats["videos_sin_miniatura"] and not stats["hay_ffmpeg"]:
        print(f"AVISO: {stats['videos_sin_miniatura']} vídeo(s) sin miniatura: "
              "instala FFmpeg para generarlas.")
    return True
