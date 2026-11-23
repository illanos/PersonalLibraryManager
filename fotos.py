"""Tratamiento de fotos: fecha de captura, organización Año/Mes y optimización.

Requiere:  pip install Pillow
Opcional:  pip install pillow-heif   (fotos HEIC/HEIF del iPhone)
"""

import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from catalogo import Catalogo, Informe
from clasificacion import carpeta_destino, categoria
from danados import ILEGIBLE, RegistroDanados, diagnosticar, problema_de_excepcion
from media_utils import (
    NOMBRE_ORIGINALES, MetadatosExtra, contar_extra, copiar_atomico, elegir_fecha,
    fecha_desde_nombre, fecha_mtime, fecha_y_nombre, hash_archivo, imprimir,
    imprimir_resumen, listar_archivos, metadatos_para_escribir, nombre_libre,
    nuevas_estadisticas, resumen_extra, ruta_temporal, subcarpeta_fecha,
)
from metadatos import jpeg_con_extra, leer_metadatos, parametros_guardado
from similares import agrupar, calidad, dhash, es_copia

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_DISPONIBLE = True
except ImportError:
    HEIF_DISPONIBLE = False

EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif",
                    ".tif", ".tiff", ".bmp", ".gif"}
EXTENSIONES_HEIF = {".heic", ".heif"}

# formato -> (nombre en Pillow, extensión de salida, extensiones "ya en ese formato")
FORMATOS = {
    "jpeg": ("JPEG", ".jpg", {".jpg", ".jpeg"}),
    "webp": ("WEBP", ".webp", {".webp"}),
}

MAX_LADO = 3200   # píxeles máximos en el lado largo (0 = no redimensionar)
CALIDAD = 88      # 80-92 = buen equilibrio calidad/peso

@dataclass
class OpcionesFotos:
    max_lado: int = MAX_LADO
    calidad: int = CALIDAD
    formato: str = "jpeg"
    conservar_originales: bool = False   # copia extra en originales/ (el origen nunca se toca)
    hilos: int = 0          # 0 = automático
    omitir_parecidas: bool = False   # no importar la peor copia de un grupo de parecidas
    pegatinas_aparte: bool = False   # pegatinas en WhatsApp/Pegatinas/ en vez de con el resto
    # Metadatos que vienen aparte de cada archivo (p. ej. takeout.IndiceTakeout): objeto
    # con metadatos(ruta) -> MetadatosExtra | None y omitir(ruta) -> motivo | None
    externos: object = None


# ----------------------------- Fecha -----------------------------

def obtener_fecha(ruta: Path):
    """(fecha, fuente): EXIF > nombre del archivo > fecha de modificación."""
    try:
        datos = leer_metadatos(ruta)
        return datos["fecha"], datos["fuente"]
    except Exception:
        fecha = fecha_desde_nombre(ruta.stem)
        return (fecha, "nombre") if fecha else (fecha_mtime(ruta), "archivo")


# ----------------------------- Optimización -----------------------------

def guardar_optimizada(ruta: Path, destino: Path, opciones: OpcionesFotos = None,
                       extra: MetadatosExtra = None) -> list:
    """Escribe en `destino` la versión reducida y recomprimida (de forma atómica).

    Conserva EXIF, XMP, IPTC, ICC y comentario (ver metadatos.py) y les añade los
    metadatos externos de `extra`. Devuelve la lista de avisos sobre metadatos que no
    se hayan podido conservar.
    """
    opciones = opciones or OpcionesFotos()
    formato_pil = FORMATOS[opciones.formato][0]
    avisos = []

    with Image.open(ruta) as original:
        im = ImageOps.exif_transpose(original)   # aplica la rotación EXIF
        kwargs = parametros_guardado(original, im, formato_pil, avisos, extra)

    if opciones.max_lado and max(im.size) > opciones.max_lado:
        factor = opciones.max_lado / max(im.size)
        nuevo = (max(1, round(im.width * factor)), max(1, round(im.height * factor)))
        im = im.resize(nuevo, Image.Resampling.LANCZOS, reducing_gap=3.0)

    transparente = im.mode in ("RGBA", "LA", "PA") or (
        im.mode == "P" and "transparency" in im.info)
    if transparente and formato_pil == "WEBP":
        im = im.convert("RGBA")
    elif transparente:
        rgba = im.convert("RGBA")
        im = Image.new("RGB", im.size, (255, 255, 255))
        im.paste(rgba, mask=rgba.getchannel("A"))
    elif im.mode not in ("RGB", "L"):
        im = im.convert("RGB")

    kwargs["quality"] = opciones.calidad
    if formato_pil == "JPEG":
        kwargs.update(optimize=True, progressive=True)

    tmp = ruta_temporal(destino)
    try:
        im.save(tmp, formato_pil, **kwargs)
        os.replace(tmp, destino)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return avisos


