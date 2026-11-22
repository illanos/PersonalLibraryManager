"""Caras: detección local y agrupación de caras parecidas para nombrarlas en la galería.

Todo se hace en este equipo, sin servicios externos. Es opcional y se activa con
`python main.py galeria <biblioteca> --caras`. Necesita OpenCV:

    pip install opencv-python

- Con los modelos YuNet (detección) y SFace (reconocimiento) de OpenCV Zoo, que se
  descargan una vez con `--descargar-modelos-caras` (~38 MB en `datos/modelos/`), la
  agrupación es buena.
- Sin ellos se usa el detector Haar que trae OpenCV y un descriptor HOG: detecta
  caras de frente y solo agrupa bien fotos casi iguales (se avisa).

Resultados en `<biblioteca>/_galeria/caras.sqlite`: cada foto se analiza una sola vez
(mientras no cambie su tamaño ni su fecha), y las caras nuevas se asignan al grupo
más parecido o abren uno nuevo. Los nombres que se ponen en la galería se guardan en
`_galeria/personas.json` ({grupo: nombre}); dar el mismo nombre a dos grupos los une.
"""

import json
import math
import sqlite3
from array import array
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from descargas import CARPETA_DATOS, descargar
from media_utils import CARPETA_GALERIA

CARPETA_MODELOS = CARPETA_DATOS / "modelos"
URL_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models/"
MODELOS = {
    "yunet": ("face_detection_yunet/face_detection_yunet_2023mar.onnx",
              "face_detection_yunet_2023mar.onnx"),
    "sface": ("face_recognition_sface/face_recognition_sface_2021dec.onnx",
              "face_recognition_sface_2021dec.onnx"),
}
LADO_ANALISIS = 1280      # se analiza una versión reducida (rápido y suficiente)
MIN_CARA = 40             # px (en la versión reducida)
UMBRAL = {"sface": 0.40, "hog": 0.80}   # similitud coseno mínima para el mismo grupo
VERSION = 1

ESQUEMA = """
CREATE TABLE IF NOT EXISTS analizadas (src TEXT PRIMARY KEY, bytes INTEGER, mtime INTEGER,
                                       motor TEXT);
CREATE TABLE IF NOT EXISTS caras (id INTEGER PRIMARY KEY, src TEXT, x REAL, y REAL, w REAL,
                                  h REAL, vector BLOB, grupo INTEGER);
CREATE INDEX IF NOT EXISTS idx_caras_src ON caras (src);
CREATE TABLE IF NOT EXISTS grupos (id INTEGER PRIMARY KEY, centroide BLOB, n INTEGER,
                                   motor TEXT);
"""


def disponible() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


MENSAJE_SIN_OPENCV = ("AVISO: se omiten las caras porque falta OpenCV. Para activarlas:\n"
                      "    pip install opencv-python")


def descargar_modelos():
    print("Descargando los modelos de caras de OpenCV Zoo (YuNet y SFace):")
    for ruta_remota, nombre in MODELOS.values():
        destino = CARPETA_MODELOS / nombre
        if not destino.exists():
            descargar(URL_ZOO + ruta_remota, destino)
    print("Modelos de caras listos.")


def ruta_nombres(carpeta: Path) -> Path:
    return carpeta / CARPETA_GALERIA / "personas.json"


