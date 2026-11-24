"""Fusionar los metadatos de las copias iguales de una foto o un vídeo (ver fusionar.py).

Al fusionar colecciones, de dos copias iguales se queda la de más calidad. Además, la que
se queda se completa con lo que saben las otras, metadato a metadato, quedándose siempre
con el que tenga más información:

  Fotos
    - Ubicación (GPS entero: con altitud, dirección...), cámara (marca, modelo, objetivo,
      exposición...), autor y copyright: los de la otra, solo si la que se queda no los
      tiene. Si es la misma cámara, los datos de la toma que le falten (objetivo, ISO...).
    - Fecha de captura: la de la otra si la que se queda no la trae en sus metadatos y la
      suya es dudosa (la del archivo) o del nombre sin hora y del mismo día (gana la
      hora); una hora fiable sacada del nombre no se pisa. Si es la misma hora y le falta
      la zona horaria, la zona.
    - Descripción y título: el más largo (el que más dice).
    - Etiquetas (álbumes) y personas: las de todas, sin repetir.
    - Valoración: la más alta.
  Vídeos: fecha y ubicación si le faltan, la descripción más larga y todas las palabras
  clave (etiquetas y personas).

Nada se recomprime: en un JPEG solo se reescriben sus segmentos EXIF y XMP (los píxeles
quedan byte a byte) y un vídeo MP4/MOV se remultiplexa sin recodificar. Si la que se queda
se convierte o reduce al entrar, los metadatos van en la conversión. Los demás formatos
(PNG, WebP, GIF...) no se pueden completar sin recomprimirlos: se dejan como están.
"""

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from PIL import Image

from media_utils import MetadatosExtra, ruta_temporal
from metadatos import (
    IFD_EXIF, IFD_GPS, TAG_APERTURA, TAG_AUTOR, TAG_EXPOSICION, TAG_FECHA, TAG_FECHA_DIGITALIZADA,
    TAG_FECHA_ORIGINAL, TAG_FOCAL, TAG_FOCAL_35MM, TAG_ISO, TAG_MARCA, TAG_MODELO, TAG_OBJETIVO,
    TAG_ZONA_DIGITALIZADA, TAG_ZONA_ORIGINAL, jpeg_con_extra, leer_metadatos,
)
from videos import FORMATO_REMUX, argumentos_metadatos, comando_remux, ejecutar_ffmpeg, sondear

IFD_PRINCIPAL = 0
TAG_ZONA, TAG_COPYRIGHT = 0x9010, 33432
TAG_SUBSEG_ORIGINAL, TAG_SUBSEG_DIGITALIZADA = 37521, 37522

# Grupos de etiquetas EXIF que pasan de una copia a otra (ifd, etiqueta)
FECHA = ((IFD_EXIF, TAG_FECHA_ORIGINAL), (IFD_EXIF, TAG_FECHA_DIGITALIZADA),
         (IFD_PRINCIPAL, TAG_FECHA), (IFD_EXIF, TAG_SUBSEG_ORIGINAL),
         (IFD_EXIF, TAG_SUBSEG_DIGITALIZADA))
ZONA = ((IFD_EXIF, TAG_ZONA_ORIGINAL), (IFD_EXIF, TAG_ZONA_DIGITALIZADA), (IFD_EXIF, TAG_ZONA))
CAMARA = ((IFD_PRINCIPAL, TAG_MARCA), (IFD_PRINCIPAL, TAG_MODELO),
          (IFD_EXIF, 42035), (IFD_EXIF, TAG_OBJETIVO), (IFD_EXIF, 42034),   # objetivo
          (IFD_EXIF, TAG_EXPOSICION), (IFD_EXIF, TAG_APERTURA), (IFD_EXIF, TAG_ISO),
          (IFD_EXIF, TAG_FOCAL), (IFD_EXIF, TAG_FOCAL_35MM), (IFD_EXIF, 34850),
          (IFD_EXIF, 37377), (IFD_EXIF, 37378), (IFD_EXIF, 37380), (IFD_EXIF, 37383),
          (IFD_EXIF, 37385), (IFD_EXIF, 41986), (IFD_EXIF, 41987), (IFD_EXIF, 41990))