# ----------------------------- Procesamiento -----------------------------

@dataclass
class _Tarea:
    ruta: Path
    estado: str = "pendiente"      # pendiente | ya_importado | parecida_conocida | danado | error
    problema: str = ""           # dañado: vacío | sin cabecera válida | truncado | ilegible
    conocido: bool = False        # dañado ya anotado en una ejecución anterior
    detalle: str = ""
    tamano: int = 0
    mtime_ns: int = 0
    hash: str = ""
    fecha: datetime = None
    fuente: str = ""
    dimensiones: tuple = (0, 0)
    animado: bool = False
    destino: Path = None
    original: Path = None
    avisos: list = None
    phash: str = None
    parecidas: list = None     # otras fotos del mismo grupo (para el informe)
    mejor: object = None       # con omitir_parecidas: la copia que se queda (tarea o destino)
    base: str = ""             # nombre final sin extensión (AAAAMMDD_HHMMSS...)
    categoria: str = ""        # whatsapp | pegatina | captura | '' (ver clasificacion.py)
    extra: MetadatosExtra = None   # metadatos externos que se escriben en la foto


def _analizar(ruta: Path, catalogo: Catalogo, origen: Path, externos=None) -> _Tarea:
    """Fase 1 (en paralelo): ¿ya importada? hash, fecha y propiedades."""
    t = _Tarea(ruta)
    try:
        st = ruta.stat()
        t.tamano, t.mtime_ns = st.st_size, st.st_mtime_ns
        # Mismo archivo de una ejecución anterior: ni siquiera hace falta leerlo entero
        fila = catalogo.buscar_por_origen(ruta, st)
        if fila is not None:
            t.estado, t.detalle = "ya_importado", fila["destino"]
            return t
        descarte = catalogo.buscar_descarte(ruta, st)
        if descarte is not None and descarte["motivo"] == "danado":
            t.estado, t.problema, t.detalle = "danado", descarte["problema"], descarte["detalle"]
            t.conocido = True
            return t
        if (descarte is not None and descarte["motivo"] == "parecida" and descarte["referencia"]
                and (catalogo.biblioteca / descarte["referencia"]).exists()):
            t.estado, t.detalle = "parecida_conocida", descarte["referencia"]
            return t
        diagnostico = diagnosticar(ruta, st.st_size, imagen=True)
        if diagnostico:
            t.estado, (t.problema, t.detalle) = "danado", diagnostico
            return t
        t.hash = hash_archivo(ruta)
        fila = catalogo.buscar_por_hash(t.hash)   # mismo contenido, otra ruta
        if fila is not None:
            t.estado, t.detalle = "ya_importado", fila["destino"]
            return t
        try:
            datos = leer_metadatos(ruta, completo=False)
        except Exception as exc:
            t.estado, t.problema, t.detalle = "danado", problema_de_excepcion(exc) or ILEGIBLE, str(exc)
            return t
        extra = externos.metadatos(ruta) if externos else None
        fecha, fuente = elegir_fecha(ruta, datos["fecha"], datos["fuente"], extra)
        t.fecha, t.fuente, t.base = fecha_y_nombre(ruta, fecha, fuente)
        t.extra = metadatos_para_escribir(ruta, extra, t.fecha, t.fuente)
        if t.extra is not None and datos["gps"]:
            t.extra = replace(t.extra, gps=None)   # el GPS de la foto manda
        t.dimensiones = (datos["ancho"], datos["alto"])
        t.animado = datos["animado"]
        t.categoria = categoria(ruta.relative_to(origen), *t.dimensiones)
        try:
            t.phash = dhash(ruta)
        except Exception:
            t.phash = None   # no impide importarla; solo no se compara con otras
    except Exception as exc:
        t.estado, t.detalle = "error", f"no se puede leer: {exc}"
    return t


