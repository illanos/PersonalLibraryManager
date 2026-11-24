"""Google Fotos (Google Takeout): empareja cada foto y vídeo con su JSON de metadatos.

Un Takeout de Google Fotos trae, junto a cada archivo, un JSON con lo que Google sabe
de él y que muchas veces no va dentro del archivo (fecha de las fotos sin EXIF, GPS,
descripción, personas, álbumes):

    Google Fotos/Fotos del 2019/IMG_20190422_183015.jpg
    Google Fotos/Fotos del 2019/IMG_20190422_183015.jpg.supplemental-metadata.json
    Google Fotos/Boda Moi/metadatos.json                    título del álbum
    Google Fotos/Boda Moi/IMG_20190422_183015.jpg (+ JSON)  la misma foto, en el álbum

`IndiceTakeout` lee todos los JSON una vez y responde, para cada archivo:
  - metadatos(ruta): fecha de captura, GPS, descripción, personas, favorita y los álbumes
    en los que está (aunque en la carpeta del álbum solo venga el JSON y no la foto);
  - omitir(ruta): las versiones «-editada» cuyo original está al lado (se importa solo
    el original) y lo que Google marca como enviado a la papelera.
Los JSON no se copian a la biblioteca: lo que dicen se graba dentro de cada foto y vídeo.

Nombres que se reconocen (Google los ha ido cambiando y recorta los largos):
    foto.jpg            foto.jpg.supplemental-metadata.json | foto.jpg.json
    foto(1).jpg         foto.jpg.supplemental-metadata(1).json | foto.jpg(1).json
    foto-editada.jpg    el JSON de foto.jpg
    07_04_13 - 1.jpg    07_04_13 - 1.supplemental-metadata.json (título sin extensión)
    PXL_….MP            el de PXL_….MP.jpg: es el clip de una foto con movimiento; se
                        importa como vídeo .mp4 con la fecha (y el nombre) de su foto
    IMG_1.MP4           si no trae JSON y hay IMG_1.HEIC/.jpg al lado (Live Photo de
                        iPhone, foto con movimiento de Samsung): igual que el anterior
    nombres largos      JSON recortado (foto_muy_larga.jpg.supplemen.json) o su "title"
"""

import collections
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .media_utils import CARPETAS_EXCLUIDAS, MetadatosExtra, fecha_plausible

SUFIJO = ".supplemental-metadata"
EXTENSIONES_CLIP = {".mp"}   # PXL_….MP junto a PXL_….MP.jpg
# Live Photos / fotos con movimiento de Samsung: IMG_1.HEIC + IMG_1.MP4 (sin JSON propio)
EXTENSIONES_VIDEO_CLIP = {".mp4", ".mov", ".m4v"}
EXTENSIONES_FOTO_CLIP = {".jpg", ".jpeg", ".heic", ".heif"}
FUENTE_CLIP = "foto"         # fecha del clip = la de su foto
FUENTE_SUBIDA = "google_subida"   # sin fecha de captura en el JSON: la de subida (dudosa)
MAX_JSON = 4 * 1024 * 1024   # un JSON de metadatos ocupa ~1 KB

_RE_CONTADOR = re.compile(r"^(.*)\((\d+)\)$")
# Sufijo de las copias editadas según el idioma de la cuenta
_RE_EDITADA = re.compile(
    r"^(.*)-(editada|editado|edited|bearbeitet|modifié|modifiée|modificata|modificato|"
    r"bewerkt|editat)(\(\d+\))?$", re.IGNORECASE)
_RE_JSON = re.compile(r"^(.*?)(\(\d+\))?\.json$", re.IGNORECASE)
# Álbumes sin nombre útil: los automáticos de Picasa ("07/04/13", "2014-03-30")
_RE_TITULO_FECHA = re.compile(r"^[\d\s/._-]+$")
TITULOS_VACIOS = {"sin título", "sin titulo", "untitled", "ohne titel", "sans titre",
                  "senza titolo"}


def _clave(ruta) -> str:
    return os.path.normcase(os.path.abspath(str(ruta)))


def _leer_json(ruta: Path):
    try:
        if ruta.stat().st_size > MAX_JSON:
            return None
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def _es_de_archivo(datos: dict) -> bool:
    """JSON de una foto o vídeo (el del álbum, metadatos.json, no trae estas fechas)."""
    return "photoTakenTime" in datos or "creationTime" in datos