AUTOR = ((IFD_PRINCIPAL, TAG_AUTOR), (IFD_PRINCIPAL, TAG_COPYRIGHT))
EXTENSIONES_JPEG = {".jpg", ".jpeg"}
FUENTES_DUDOSAS = {"", "archivo", "google_subida"}       # fecha de modificación, de subida...
FUENTES_SIN_HORA = {"nombre", "nombre+hora_archivo"}     # del nombre: el día, quizá sin la hora


@dataclass
class Datos:
    """Lo que dicen los metadatos de una copia (y, en la que se queda, lo que va ganando)."""
    tipo: str                          # 'foto' | 'video'
    fecha: object = None               # de captura, de sus metadatos (no del nombre)
    zona: str = ""
    gps: list = None
    camara: str = ""
    autor: str = ""
    descripcion: str = ""
    titulo: str = ""
    etiquetas: list = field(default_factory=list)
    personas: list = field(default_factory=list)
    valoracion: int = 0
    exif: dict = field(default_factory=dict)   # (ifd, etiqueta) -> valor, de los grupos
    ganado: dict = field(default_factory=dict)  # la que se queda: qué ha ganado -> cuántas
    # La fecha con la que está en su biblioteca (puede no venir de sus metadatos) y de dónde
    fecha_actual: object = None
    fuente_actual: str = ""

    def describir(self) -> list:
        """Lo ganado de todas las otras copias, legible: ["ubicación", "3 etiquetas"]."""
        return _describir(self.ganado)


def leer(ruta: Path, tipo: str, sondeo=sondear) -> Datos:
    """Metadatos de una copia. Lanza excepción si no se puede leer."""
    if tipo == "video":
        info = sondeo(ruta) or {}
        return Datos("video", fecha=info.get("fecha"), gps=info.get("gps"),
                     camara=info.get("camara") or "",
                     descripcion=str(info.get("descripcion") or "").strip(),
                     etiquetas=list(info.get("etiquetas") or []))
    m = leer_metadatos(ruta)
    d = Datos("foto", fecha=m["fecha"] if m["fuente"] == "exif" else None, gps=m["gps"],
              camara=m["camara"], autor=m["autor"], descripcion=m["descripcion"].strip(),
              titulo=m["titulo"].strip(), etiquetas=list(m["etiquetas"]),
              personas=list(m["personas"]), valoracion=m["valoracion"])
    with Image.open(ruta) as im:
        exif = im.getexif()
        sub = exif.get_ifd(IFD_EXIF)
        for ifd, tag in FECHA + ZONA + CAMARA + AUTOR:
            valor = (exif if ifd == IFD_PRINCIPAL else sub).get(tag)
            if valor not in (None, "", b""):
                d.exif[(ifd, tag)] = valor
        if d.gps:   # solo una ubicación válida, y con todo lo que traiga
            for tag, valor in exif.get_ifd(IFD_GPS).items():
                d.exif[(IFD_GPS, tag)] = valor
    d.zona = str(d.exif.get((IFD_EXIF, TAG_ZONA_ORIGINAL)) or "").strip()
    return d


def _nuevas(actuales: list, otras: list) -> list:
    vistos = {x.strip().lower() for x in actuales if x}
    nuevas = []
    for x in otras:
        x = (x or "").strip()
        if x and x.lower() not in vistos:
            vistos.add(x.lower())
            nuevas.append(x)
    return nuevas


def _dice_mas(actual: str, otro: str) -> bool:
    actual, otro = (actual or "").strip(), (otro or "").strip()
    return len(otro) > len(actual) and otro.lower() != actual.lower()


CONTABLES = ("etiqueta", "persona")


def _describir(cuentas: dict) -> list:
    return [f"{n} {clave}{'s' if n != 1 else ''}" if clave in CONTABLES else clave
            for clave, n in cuentas.items()]


def gana_la_fecha(k: Datos, d: Datos) -> bool:
    """¿La fecha de `d` sabe más que la de `k`? Solo si `k` no la trae en sus metadatos."""
    if not d.fecha or k.fecha:
        return False
    actual = k.fecha_actual
    if actual is None or k.fuente_actual in FUENTES_DUDOSAS or actual == d.fecha:
        return True
    return (k.fuente_actual in FUENTES_SIN_HORA and actual.date() == d.fecha.date()
            and (actual.time() == time(0) or k.fuente_actual == "nombre+hora_archivo"))