def _ejecutar(t: _Tarea, opciones: OpcionesFotos, extensiones_mismo_formato: set) -> str:
    """Fase 3 (en paralelo): escribe la foto final y la copia del original."""
    t.destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        if t.animado:
            copiar_atomico(t.ruta, t.destino)   # GIF/WebP animados: no perder la animación
            accion = "COPIADO_ANIMADO"
        elif t.categoria == "pegatina":
            copiar_atomico(t.ruta, t.destino)   # WebP pequeño con transparencia: tal cual
            accion = "PEGATINA"
        else:
            t.avisos = guardar_optimizada(t.ruta, t.destino, opciones, t.extra)
            sin_redimensionar = not opciones.max_lado or max(t.dimensiones) <= opciones.max_lado
            if (sin_redimensionar and t.ruta.suffix.lower() in extensiones_mismo_formato
                    and t.destino.stat().st_size >= t.tamano
                    and _copiar_sin_recomprimir(t)):   # recomprimir no compensa
                accion, t.avisos = "SIN_CAMBIOS", []
            else:
                accion = "OK"
        # Fecha del archivo = fecha de captura: el explorador ordena igual que la galería
        marca = t.fecha.timestamp()
        os.utime(t.destino, (marca, marca))
        if t.original:
            t.original.parent.mkdir(parents=True, exist_ok=True)
            copiar_atomico(t.ruta, t.original)
    except BaseException:
        t.destino.unlink(missing_ok=True)   # no dejar una foto sin su original
        raise
    return accion


def _combinar_copias(tareas: list):
    """Copias idénticas (mismo MD5; en Google, la de un álbum y la de «Fotos del AAAA»):
    solo se importa la primera, con los álbumes, personas… de todas. `tareas`, ya en el
    orden en que se importan."""
    primeras = {}
    for t in tareas:
        if t.estado != "pendiente" or not t.hash:
            continue
        primera = primeras.setdefault(t.hash, t)
        if primera is not t and t.extra is not None:
            primera.extra = (replace(t.extra, fecha=None, zona="") if primera.extra is None
                             else primera.extra.combinar(t.extra))


def _copiar_sin_recomprimir(t: _Tarea) -> bool:
    """El original tal cual a `t.destino`; con metadatos externos que añadir (solo JPEG),
    insertados sin recomprimir. False si no se puede: se queda la versión recomprimida,
    que sí los lleva."""
    if t.extra is None or t.ruta.suffix.lower() not in (".jpg", ".jpeg"):
        if t.extra is not None and (t.extra.fecha or t.extra.gps or t.extra.aporta_xmp()):
            return False   # WebP: no se sabe insertar sin recomprimir
        copiar_atomico(t.ruta, t.destino)
        return True
    try:
        datos = jpeg_con_extra(t.ruta.read_bytes(), t.extra)
    except (ValueError, OSError, SyntaxError):
        return False
    tmp = ruta_temporal(t.destino)
    try:
        tmp.write_bytes(datos)
        os.replace(tmp, t.destino)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return True


def _marcar_parecidas(tareas: list, catalogo: Catalogo, origen: Path, omitir: bool):
    """Agrupa las fotos nuevas parecidas entre sí o a otras ya importadas.

    Rellena `t.parecidas` (para el informe) y, con `omitir`, `t.mejor` en todas las
    copias nuevas de un grupo salvo la mejor (más píxeles, con EXIF, más bytes).
    """
    nuevas, md5_vistos = {}, set()
    for i, t in enumerate(tareas):
        if t.estado == "pendiente" and t.phash and t.hash not in md5_vistos:
            md5_vistos.add(t.hash)
            nuevas[("n", i)] = t
    if not nuevas:
        return
    previas = {("c", f["destino"]): f for f in catalogo.fotos_con_phash()}
    hashes = {c: t.phash for c, t in nuevas.items()}
    hashes.update({c: f["phash"] for c, f in previas.items()})
    proporciones = {c: t.dimensiones[0] / t.dimensiones[1]
                    for c, t in nuevas.items() if t.dimensiones[1]}
    proporciones.update({c: f["ancho"] / f["alto"] for c, f in previas.items()
                         if f["ancho"] and f["alto"]})

    def nombre(c):
        return c[1] if c[0] == "c" else nuevas[c].ruta.relative_to(origen).as_posix()

    def puntuacion(c):
        if c[0] == "c":
            f = previas[c]
            return calidad(f["ancho"], f["alto"], f["bytes_antes"], f["fuente_fecha"])
        t = nuevas[c]
        return calidad(*t.dimensiones, t.tamano, t.fuente)

    def fecha_exif(c):
        if c[0] == "c":
            f = previas[c]
            return f["fecha"] if f["fuente_fecha"] == "exif" else None
        t = nuevas[c]
        return t.fecha.isoformat() if t.fuente == "exif" else None

    for grupo in agrupar(hashes, proporciones):
        mejor = max(grupo, key=lambda c: (puntuacion(c), c[0] == "c"))
        for c in grupo:
            if c[0] != "n":
                continue
            t = nuevas[c]
            t.parecidas = [nombre(o) for o in grupo if o != c]
            if omitir and c != mejor and es_copia(hashes[c], hashes[mejor],
                                                  fecha_exif(c), fecha_exif(mejor)):
                t.mejor = mejor[1] if mejor[0] == "c" else nuevas[mejor]