def nombre_album(titulo, carpeta: str):
    """Nombre del álbum para usarlo como etiqueta, o None si no aporta nada."""
    titulo = str(titulo or "").strip() or carpeta.strip()
    if not titulo or titulo.lower() in TITULOS_VACIOS or _RE_TITULO_FECHA.match(titulo):
        return None
    return titulo


def bases_json(nombre: str) -> list:
    """[(archivo cuyo JSON se busca, contador)] de más a menos probable.

    'foto(1).jpg' -> [('foto(1).jpg', ''), ('foto.jpg', '(1)')]
    'foto-editada.jpg' -> [..., ('foto.jpg', '')];  'PXL_1.MP' -> [..., ('PXL_1.MP.jpg', '')]
    """
    stem, ext = os.path.splitext(nombre)
    bases = [(nombre, "")]
    m = _RE_CONTADOR.match(stem)
    if m:
        bases.append((m.group(1) + ext, f"({m.group(2)})"))
    e = _RE_EDITADA.match(stem)
    if e:
        bases.append((e.group(1) + ext, e.group(3) or ""))
    if ext.lower() in EXTENSIONES_CLIP:
        bases.append((nombre + ".jpg", ""))
    return bases


def nombres_json(nombre: str) -> list:
    """Nombres posibles del JSON de `nombre`, de más a menos probable."""
    nombres = []
    for base, contador in bases_json(nombre):
        sin_ext = os.path.splitext(base)[0]
        nombres += [f"{base}{SUFIJO}{contador}.json", f"{base}{contador}.json",
                    f"{sin_ext}{SUFIJO}{contador}.json", f"{sin_ext}{contador}.json"]
    return list(dict.fromkeys(nombres))


def original_de_editada(nombre: str):
    """'foto-editada.jpg' -> 'foto' (nombre sin extensión del original); si no, None."""
    e = _RE_EDITADA.match(os.path.splitext(nombre)[0])
    return e.group(1) + (e.group(3) or "") if e else None


def _fecha(marca):
    """photoTakenTime {"timestamp": "1365258955"} (UTC) -> (hora local, "+02:00")."""
    try:
        segundos = int((marca or {}).get("timestamp") or 0)
        if segundos <= 0:
            return None, ""
        local = datetime.fromtimestamp(segundos)
        desfase = local.astimezone().strftime("%z")
    except (TypeError, ValueError, OverflowError, OSError, AttributeError):
        return None, ""
    if not fecha_plausible(local):
        return None, ""
    return local, f"{desfase[:3]}:{desfase[3:]}" if len(desfase) == 5 else ""


def _gps(geo):
    """geoData -> (lat, lon, altitud o None); None si falta (Google pone 0.0, 0.0)."""
    try:
        lat, lon = float(geo.get("latitude") or 0), float(geo.get("longitude") or 0)
        altitud = float(geo.get("altitude") or 0) or None
    except (TypeError, ValueError, AttributeError):
        return None
    if (lat == 0 and lon == 0) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return (round(lat, 7), round(lon, 7), altitud)


def _unicos(valores) -> list:
    vistos, resultado = set(), []
    for valor in valores:
        valor = str(valor or "").strip()
        if valor and valor.lower() not in vistos:
            vistos.add(valor.lower())
            resultado.append(valor)
    return resultado


def _clave_album(datos: dict):
    """Identifica la misma foto en distintas carpetas: título + fecha de captura."""
    titulo = str(datos.get("title") or "").strip().lower()
    marca = str((datos.get("photoTakenTime") or {}).get("timestamp") or "")
    return (titulo, marca) if titulo and marca else None


