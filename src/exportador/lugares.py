"""Lugares a partir del GPS, sin conexión (geocodificación inversa local).

Usa las ciudades de más de 15.000 habitantes de GeoNames (licencia CC BY 4.0,
https://www.geonames.org), que se descargan **una sola vez** con

    python -m exportador galeria <biblioteca> --descargar-lugares

y se guardan reducidas en `datos/lugares.tsv` (~1 MB). Si el archivo no está, la
galería funciona igual y solo avisa de cómo obtener los lugares.

La búsqueda usa una rejilla de 1°: para cada coordenada solo se miran las ciudades de
las celdas vecinas, así que miles de fotos se resuelven en un instante.
"""

import io
import math
import zipfile

from .descargas import CARPETA_DATOS, descargar

ARCHIVO = CARPETA_DATOS / "lugares.tsv"
URL_BASE = "https://download.geonames.org/export/dump/"
DISTANCIA_MAX_KM = 40

# Nombres en español de los países más habituales (GeoNames los trae en inglés)
PAISES_ES = {
    "ES": "España", "PT": "Portugal", "FR": "Francia", "IT": "Italia", "DE": "Alemania",
    "GB": "Reino Unido", "IE": "Irlanda", "NL": "Países Bajos", "BE": "Bélgica",
    "CH": "Suiza", "AT": "Austria", "US": "Estados Unidos", "MX": "México",
    "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "PE": "Perú", "MA": "Marruecos",
    "GR": "Grecia", "DK": "Dinamarca", "SE": "Suecia", "NO": "Noruega", "FI": "Finlandia",
    "PL": "Polonia", "CZ": "Chequia", "HU": "Hungría", "TR": "Turquía", "JP": "Japón",
    "CN": "China", "BR": "Brasil", "CA": "Canadá", "AD": "Andorra", "GI": "Gibraltar",
}


def preparar(origen_zip: bytes, admin1: str, paises: str) -> list:
    """Filas (nombre, lat, lon, región, país) a partir de los archivos de GeoNames."""
    regiones = {}
    for linea in admin1.splitlines():
        partes = linea.split("\t")
        if len(partes) >= 2:
            regiones[partes[0]] = partes[1]
    nombres_pais = {}
    for linea in paises.splitlines():
        if linea.startswith("#"):
            continue
        partes = linea.split("\t")
        if len(partes) > 4:
            nombres_pais[partes[0]] = PAISES_ES.get(partes[0], partes[4])
    filas = []
    with zipfile.ZipFile(io.BytesIO(origen_zip)) as z:
        nombre = next(n for n in z.namelist() if n.endswith(".txt"))
        for linea in io.TextIOWrapper(z.open(nombre), encoding="utf-8"):
            c = linea.rstrip("\n").split("\t")
            if len(c) < 11:
                continue
            pais = c[8]
            filas.append((c[1], round(float(c[4]), 4), round(float(c[5]), 4),
                          regiones.get(f"{pais}.{c[10]}", ""), nombres_pais.get(pais, pais)))
    return filas


def descargar_lugares():
    """Descarga GeoNames una vez y deja `datos/lugares.tsv` (si ya está, no hace nada)."""
    if ARCHIVO.exists():
        print(f"Lugares ya descargados en {ARCHIVO} (bórralo para volver a descargarlos).")
        return
    print("Descargando ciudades de GeoNames (CC BY 4.0) para mostrar lugares sin conexión:")
    tmp = CARPETA_DATOS / "_geonames"
    archivos = {n: descargar(URL_BASE + n, tmp / n)
                for n in ("cities15000.zip", "admin1CodesASCII.txt", "countryInfo.txt")}
    filas = preparar(archivos["cities15000.zip"].read_bytes(),
                     archivos["admin1CodesASCII.txt"].read_text(encoding="utf-8"),
                     archivos["countryInfo.txt"].read_text(encoding="utf-8"))
    guardar(filas)
    for ruta in archivos.values():
        ruta.unlink(missing_ok=True)
    tmp.rmdir()
    print(f"Lugares listos: {len(filas)} ciudades en {ARCHIVO}")


def guardar(filas: list, ruta=ARCHIVO):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".part")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Datos de GeoNames (https://www.geonames.org), licencia CC BY 4.0\n")
        for fila in filas:
            f.write("\t".join(str(x) for x in fila) + "\n")
    tmp.replace(ruta)


class Geocodificador:
    def __init__(self, ruta=ARCHIVO):
        self.celdas = {}
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                if linea.startswith("#"):
                    continue
                nombre, lat, lon, region, pais = linea.rstrip("\n").split("\t")
                lat, lon = float(lat), float(lon)
                clave = (math.floor(lat), math.floor(lon))
                self.celdas.setdefault(clave, []).append((lat, lon, nombre, region, pais))

    @staticmethod
    def _km(lat1, lon1, lat2, lon2) -> float:
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = p2 - p1, math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 6371 * 2 * math.asin(math.sqrt(a))

    def buscar(self, lat: float, lon: float):
        """{'ciudad', 'region', 'pais'} de la ciudad más cercana (≤ 40 km) o None."""
        mejor, mejor_km = None, DISTANCIA_MAX_KM
        clat, clon = math.floor(lat), math.floor(lon)
        for dlat in (-1, 0, 1):
            for dlon in (-1, 0, 1):
                celda = (clat + dlat, (clon + dlon + 180) % 360 - 180)
                for c in self.celdas.get(celda, ()):
                    km = self._km(lat, lon, c[0], c[1])
                    if km < mejor_km:
                        mejor, mejor_km = c, km
        if mejor is None:
            return None
        return {"ciudad": mejor[2], "region": mejor[3], "pais": mejor[4]}


def cargar():
    """Geocodificador listo, o None si no se ha descargado el archivo de lugares."""
    if not ARCHIVO.exists():
        return None
    try:
        return Geocodificador()
    except (OSError, ValueError):
        return None


def asignar_lugares(elementos: list, geo) -> int:
    """Pone 'lugar' y 'pais' a los elementos con GPS que aún no lo tengan. Devuelve cuántos."""
    nuevos = 0
    for e in elementos:
        if not e.get("gps") or "lugar" in e:
            continue
        encontrado = geo.buscar(*e["gps"])
        nuevos += 1
        if encontrado:
            e["lugar"] = encontrado["ciudad"]
            e["pais"] = encontrado["pais"]
            if encontrado["region"]:
                e["region"] = encontrado["region"]
        else:
            e["lugar"] = ""   # calculado: lejos de cualquier ciudad (no se repite)
    return nuevos
