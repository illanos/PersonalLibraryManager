"""Fotos casi idénticas: hash perceptual (dHash) y agrupación de parecidas.

El dHash resume una imagen en 128 bits (gradientes horizontales y verticales de una
versión de 9x8 / 8x9 píxeles en grises). Dos copias de la misma foto —por ejemplo la
de WhatsApp `Sent/` y la de `Images/`, recomprimidas— dan hashes casi iguales aunque
sus bytes sean distintos; dos fotos diferentes difieren en muchos bits.

Solo usa Pillow. Nada se borra: las parecidas se marcan (informe, galería) y, si se
pide, al importar se omite la peor copia de cada grupo.
"""

from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageOps

BITS = 128
UMBRAL = 12          # bits distintos (de 128) para considerar dos fotos "parecidas"
UMBRAL_COPIA = 5     # bits como máximo para tratarla como copia (y poder omitirla)
MIN_DETALLE = 12     # hashes con casi todo 0 o todo 1 (fotos lisas, negras) no se agrupan
TOLERANCIA_PROPORCION = 0.06


def dhash_imagen(im: Image.Image) -> str:
    """dHash de 128 bits (hex de 32 caracteres) de una imagen ya abierta."""
    if im.mode not in ("L", "RGB"):
        im = im.convert("RGBA") if "A" in im.getbands() or "transparency" in im.info else im
        if im.mode == "RGBA":
            fondo = Image.new("RGB", im.size, (255, 255, 255))
            fondo.paste(im, mask=im.getchannel("A"))
            im = fondo
    gris = im.convert("L")
    h = gris.resize((9, 8), Image.Resampling.BILINEAR, reducing_gap=2.0).tobytes()
    v = gris.resize((8, 9), Image.Resampling.BILINEAR, reducing_gap=2.0).tobytes()
    valor = 0
    for fila in range(8):
        for col in range(8):
            valor = (valor << 1) | (h[fila * 9 + col] > h[fila * 9 + col + 1])
    for fila in range(8):
        for col in range(8):
            valor = (valor << 1) | (v[fila * 8 + col] > v[(fila + 1) * 8 + col])
    return f"{valor:032x}"


def dhash(ruta: Path) -> str:
    """dHash de un archivo de imagen (con la rotación EXIF aplicada)."""
    with Image.open(ruta) as im:
        im.draft("RGB", (128, 128))   # JPEG: decodifica ya reducida (muy rápido)
        orientacion = im.getexif().get(274)
        im = im.copy() if orientacion in (None, 1) else ImageOps.exif_transpose(im)
        return dhash_imagen(im)


def distancia(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def con_detalle(h: str) -> bool:
    unos = int(h, 16).bit_count()
    return MIN_DETALLE <= unos <= BITS - MIN_DETALLE


def _proporciones_compatibles(a, b) -> bool:
    if not a or not b:
        return True
    return abs(a - b) / max(a, b) <= TOLERANCIA_PROPORCION


def _trozos(valor: int, umbral: int):
    """Las `umbral + 1` bandas del hash, como claves (banda, bits de la banda)."""
    bandas = umbral + 1
    ancho = -(-BITS // bandas)
    mascara = (1 << ancho) - 1
    return [(b, (valor >> (b * ancho)) & mascara) for b in range(bandas)]


def indice_bandas(valores: dict, umbral: int = UMBRAL) -> dict:
    """{(banda, trozo): [claves]} de {clave: hash como entero}.

    Si dos hashes difieren en `umbral` bits o menos, al menos una de sus `umbral + 1`
    bandas coincide entera (principio del palomar): basta comparar dentro de cada cubo.
    """
    cubos = defaultdict(list)
    for c, v in valores.items():
        for trozo in _trozos(v, umbral):
            cubos[trozo].append(c)
    return cubos


def candidatos(cubos: dict, valor: int, umbral: int = UMBRAL) -> set:
    """Claves de `indice_bandas` que pueden estar a `umbral` bits o menos de `valor`."""
    encontrados = set()
    for trozo in _trozos(valor, umbral):
        encontrados.update(cubos.get(trozo, ()))
    return encontrados


def agrupar(hashes: dict, proporciones: dict = None, umbral: int = UMBRAL) -> list:
    """Grupos (listas de claves, con 2 o más) de elementos parecidos entre sí.

    `hashes` es {clave: dhash}; `proporciones` (opcional) {clave: ancho/alto} evita unir
    una foto con un recorte suyo. Solo se comparan los que comparten alguna banda
    (`indice_bandas`).
    """
    proporciones = proporciones or {}
    valores = {c: int(h, 16) for c, h in hashes.items() if h and con_detalle(h)}
    padre = {c: c for c in valores}

    def raiz(c):
        while padre[c] != c:
            padre[c] = padre[padre[c]]
            c = padre[c]
        return c

    # Sin apuntar los pares ya comparados: repetir la comparación de dos hashes que
    # comparten varias bandas cuesta menos que llevar la cuenta (con 43.000 fotos reales,
    # 12 s en vez de 92), y unirlos dos veces no cambia nada
    for miembros in indice_bandas(valores, umbral).values():
        if len(miembros) < 2:
            continue
        hs = [valores[c] for c in miembros]
        for i in range(len(miembros) - 1):
            a, ha = miembros[i], hs[i]
            for j in range(i + 1, len(miembros)):
                if (ha ^ hs[j]).bit_count() <= umbral:
                    b = miembros[j]
                    if _proporciones_compatibles(proporciones.get(a), proporciones.get(b)):
                        ra, rb = raiz(a), raiz(b)
                        if ra != rb:
                            padre[rb] = ra

    grupos = {}
    for c in valores:
        grupos.setdefault(raiz(c), []).append(c)
    return [g for g in grupos.values() if len(g) > 1]


def es_copia(h: str, h_mejor: str, fecha_exif=None, fecha_exif_mejor=None) -> bool:
    """¿Es `h` una copia recomprimida de la mejor (y no otra toma de una ráfaga)?

    Para *omitir* una foto no basta con que sea parecida: las ráfagas también lo son
    (1-12 bits de diferencia en fotos reales) y cada toma es distinta. Solo se considera
    copia si está muy cerca de la mejor (≤ UMBRAL_COPIA bits, lo típico de reenviar por
    WhatsApp) y no tiene una fecha EXIF propia distinta: una toma de cámara la tiene,
    una copia de WhatsApp o de Instagram no.
    """
    if distancia(h, h_mejor) > UMBRAL_COPIA:
        return False
    return fecha_exif is None or fecha_exif == fecha_exif_mejor


def calidad(ancho, alto, tamano, fuente: str = "") -> tuple:
    """Clave para elegir la mejor copia: más píxeles, luego con EXIF, luego más bytes."""
    return ((ancho or 0) * (alto or 0), fuente == "exif", tamano or 0)