class IndiceTakeout:
    """Metadatos de los JSON de un Takeout de Google Fotos, por archivo (ver el módulo)."""

    extensiones_video = EXTENSIONES_CLIP   # los clips .MP se importan como vídeos

    def __init__(self, raiz: Path, hilos: int = 16):
        self.raiz = Path(raiz)
        self._datos = {}            # ruta del JSON -> contenido
        self._json_de = {}          # archivo -> ruta de su JSON
        self._album_de = {}         # carpeta -> nombre del álbum (None si no aporta)
        self._albumes = collections.defaultdict(set)   # _clave_album -> álbumes
        self._omitir = {}           # archivo -> motivo
        self._foto_de_clip = {}     # clip .MP -> su foto .MP.jpg
        self.cuenta = collections.Counter()
        self._construir(hilos)

    # --- construcción ---

    def _construir(self, hilos: int):
        carpetas = []
        for raiz, subcarpetas, archivos in os.walk(self.raiz):
            subcarpetas[:] = [c for c in subcarpetas
                              if c not in CARPETAS_EXCLUIDAS and not c.startswith(".")]
            carpetas.append((Path(raiz), [a for a in archivos if not a.startswith("._")]))
        rutas = [c / a for c, archivos in carpetas for a in archivos
                 if a.lower().endswith(".json")]
        with ThreadPoolExecutor(max(1, hilos)) as pool:   # en un disco USB, abrir cuesta
            for ruta, datos in zip(rutas, pool.map(_leer_json, rutas)):
                if datos is not None:
                    self._datos[ruta] = datos
        self.cuenta["json"] = len(self._datos)
        for carpeta, archivos in carpetas:
            self._indexar_carpeta(carpeta, archivos)

    def _indexar_carpeta(self, carpeta: Path, archivos: list):
        jsons, es_album, album = {}, False, None
        for nombre in archivos:
            datos = self._datos.get(carpeta / nombre)
            if datos is None:
                continue
            if _es_de_archivo(datos):
                jsons[nombre.lower()] = carpeta / nombre
            elif (carpeta != self.raiz and isinstance(datos.get("title"), str)
                  and not es_album):
                es_album, album = True, nombre_album(datos.get("title"), carpeta.name)
        if es_album:
            self._album_de[_clave(carpeta)] = album
            if album:
                self.cuenta["albumes"] += 1
                for ruta in jsons.values():
                    clave = _clave_album(self._datos[ruta])
                    if clave:
                        self._albumes[clave].add(album)

        medios = [n for n in archivos if not n.lower().endswith(".json")]
        nombres = {n.lower() for n in medios}
        stems = {os.path.splitext(n)[0].lower() for n in medios}
        usados, pendientes = set(), []
        for nombre in medios:
            ruta = carpeta / nombre
            original = original_de_editada(nombre)
            if original and original.lower() in stems:
                self._omitir[_clave(ruta)] = f"versión editada de {original} (se importa el original)"
                self.cuenta["editadas"] += 1
            if os.path.splitext(nombre)[1].lower() in EXTENSIONES_CLIP:
                if f"{nombre}.jpg".lower() in nombres:
                    self._foto_de_clip[_clave(ruta)] = carpeta / next(
                        n for n in medios if n.lower() == f"{nombre}.jpg".lower())
                self.cuenta["clips"] += 1
            encontrado = next((jsons[j.lower()] for j in nombres_json(nombre)
                               if j.lower() in jsons), None)
            if encontrado:
                self._json_de[_clave(ruta)] = encontrado
                usados.add(encontrado)
            else:
                pendientes.append(nombre)
        # Live Photo de iPhone (IMG_1.HEIC + IMG_1.MP4) o foto con movimiento de Samsung
        # (X.jpg + X.MP4): el vídeo no trae JSON; usa el de su foto y su fecha
        fotos = {os.path.splitext(n)[0].lower(): carpeta / n for n in medios
                 if os.path.splitext(n)[1].lower() in EXTENSIONES_FOTO_CLIP}
        for nombre in list(pendientes):
            stem, ext = os.path.splitext(nombre)
            foto = fotos.get(stem.lower()) if ext.lower() in EXTENSIONES_VIDEO_CLIP else None
            if foto is not None and _clave(foto) in self._json_de:
                self._json_de[_clave(carpeta / nombre)] = self._json_de[_clave(foto)]
                self._foto_de_clip[_clave(carpeta / nombre)] = foto
                self.cuenta["clips"] += 1
                pendientes.remove(nombre)
        libres = [r for r in jsons.values() if r not in usados]
        for nombre in pendientes:
            encontrado = self._json_recortado(nombre, libres) or self._json_por_titulo(nombre, libres)
            if encontrado:
                self._json_de[_clave(carpeta / nombre)] = encontrado
                libres.remove(encontrado)
            else:
                self.cuenta["sin_json"] += 1
        for ruta in jsons.values():
            if self._datos[ruta].get("trashed") is True:
                for archivo, j in list(self._json_de.items()):
                    if j == ruta:
                        self._omitir[archivo] = "en la papelera de Google Fotos"

    @staticmethod
    def _json_recortado(nombre: str, libres: list):
        """Google recorta los nombres largos: foto_muy_larga.jpg.supplemen.json."""
        mejor = None
        for base, contador in bases_json(nombre):
            objetivo = f"{base}{SUFIJO}".lower()
            minimo = len(os.path.splitext(base)[0])
            for ruta in libres:
                m = _RE_JSON.match(ruta.name)
                prefijo = m.group(1).lower() if m else ""
                if ((m.group(2) or "") == contador and len(prefijo) > minimo
                        and objetivo.startswith(prefijo)
                        and (mejor is None or len(prefijo) > mejor[0])):
                    mejor = (len(prefijo), ruta)
            if mejor:
                return mejor[1]
        return None

    def _json_por_titulo(self, nombre: str, libres: list):
        """Último recurso: el "title" del JSON es el nombre original del archivo."""
        for base, _ in bases_json(nombre)[:2]:
            for ruta in libres:
                if str(self._datos[ruta].get("title") or "").strip().lower() == base.lower():
                    return ruta
        return None

    # --- consultas ---

    def omitir(self, ruta: Path):
        """Motivo para no importar `ruta`, o None."""
        return self._omitir.get(_clave(ruta))

    def json_de(self, ruta: Path):
        return self._json_de.get(_clave(ruta))

    def metadatos(self, ruta: Path):
        """MetadatosExtra de `ruta` según su JSON y sus álbumes, o None si no hay nada."""
        album = self._album_de.get(_clave(Path(ruta).parent))
        ruta_json = self._json_de.get(_clave(ruta))
        if ruta_json is None:
            return MetadatosExtra(etiquetas=[album]) if album else None
        datos = self._datos[ruta_json]
        fecha, zona = _fecha(datos.get("photoTakenTime"))
        fuente, dudosa = "google", False
        if fecha is None:
            # Sin fecha de captura ("timestamp": "0"): la de subida, mejor que la del archivo
            # (la de cuando se descomprimió el Takeout). Se marca como dudosa y no se graba.
            fecha, zona = _fecha(datos.get("creationTime"))
            fuente, dudosa = FUENTE_SUBIDA, fecha is not None
        clave = _clave_album(datos)
        albumes = ([album] if album else []) + sorted(self._albumes.get(clave, ()) if clave else ())
        personas = [p.get("name") for p in datos.get("people") or [] if isinstance(p, dict)]
        extra = MetadatosExtra(
            fecha=fecha, zona=zona, fuente=fuente, fecha_dudosa=dudosa,
            gps=_gps(datos.get("geoData")) or _gps(datos.get("geoDataExif")),
            descripcion=str(datos.get("description") or "").strip(),
            etiquetas=_unicos(albumes), personas=_unicos(personas),
            favorita=datos.get("favorited") is True)
        foto = self._foto_de_clip.get(_clave(ruta))
        if foto is not None:
            fecha_foto = _fecha_exif(foto)
            if fecha_foto:
                extra.fecha, extra.zona, extra.fecha_dudosa = fecha_foto, "", False
                extra.fuente, extra.fecha_prioritaria = FUENTE_CLIP, True
        return extra

    def resumen(self) -> str:
        c = self.cuenta
        lineas = [f"  JSON de Google leídos      : {c['json']}",
                  f"  Archivos con su JSON       : {len(self._json_de)}",
                  f"  Archivos sin JSON          : {c['sin_json']}",
                  f"  Álbumes (como etiquetas)   : {c['albumes']}"]
        if c["editadas"]:
            lineas.append(f"  Editadas (va el original)  : {c['editadas']}")
        if c["clips"]:
            lineas.append(f"  Clips de fotos con movim.  : {c['clips']}")
        return "\n".join(lineas)


def _fecha_exif(foto: Path):
    """Fecha EXIF de la foto de un clip (para que ambos se llamen igual), o None."""
    try:
        from .metadatos import leer_metadatos
        datos = leer_metadatos(foto, completo=False)
    except Exception:
        return None
    return datos["fecha"] if datos["fuente"] == "exif" else None