def leer_nombres(carpeta: Path) -> dict:
    try:
        datos = json.loads(ruta_nombres(carpeta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(datos, dict):
        return {}
    return {str(k): v.strip() for k, v in datos.items()
            if isinstance(v, str) and v.strip() and str(k).isdigit()}


# ----------------------------- Motores -----------------------------

class Motor:
    """Detecta las caras de una foto: [(x, y, w, h, vector)], caja en fracciones (0-1)."""
    nombre = ""

    def caras(self, ruta: Path) -> list:
        raise NotImplementedError


class MotorOpenCV(Motor):
    def __init__(self):
        import cv2
        self.cv2 = cv2
        yunet = CARPETA_MODELOS / MODELOS["yunet"][1]
        sface = CARPETA_MODELOS / MODELOS["sface"][1]
        self._local = threading.local()   # los modelos de OpenCV no son seguros entre hilos
        self.con_modelos = yunet.exists() and sface.exists()
        self.nombre = "sface" if self.con_modelos else "hog"
        self._yunet, self._sface = str(yunet), str(sface)

    def _modelos(self):
        cv2, local = self.cv2, self._local
        if not hasattr(local, "detector"):
            if self.con_modelos:
                local.detector = cv2.FaceDetectorYN.create(self._yunet, "", (320, 320), 0.85)
                local.reconocedor = cv2.FaceRecognizerSF.create(self._sface, "")
            else:
                local.detector = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
                local.hog = cv2.HOGDescriptor((64, 64), (16, 16), (8, 8), (8, 8), 9)
        return local

    def caras(self, ruta: Path) -> list:
        import numpy as np
        cv2, m = self.cv2, self._modelos()
        imagen = _imagen_bgr(ruta)
        alto, ancho = imagen.shape[:2]
        resultado = []
        if self.con_modelos:
            m.detector.setInputSize((ancho, alto))
            _, detectadas = m.detector.detect(imagen)
            for fila in detectadas if detectadas is not None else []:
                x, y, w, h = (float(v) for v in fila[:4])
                if min(w, h) < MIN_CARA:
                    continue
                alineada = m.reconocedor.alignCrop(imagen, fila)
                vector = m.reconocedor.feature(alineada).flatten().astype(np.float32)
                resultado.append((x, y, w, h, vector))
        else:
            gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
            for x, y, w, h in m.detector.detectMultiScale(
                    gris, scaleFactor=1.1, minNeighbors=6, minSize=(MIN_CARA, MIN_CARA)):
                recorte = cv2.equalizeHist(cv2.resize(gris[y:y + h, x:x + w], (64, 64)))
                vector = m.hog.compute(recorte).flatten().astype(np.float32)
                resultado.append((float(x), float(y), float(w), float(h), vector))
        return [(x / ancho, y / alto, w / ancho, h / alto, v) for x, y, w, h, v in resultado]


def _imagen_bgr(ruta: Path):
    """Foto (con la rotación EXIF aplicada y reducida) como matriz BGR para OpenCV."""
    import numpy as np
    from PIL import Image, ImageOps
    with Image.open(ruta) as im:
        im.draft("RGB", (LADO_ANALISIS, LADO_ANALISIS))
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((LADO_ANALISIS, LADO_ANALISIS))
        return np.asarray(im)[:, :, ::-1].copy()


# ----------------------------- Agrupación -----------------------------

# Con OpenCV siempre hay numpy (rápido); sin él (tests, motores propios) se usa array.
try:
    import numpy as _np
except ImportError:
    _np = None


def _vector(valores):
    if _np is not None:
        return _np.asarray(valores, dtype=_np.float32)
    return array("f", (float(x) for x in valores))


def _de_bytes(datos: bytes):
    if _np is not None:
        return _np.frombuffer(datos, dtype=_np.float32).copy()
    v = array("f")
    v.frombytes(datos)
    return v


def _producto(a, b) -> float:
    if _np is not None:
        return float(_np.dot(a, b))
    return sum(x * y for x, y in zip(a, b))


def _normalizar(v):
    v = _vector(v)
    n = math.sqrt(_producto(v, v))
    if not n:
        return v
    return v / n if _np is not None else array("f", (x / n for x in v))


def _media(centroide, n: int, v):
    """Centroide tras añadir `v` a un grupo de `n` caras (normalizado)."""
    if _np is not None:
        return _normalizar((centroide * n + v) / (n + 1))
    return _normalizar([(c * n + x) / (n + 1) for c, x in zip(centroide, v)])


class Caras:
    """Caché de caras de una galería y agrupación incremental."""

    def __init__(self, carpeta: Path, motor: Motor):
        self.carpeta, self.motor = carpeta, motor
        ruta = carpeta / CARPETA_GALERIA / "caras.sqlite"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(ruta)
        self.db.executescript(ESQUEMA)
        self.db.execute(f"PRAGMA user_version = {VERSION}")
        self._grupos = None

    def cerrar(self):
        self.db.commit()
        self.db.close()

    def _cargar_grupos(self):
        self._grupos = {gid: (_de_bytes(c), n)
                        for gid, c, n in self.db.execute(
                            "SELECT id, centroide, n FROM grupos WHERE motor = ?",
                            (self.motor.nombre,))}

    def _asignar(self, vector) -> int:
        """Grupo más parecido (similitud coseno ≥ umbral) o uno nuevo."""
        vector = _normalizar(vector)
        mejor, similitud = None, UMBRAL.get(self.motor.nombre, UMBRAL["sface"])
        for gid, (centroide, _) in self._grupos.items():
            s = _producto(vector, centroide)
            if s >= similitud:
                mejor, similitud = gid, s
        if mejor is None:
            cur = self.db.execute("INSERT INTO grupos (centroide, n, motor) VALUES (?, 1, ?)",
                                  (vector.tobytes(), self.motor.nombre))
            self._grupos[cur.lastrowid] = (vector, 1)
            return cur.lastrowid
        centroide, n = self._grupos[mejor]
        centroide = _media(centroide, n, vector)
        self._grupos[mejor] = (centroide, n + 1)
        self.db.execute("UPDATE grupos SET centroide = ?, n = ? WHERE id = ?",
                        (centroide.tobytes(), n + 1, mejor))
        return mejor

    def pendientes(self, elementos: list) -> list:
        """Fotos aún no analizadas (o cambiadas desde entonces) con este motor."""
        hechas = {src: (b, m, motor) for src, b, m, motor in
                  self.db.execute("SELECT src, bytes, mtime, motor FROM analizadas")}
        return [e for e in elementos if e["tipo"] == "foto"
                and hechas.get(e["src"]) != (e["bytes"], e["mtime"], self.motor.nombre)]

    def analizar(self, elementos: list, hilos: int = 4) -> int:
        """Analiza lo pendiente y pone `caras` en cada foto. Devuelve cuántas se analizaron."""
        self._cargar_grupos()
        presentes = {e["src"] for e in elementos}
        for (src,) in self.db.execute("SELECT src FROM analizadas").fetchall():
            if src not in presentes:   # ya no está en la biblioteca
                self.db.execute("DELETE FROM caras WHERE src = ?", (src,))
                self.db.execute("DELETE FROM analizadas WHERE src = ?", (src,))

        pendientes = self.pendientes(elementos)

        def detectar(e):
            try:
                return e, self.motor.caras(self.carpeta / e["src"])
            except Exception as exc:
                return e, exc

        with ThreadPoolExecutor(max(1, hilos)) as pool:
            for n, (e, caras) in enumerate(pool.map(detectar, pendientes), 1):
                self.db.execute("DELETE FROM caras WHERE src = ?", (e["src"],))
                if isinstance(caras, Exception):
                    print(f"  caras omitidas en {e['src']}: {caras}")
                    caras = []
                for x, y, w, h, vector in caras:
                    grupo = self._asignar(vector)
                    self.db.execute(
                        "INSERT INTO caras (src, x, y, w, h, vector, grupo) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (e["src"], x, y, w, h, _normalizar(vector).tobytes(), grupo))
                self.db.execute("INSERT OR REPLACE INTO analizadas VALUES (?, ?, ?, ?)",
                                (e["src"], e["bytes"], e["mtime"], self.motor.nombre))
                if n % 200 == 0:
                    self.db.commit()
                    print(f"  caras: {n}/{len(pendientes)} fotos analizadas")
        self.db.commit()

        por_src = {}
        for src, x, y, w, h, grupo in self.db.execute(
                "SELECT src, x, y, w, h, grupo FROM caras ORDER BY src, x"):
            por_src.setdefault(src, []).append([grupo, round(x, 3), round(y, 3),
                                                round(w, 3), round(h, 3)])
        for e in elementos:
            e.pop("caras", None)
            if e["src"] in por_src:
                e["caras"] = por_src[e["src"]]
        return len(pendientes)


def aplicar_caras(carpeta: Path, elementos: list, motor: Motor = None, hilos: int = 4):
    """Paso de la galería: devuelve (fotos analizadas ahora, aviso o '')."""
    aviso = ""
    if motor is None:
        if not disponible():
            return 0, MENSAJE_SIN_OPENCV
        motor = MotorOpenCV()
        if not motor.con_modelos:
            aviso = ("AVISO: caras con el detector básico (agrupa poco). Para agruparlas "
                     "bien:  python main.py galeria <carpeta> --descargar-modelos-caras")
    caras = Caras(carpeta, motor)
    try:
        analizadas = caras.analizar(elementos, hilos)
    finally:
        caras.cerrar()
    return analizadas, aviso


def renombrar_en_cache(carpeta: Path, cambios: dict):
    """Tras `reorganizar`: las fotos movidas conservan sus caras ya calculadas."""
    ruta = carpeta / CARPETA_GALERIA / "caras.sqlite"
    if not cambios or not ruta.exists():
        return
    db = sqlite3.connect(ruta)
    try:
        for viejo, nuevo in cambios.items():
            for tabla in ("analizadas", "caras"):
                db.execute(f"UPDATE {tabla} SET src = ? WHERE src = ?", (nuevo, viejo))
        db.commit()
    finally:
        db.close()