def procesar_fotos(origen: Path, destino: Path, simular: bool,
                   opciones: OpcionesFotos = None) -> dict:
    opciones = opciones or OpcionesFotos()
    formato_pil, ext_salida, mismo_formato = FORMATOS[opciones.formato]
    carpeta_originales = destino / NOMBRE_ORIGINALES
    stats = nuevas_estadisticas()

    archivos = listar_archivos(origen, EXTENSIONES_FOTO)
    externos = opciones.externos
    omitidos_externos = []
    if externos:
        omitidos_externos = [(a, m) for a in archivos for m in [externos.omitir(a)] if m]
        if omitidos_externos:
            descartar = {a for a, _ in omitidos_externos}
            archivos = [a for a in archivos if a not in descartar]
            stats["editadas"] = len(omitidos_externos)
    if not archivos:
        print(f"No se encontraron fotos en {origen}")
        return stats

    if not HEIF_DISPONIBLE:
        heif = [a for a in archivos if a.suffix.lower() in EXTENSIONES_HEIF]
        if heif:
            print(f"AVISO: se omiten {len(heif)} foto(s) HEIC/HEIF. "
                  "Para incluirlas:  pip install pillow-heif")
            archivos = [a for a in archivos if a.suffix.lower() not in EXTENSIONES_HEIF]
            stats["omitidos"] = len(heif)

    hilos = opciones.hilos or min(8, os.cpu_count() or 2)
    print(f"\n{'SIMULACIÓN' if simular else 'PROCESANDO'} — {len(archivos)} foto(s) — "
          f"{formato_pil}, calidad {opciones.calidad}, "
          f"máx. {opciones.max_lado or 'sin límite'} px — {hilos} hilo(s)\n")
    if omitidos_externos:
        print(f"Se omiten {len(omitidos_externos)} versión(es) editada(s): se importa su "
              "original (ver informe)\n")

    danados = RegistroDanados(destino, origen, "fotos", simular)
    with Catalogo(destino, simular) as catalogo, \
            Informe(destino, "fotos", simular) as informe, \
            ThreadPoolExecutor(hilos) as pool:
        try:
            for ruta, motivo in omitidos_externos:
                informe.anotar("OMITIDA", ruta, detalle=motivo)
            # Fase 1: análisis en paralelo
            tareas = list(pool.map(lambda r: _analizar(r, catalogo, origen, externos), archivos))

            # Fase 2: duplicados y nombres, en orden cronológico (ráfagas -> _01, _02...)
            reservados, vistos, pendientes, omitidas = set(), {}, [], []
            tareas.sort(key=lambda t: (t.fecha or datetime.min, str(t.ruta)))
            if externos:
                _combinar_copias(tareas)
            _marcar_parecidas(tareas, catalogo, origen, opciones.omitir_parecidas)
            for t in tareas:
                rel = t.ruta.relative_to(origen)
                if t.estado == "ya_importado":
                    stats["ya_importados"] += 1
                    continue
                if t.estado == "parecida_conocida":
                    stats["parecidas_omitidas"] += 1
                    continue
                if t.estado == "danado":
                    _anotar_danado(t, rel, danados, catalogo, informe, stats)
                    continue
                if t.estado == "error":
                    imprimir(f"  ERROR      {rel}: {t.detalle}")
                    informe.anotar("ERROR", t.ruta, detalle=t.detalle)
                    stats["errores"] += 1
                    continue
                if t.hash in vistos:
                    t.detalle = f"igual que {vistos[t.hash]}"
                    imprimir(f"  DUPLICADO  {rel}  ({t.detalle})")
                    informe.anotar("DUPLICADO", t.ruta, detalle=t.detalle)
                    stats["duplicados"] += 1
                    continue

                vistos[t.hash] = rel
                if t.parecidas:
                    stats["parecidas"] += 1
                if t.mejor is not None:
                    omitidas.append(t)
                    continue
                carpeta_rel = carpeta_destino(t.fecha, t.categoria, "foto",
                                              opciones.pegatinas_aparte)
                tal_cual = t.animado or t.categoria == "pegatina"
                ext = t.ruta.suffix.lower() if tal_cual else ext_salida
                t.destino = nombre_libre(destino / carpeta_rel,
                                         t.base, ext, reservados)
                if opciones.conservar_originales:
                    t.original = nombre_libre(carpeta_originales / carpeta_rel,
                                              t.ruta.stem, t.ruta.suffix, reservados)
                if simular:
                    anade = resumen_extra(t.extra, externos, tal_cual)
                    imprimir(f"  {rel}  ->  {carpeta_rel}/{t.destino.name}  "
                             f"[fecha: {t.fuente}]{anade}")
                    stats["procesados"] += 1
                    contar_extra(stats, t.extra, externos)
                else:
                    pendientes.append(t)

            for t in omitidas:
                rel = t.ruta.relative_to(origen)
                ref = t.mejor if isinstance(t.mejor, str) else \
                    t.mejor.destino.relative_to(destino).as_posix()
                imprimir(f"  PARECIDA   {rel}  (peor copia que {ref}: no se importa)")
                informe.anotar("PARECIDA_OMITIDA", t.ruta, detalle=f"peor copia que {ref}",
                               parecidas=", ".join(t.parecidas))
                catalogo.descartar(t.ruta, t.tamano, t.mtime_ns, "foto", "parecida",
                                   detalle="peor copia de un grupo de parecidas",
                                   referencia=ref)
                stats["parecidas_omitidas"] += 1

            # Fase 3: escritura en paralelo
            futuros = {pool.submit(_ejecutar, t, opciones, mismo_formato): t
                       for t in pendientes}
            for n, futuro in enumerate(as_completed(futuros), 1):
                t = futuros[futuro]
                rel = t.ruta.relative_to(origen)
                destino_rel = t.destino.relative_to(destino).as_posix()
                prefijo = f"  [{n}/{len(pendientes)}]"
                try:
                    accion = futuro.result()
                except Exception as exc:
                    problema = problema_de_excepcion(exc)
                    if problema:
                        t.estado, t.problema, t.detalle = "danado", problema, str(exc)
                        _anotar_danado(t, rel, danados, catalogo, informe, stats)
                        continue
                    imprimir(f"{prefijo} ERROR {rel}: {exc}")
                    informe.anotar("ERROR", t.ruta, detalle=str(exc))
                    stats["errores"] += 1
                    continue
                despues = t.destino.stat().st_size
                original_rel = t.original.relative_to(destino).as_posix() if t.original else None
                catalogo.registrar(
                    hash=t.hash, tipo="foto", origen=str(t.ruta), tamano=t.tamano,
                    mtime_ns=t.mtime_ns, destino=destino_rel, original=original_rel,
                    fecha=t.fecha.isoformat(), fuente_fecha=t.fuente,
                    bytes_antes=t.tamano, bytes_despues=despues,
                    phash=t.phash, ancho=t.dimensiones[0], alto=t.dimensiones[1])
                detalle = list(t.avisos or [])
                if externos:
                    copia = accion in ("COPIADO_ANIMADO", "PEGATINA")
                    detalle.insert(0, resumen_extra(t.extra, externos, copia).strip(" []"))
                informe.anotar(accion, t.ruta, destino_rel, t.fecha, t.fuente,
                               t.tamano, despues, "; ".join(filter(None, detalle)),
                               ", ".join(t.parecidas or []))
                contar_extra(stats, t.extra, externos)
                etiqueta = {"OK": "OK", "SIN_CAMBIOS": "SIN CAMBIOS",
                            "COPIADO_ANIMADO": "ANIMADA", "PEGATINA": "PEGATINA"}[accion]
                imprimir(f"{prefijo} {etiqueta}  {rel}  ->  {destino_rel}")
                for aviso in t.avisos or []:
                    imprimir(f"      aviso: {aviso}")
                stats["procesados"] += 1
                stats["sin_cambios"] += accion != "OK"
                stats["bytes_antes"] += t.tamano
                stats["bytes_despues"] += despues
        except KeyboardInterrupt:
            pool.shutdown(wait=True, cancel_futures=True)
            imprimir("\nInterrumpido. Lo ya terminado queda registrado; "
                     "vuelve a ejecutar para continuar.")
            raise

    imprimir_resumen(stats, "fotos", simular,
                     carpeta_originales if opciones.conservar_originales else None,
                     informe.ruta if informe.filas else None)
    danados.cerrar()
    return stats


def _anotar_danado(t: _Tarea, rel, danados: RegistroDanados, catalogo: Catalogo,
                   informe: Informe, stats: dict):
    imprimir(f"  DAÑADO     {rel}  ({t.problema}{': ' + t.detalle if t.detalle else ''})")
    danados.anotar(t.ruta, t.problema, t.detalle, t.tamano, t.conocido)
    if not t.conocido:
        informe.anotar("DANADO", t.ruta, detalle=f"{t.problema}: {t.detalle}")
        catalogo.descartar(t.ruta, t.tamano, t.mtime_ns, "foto", "danado", t.problema, t.detalle)
    stats["danados"] += 1
