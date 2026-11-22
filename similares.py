"""Fotos casi idénticas: hash perceptual (dHash) y agrupación de parecidas.

El dHash resume una imagen en 128 bits (gradientes horizontales y verticales de una
versión de 9x8 / 8x9 píxeles en grises). Dos copias de la misma foto —por ejemplo la
de WhatsApp `Sent/` y la de `Images/`, recomprimidas— dan hashes casi iguales aunque
sus bytes sean distintos; dos fotos diferentes difieren en muchos bits.

Solo usa Pillow. Nada se borra: las parecidas se marcan (informe, galería) y, si se
pide, al importar se omite la peor copia de cada grupo.
"""

from pathlib import Path

from PIL import Image, ImageOps

BITS = 128
UMBRAL = 12          # bits distintos (de 128) para considerar dos fotos "parecidas"
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


def agrupar(hashes: dict, proporciones: dict = None, umbral: int = UMBRAL) -> list:
    """Grupos (listas de claves, con 2 o más) de elementos parecidos entre sí.

    `hashes` es {clave: dhash}; `proporciones` (opcional) {clave: ancho/alto} evita unir
    una foto con un recorte suyo. Divide el hash en `umbral + 1` bandas: si dos hashes
    difieren en `umbral` bits o menos, al menos una banda coincide entera (principio
    del palomar), así que solo se comparan los que comparten alguna banda.
    """
    proporciones = proporciones or {}
    claves = [c for c, h in hashes.items() if h and con_detalle(h)]
    valores = {c: int(hashes[c], 16) for c in claves}
    bandas = umbral + 1
    ancho_banda = -(-BITS // bandas)

    padre = {c: c for c in claves}

    def raiz(c):
        while padre[c] != c:
            padre[c] = padre[padre[c]]
            c = padre[c]
        return c

    cubos = {}
    for c in claves:
        v = valores[c]
        for b in range(bandas):
            trozo = (v >> (b * ancho_banda)) & ((1 << ancho_banda) - 1)
            cubos.setdefault((b, trozo), []).append(c)

    comparados = set()
    for miembros in cubos.values():
        if len(miembros) < 2:
            continue
        for i, a in enumerate(miembros):
            for b in miembros[i + 1:]:
                par = (a, b)
                if par in comparados:
                    continue
                comparados.add(par)
                if ((valores[a] ^ valores[b]).bit_count() <= umbral
                        and _proporciones_compatibles(proporciones.get(a), proporciones.get(b))):
                    ra, rb = raiz(a), raiz(b)
                    if ra != rb:
                        padre[rb] = ra

    grupos = {}
    for c in claves:
        grupos.setdefault(raiz(c), []).append(c)
    return [g for g in grupos.values() if len(g) > 1]


def calidad(ancho, alto, tamano, fuente: str = "") -> tuple:
    """Clave para elegir la mejor copia: más píxeles, luego con EXIF, luego más bytes."""
    return ((ancho or 0) * (alto or 0), fuente == "exif", tamano or 0)
