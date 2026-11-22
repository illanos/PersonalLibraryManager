"""Reorganiza una biblioteca ya importada, solo cuando se pide explícitamente.

    python main.py reorganizar <biblioteca> --whatsapp [--simular]
    python main.py reorganizar <biblioteca> --fechas-aproximadas [--simular]

- `--whatsapp`: lo que se importó antes de separar WhatsApp (estaba mezclado en
  Año/Mes) pasa a `WhatsApp/Año/Mes` (y las pegatinas, con `--pegatinas-aparte`,
  a `WhatsApp/Pegatinas/`).
- `--fechas-aproximadas`: renombra lo que recibió un nombre `AAAAMMDD_000000` porque
  su fecha salió del nombre sin hora (ver media_utils.fecha_aproximada).

Solo mueve o renombra archivos **dentro de la biblioteca**: el origen no se toca.
Actualiza el catálogo, `galeria.json` (reutilizando metadatos y miniaturas) y los
favoritos, así que no hace falta regenerar nada.
"""

import json
import os
from datetime import datetime
from pathlib import Path, PurePath

from catalogo import Catalogo, ruta_catalogo
from clasificacion import carpeta_destino, categoria, en_carpeta_whatsapp
from media_utils import CARPETA_GALERIA, fecha_aproximada, imprimir, nombre_libre

_RE_SIN_HORA = "_000000"


def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _escribir_json(ruta: Path, datos, **kwargs):
    tmp = ruta.with_name(ruta.name + ".part")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, **kwargs), encoding="utf-8")
    os.replace(tmp, ruta)


def plan(biblioteca: Path, fila, whatsapp: bool, fechas: bool, pegatinas_aparte: bool,
         reservados: set):
    """Nueva ruta relativa para una fila del catálogo, o None si se queda donde está."""
    rel = fila["destino"]
    actual = PurePath(rel)
    carpeta, base, ext = actual.parent.as_posix(), actual.stem, actual.suffix
    origen = Path(fila["origen"])
    try:
        fecha = datetime.fromisoformat(fila["fecha"]) if fila["fecha"] else None
    except ValueError:
        fecha = None
    if fecha is None:
        return None
    fuente, cambia = fila["fuente_fecha"], False

    if fechas and fila["fuente_fecha"] == "nombre" and _RE_SIN_HORA in base:
        mtime = datetime.fromtimestamp(fila["mtime_ns"] / 1e9)
        nueva_fecha, nueva_fuente, nueva_base = fecha_aproximada(origen, fecha, mtime)
        if not nueva_base.endswith(_RE_SIN_HORA):
            base, fecha, fuente, cambia = nueva_base, nueva_fecha, nueva_fuente, True

    if whatsapp and not en_carpeta_whatsapp(rel):
        ancho = fila["ancho"] if "ancho" in fila.keys() else 0
        alto = fila["alto"] if "alto" in fila.keys() else 0
        cat = categoria(PurePath(*origen.parts[-4:]), ancho or 0, alto or 0)
        if cat in ("whatsapp", "pegatina"):
            carpeta = carpeta_destino(fecha, cat, fila["tipo"], pegatinas_aparte)
            cambia = True

    if not cambia:
        return None
    nueva = nombre_libre(biblioteca / carpeta, base, ext, reservados)
    nueva_rel = nueva.relative_to(biblioteca).as_posix()
    return (nueva_rel, fecha, fuente) if nueva_rel != rel else None


def reorganizar(biblioteca: Path, simular: bool = False, whatsapp: bool = False,
                fechas: bool = False, pegatinas_aparte: bool = False) -> dict:
    stats = {"movidos": 0, "errores": 0}
    if not ruta_catalogo(biblioteca).exists():
        print(f"No hay catálogo en {biblioteca}: nada que reorganizar.")
        return stats

    indice_ruta = biblioteca / "galeria.json"
    indice = _leer_json(indice_ruta, {})
    elementos = {e.get("src"): e for e in indice.get("elementos", [])} if indice else {}
    favs_ruta = biblioteca / CARPETA_GALERIA / "favoritos.json"
    favoritos = _leer_json(favs_ruta, [])
    cambios = {}

    from galeria import _clave   # nombre de las miniaturas (por ruta)

    print(f"\n{'SIMULACIÓN' if simular else 'REORGANIZANDO'} — {biblioteca}\n")
    reservados = set()
    with Catalogo(biblioteca, simular) as catalogo:
        for fila in sorted(catalogo.filas(), key=lambda f: f["destino"]):
            rel = fila["destino"]
            if not (biblioteca / rel).exists():
                continue
            nuevo = plan(biblioteca, fila, whatsapp, fechas, pegatinas_aparte, reservados)
            if not nuevo:
                continue
            nueva_rel, fecha, fuente = nuevo
            imprimir(f"  {rel}  ->  {nueva_rel}")
            stats["movidos"] += 1
            if simular:
                continue
            try:
                destino = biblioteca / nueva_rel
                destino.parent.mkdir(parents=True, exist_ok=True)
                os.replace(biblioteca / rel, destino)
                if fecha != datetime.fromisoformat(fila["fecha"]):
                    marca = fecha.timestamp()
                    os.utime(destino, (marca, marca))
                catalogo.cambiar_destino(rel, nueva_rel, fecha.isoformat(), fuente)
            except OSError as exc:
                imprimir(f"  ERROR {rel}: {exc}")
                stats["errores"] += 1
                continue
            cambios[rel] = nueva_rel
            elemento = elementos.get(rel)
            if elemento:
                viejo_thumb = biblioteca / elemento.get("thumb", "") if elemento.get("thumb") else None
                nuevo_thumb_rel = f"{CARPETA_GALERIA}/thumbs/{_clave(nueva_rel)}.jpg"
                if viejo_thumb and viejo_thumb.exists():
                    os.replace(viejo_thumb, biblioteca / nuevo_thumb_rel)
                    elemento["thumb"] = nuevo_thumb_rel
                padre = PurePath(nueva_rel).parent.as_posix()
                st = destino.stat()
                elemento.update(src=nueva_rel, nombre=PurePath(nueva_rel).stem,
                                carpeta="" if padre == "." else padre,
                                fecha=fecha.isoformat(timespec="seconds"),
                                bytes=st.st_size, mtime=int(st.st_mtime))

    if cambios and not simular:
        if indice:
            _escribir_json(indice_ruta, indice, separators=(",", ":"))
        if favoritos:
            _escribir_json(favs_ruta, sorted({cambios.get(f, f) for f in favoritos}), indent=1)
        # Carpetas que hayan quedado vacías dentro de la biblioteca
        for viejo in cambios:
            carpeta = (biblioteca / viejo).parent
            while carpeta != biblioteca:
                try:
                    carpeta.rmdir()
                except OSError:
                    break
                carpeta = carpeta.parent

    accion = "a mover o renombrar" if simular else "movidos o renombrados"
    print(f"\nArchivos {accion}: {stats['movidos']}  (errores: {stats['errores']})")
    if cambios and not simular:
        print("Galería y favoritos actualizados (el origen no se ha tocado).")
    return stats