def aportar(k: Datos, d: Datos, extra: MetadatosExtra) -> list:
    """Lo que la copia `d` sabe y la que se queda (`k`) no: lo añade a `extra` (lo que se
    escribirá en `k`) y lo apunta en `k`. Devuelve qué es, legible ("ubicación"...)."""
    cuentas = {}
    foto = k.tipo == "foto"

    def anotar(clave: str, n: int = 1):
        cuentas[clave] = cuentas.get(clave, 0) + n
        k.ganado[clave] = k.ganado.get(clave, 0) + n

    def pasar(grupo) -> bool:
        nuevas = {t: d.exif[t] for t in grupo if t in d.exif and t not in k.exif}
        extra.exif.update(nuevas)
        k.exif.update(nuevas)
        return bool(nuevas)

    if gana_la_fecha(k, d):
        if foto:
            pasar(FECHA + ZONA)
        else:
            extra.fecha = d.fecha
        k.fecha, k.zona = d.fecha, d.zona
        anotar("fecha")
    elif foto and d.zona and not k.zona and d.fecha == k.fecha and pasar(ZONA):
        k.zona = d.zona
        anotar("zona horaria")
    if d.gps and not k.gps:
        if foto:
            gps = {t: v for t, v in d.exif.items() if t[0] == IFD_GPS}
            extra.exif.update(gps)
            k.exif.update(gps)
        else:
            extra.gps = tuple(d.gps)
        k.gps = d.gps
        anotar("ubicación")
    if foto and d.camara and (not k.camara or k.camara == d.camara) and pasar(CAMARA):
        anotar("datos de la cámara" if k.camara else "cámara")
        k.camara = d.camara
    if foto:
        autor = [t for t in AUTOR if not (t == (IFD_PRINCIPAL, TAG_AUTOR) and k.autor)]
        if pasar(autor):
            anotar("autor")
            k.autor = k.autor or d.autor
    if _dice_mas(k.descripcion, d.descripcion):
        extra.descripcion = k.descripcion = d.descripcion.strip()
        anotar("descripción")
    if foto and _dice_mas(k.titulo, d.titulo):
        extra.titulo = k.titulo = d.titulo.strip()
        anotar("título")
    etiquetas = _nuevas(k.etiquetas, d.etiquetas)
    if etiquetas:
        k.etiquetas += etiquetas
        # En un vídeo las palabras clave se escriben enteras (sustituyen a las suyas)
        extra.etiquetas = extra.etiquetas + etiquetas if foto else list(k.etiquetas)
        anotar("etiqueta", len(etiquetas))
    personas = _nuevas(k.personas, d.personas)
    if personas:
        k.personas += personas
        extra.personas = extra.personas + personas
        anotar("persona", len(personas))
    if foto and d.valoracion > k.valoracion:
        extra.valoracion = k.valoracion = d.valoracion
        anotar("valoración")
    return _describir(cuentas)


def se_puede_completar(ruta: Path, tipo: str, convertir: bool = False) -> bool:
    """¿Se le pueden añadir metadatos sin recomprimir? (O se convierte de todos modos.)"""
    if convertir:
        return True
    extension = ruta.suffix.lower()
    return extension in EXTENSIONES_JPEG if tipo == "foto" else extension in FORMATO_REMUX


def argumentos_video(extra: MetadatosExtra) -> list:
    """-metadata de FFmpeg (`aportar` solo pone fecha y ubicación si le faltan)."""
    return argumentos_metadatos(extra, {})


def escribir(origen: Path, destino: Path, tipo: str, extra: MetadatosExtra):
    """`origen` con los metadatos de `extra` en `destino` (puede ser el mismo archivo: se
    escribe aparte y se sustituye de una vez, con la misma fecha de modificación).
    Devuelve False si no había nada que cambiar. Lanza excepción si no se puede."""
    st = origen.stat()
    tmp = ruta_temporal(destino)
    try:
        if tipo == "foto":
            datos = origen.read_bytes()
            nuevo = jpeg_con_extra(datos, extra)
            if nuevo == datos and origen == destino:
                return False
            tmp.write_bytes(nuevo)
        else:
            ok, error = ejecutar_ffmpeg(comando_remux(origen, tmp, argumentos_video(extra)))
            if not ok or not tmp.exists() or tmp.stat().st_size == 0:
                raise RuntimeError((error or "FFmpeg no generó salida").splitlines()[-1][:300])
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, destino)
    finally:
        tmp.unlink(missing_ok=True)
    return True
