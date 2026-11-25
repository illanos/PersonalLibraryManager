"""Servidor local de las notas: la página web y su API.

Solo para este equipo y solo para su propia página:
  - Escucha en 127.0.0.1 y rechaza cabeceras Host que no sean locales ("DNS rebinding").
  - La API y los adjuntos solo responden a la propia página (Sec-Fetch-Site): otra web no
    puede ni incrustar tus imágenes.
  - Todo lo que cambia algo exige el mismo origen y un token secreto de esta ejecución, que
    solo puede leer la propia página: otra web no puede provocarlo (CSRF).
  - Los adjuntos se sirven con el tipo comprobado al guardarlos, y la página con una CSP
    que solo admite su propio código.

API (JSON): GET /api/estado, /api/notas, /api/notas/ID, /api/copia · POST /api/notas,
/api/notas/ID/adjuntos (el archivo tal cual), /api/lote, /api/categorias,
/api/adjuntos/ID/quitar|recuperar, /api/papelera/vaciar · PATCH /api/notas/ID,
/api/categorias/ID · DELETE /api/categorias/ID.
"""

import hmac
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import sys
import tempfile
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__
from . import adjuntos as adj
from .copia import escribir_copia, nombre_copia
from .cuaderno import COLORES, Cuaderno
from .errores import AdjuntoNoValido, Conflicto, ErrorNotas, NoEncontrada

PUERTO = 8790
CABECERA_TOKEN = "X-Notas-Token"
TOKEN = secrets.token_urlsafe(24)      # de esta ejecución (anti-CSRF)
PLANTILLAS = Path(__file__).with_name("plantillas")
ESTATICOS = {
    "notas.html": "text/html; charset=utf-8", "notas.css": "text/css; charset=utf-8",
    "notas.js": "text/javascript; charset=utf-8", "icono.svg": "image/svg+xml",
}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; "
       "media-src 'self' blob:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
MAX_JSON = 4 * 1024 * 1024
MAX_DESCARTAR = 64 * 1024 * 1024
TAM_BLOQUE = 256 * 1024
_RE_RANGO = re.compile(r"bytes=(\d*)-(\d*)")


def es_local(nombre_host: str) -> bool:
    nombre = (nombre_host or "").strip("[]").lower()
    if nombre == "localhost":
        return True
    try:
        return ipaddress.ip_address(nombre).is_loopback
    except ValueError:
        return False


class PeticionNoValida(Exception):
    def __init__(self, estado: HTTPStatus, texto: str, codigo: str = None):
        super().__init__(texto)
        self.estado, self.codigo = estado, codigo


class _Cuerpo:
    """El cuerpo de una petición, sabiendo cuánto queda por leer."""

    def __init__(self, flujo, longitud: int):
        self.flujo, self.pendiente = flujo, longitud

    def read(self, n: int) -> bytes:
        n = min(n, self.pendiente)
        datos = self.flujo.read(n) if n > 0 else b""
        self.pendiente -= len(datos)
        return datos


class ManejadorNotas(BaseHTTPRequestHandler):
    cuaderno: Cuaderno = None          # lo pone crear_servidor en una subclase
    server_version = "Notas"
    timeout = 120

    RUTAS = [
        ("GET", r"/", "_pagina"),
        ("GET", r"/estaticos/([a-z]+\.[a-z]+)", "_estatico"),
        ("GET", r"/api/estado", "_estado"),
        ("GET", r"/api/notas", "_listar"),
        ("POST", r"/api/notas", "_crear"),
        ("GET", r"/api/notas/(\d{1,15})", "_nota"),
        ("PATCH", r"/api/notas/(\d{1,15})", "_editar"),
        ("POST", r"/api/notas/(\d{1,15})/adjuntos", "_adjuntar"),
        ("POST", r"/api/lote", "_lote"),
        ("POST", r"/api/adjuntos/(\d{1,15})/(quitar|recuperar)", "_quitar_adjunto"),
        ("POST", r"/api/categorias", "_crear_categoria"),
        ("PATCH", r"/api/categorias/(\d{1,15})", "_renombrar_categoria"),
        ("DELETE", r"/api/categorias/(\d{1,15})", "_borrar_categoria"),
        ("POST", r"/api/papelera/vaciar", "_vaciar"),
        ("GET", r"/api/copia", "_copia"),
        ("GET", r"/adjuntos/(\d{1,15})", "_adjunto"),
        ("GET", r"/adjuntos/(\d{1,15})/miniatura", "_miniatura"),
    ]

    def log_message(self, formato, *args):      # sin una línea por cada petición
        pass

    # --- despacho y seguridad ---

    def do_GET(self):
        self._despachar("GET")

    def do_POST(self):
        self._despachar("POST")

    def do_PATCH(self):
        self._despachar("PATCH")

    def do_DELETE(self):
        self._despachar("DELETE")

    def _despachar(self, metodo: str):
        try:
            longitud = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            longitud = 0
        self.cuerpo = _Cuerpo(self.rfile, max(0, longitud))
        try:
            url = urlsplit(self.path)
            self.consulta = parse_qs(url.query)
            self._comprobar(metodo, url.path)
            for metodo_ruta, patron, nombre in self.RUTAS:
                m = re.fullmatch(patron, url.path) if metodo_ruta == metodo else None
                if m:
                    return getattr(self, nombre)(*m.groups())
            raise PeticionNoValida(HTTPStatus.NOT_FOUND, "No existe")
        except PeticionNoValida as exc:
            self._error(exc.estado, str(exc), exc.codigo)
        except Conflicto as exc:
            self._json({"error": str(exc), "nota": exc.nota}, HTTPStatus.CONFLICT)
        except NoEncontrada as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except AdjuntoNoValido as exc:
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, str(exc))
        except ErrorNotas as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except (ConnectionError, TimeoutError):
            raise                    # el navegador ha cortado: no hay a quién responder
        except (OSError, sqlite3.Error) as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"No se ha podido guardar: {exc}")

    def _comprobar(self, metodo: str, ruta: str):
        host = self.headers.get("Host", "")
        if not es_local(re.sub(r":\d+$", "", host)):
            raise PeticionNoValida(HTTPStatus.FORBIDDEN, "Host no permitido")
        sitio = self.headers.get("Sec-Fetch-Site", "same-origin")
        if ruta.startswith(("/api/", "/adjuntos/")) and sitio not in ("same-origin", "none"):
            raise PeticionNoValida(HTTPStatus.FORBIDDEN, "Petición de otra web")
        if metodo == "GET":
            return
        origen = self.headers.get("Origin")
        if (not origen or urlsplit(origen).netloc.lower() != host.lower()
                or sitio != "same-origin"):
            raise PeticionNoValida(HTTPStatus.FORBIDDEN, "Petición de otra web")
        if not hmac.compare_digest(self.headers.get(CABECERA_TOKEN, "").encode(), TOKEN.encode()):
            # La página se abrió con una ejecución anterior: pide el token y reintenta
            raise PeticionNoValida(HTTPStatus.FORBIDDEN, "Token caducado", "token")

    # --- entrada y salida ---

    def _longitud(self, maximo: int) -> int:
        longitud = self.cuerpo.pendiente
        if not longitud:
            raise PeticionNoValida(HTTPStatus.LENGTH_REQUIRED, "La petición está vacía")
        if longitud > maximo:
            raise PeticionNoValida(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                                   f"Demasiado grande (máximo {maximo // 1024 // 1024} MB)")
        return longitud

    def _cuerpo(self) -> dict:
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise PeticionNoValida(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Se esperaba JSON")
        try:
            datos = json.loads(self.cuerpo.read(self._longitud(MAX_JSON)))
        except ValueError:
            raise PeticionNoValida(HTTPStatus.BAD_REQUEST, "JSON no válido") from None
        if not isinstance(datos, dict):
            raise PeticionNoValida(HTTPStatus.BAD_REQUEST, "Se esperaba un objeto JSON")
        return datos

    def _cabeceras(self, tipo: str, tamano: int, estado=HTTPStatus.OK, **otras):
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(tamano))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        otras.setdefault("Cache_Control", "no-cache")
        for nombre, valor in otras.items():
            self.send_header(nombre.replace("_", "-"), valor)
        self.end_headers()

    def _json(self, datos, estado=HTTPStatus.OK):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8", "replace")
        self._cabeceras("application/json; charset=utf-8", len(cuerpo), estado,
                        Cache_Control="no-store")
        self.wfile.write(cuerpo)

    def _error(self, estado, texto: str, codigo: str = None):
        # Si se cierra la conexión con cuerpo sin leer, el navegador ve «conexión cortada»
        # en vez del mensaje: se descarta lo que quede, con un límite
        try:
            if 0 < self.cuerpo.pendiente <= MAX_DESCARTAR:
                self.connection.settimeout(5)
                while self.cuerpo.read(TAM_BLOQUE):
                    pass
        except OSError:
            pass
        self._json({"error": texto, "codigo": codigo}, estado)

    # --- página ---

    def _pagina(self):
        self._estatico("notas.html")

    def _estatico(self, nombre: str):
        if nombre not in ESTATICOS:
            raise PeticionNoValida(HTTPStatus.NOT_FOUND, "No existe")
        cuerpo = (PLANTILLAS / nombre).read_bytes()
        self._cabeceras(ESTATICOS[nombre], len(cuerpo), Content_Security_Policy=CSP)
        self.wfile.write(cuerpo)

    # --- notas ---

    def _estado(self):
        self._json({"app": "notas", "version": __version__, "token": TOKEN,
                    "cuaderno": str(self.cuaderno.carpeta), "colores": COLORES,
                    "max_adjunto": adj.MAX_BYTES, **self.cuaderno.estado()})

    def _listar(self):
        def uno(nombre, defecto=None):
            return self.consulta.get(nombre, [defecto])[0]
        categoria = uno("categoria")
        if categoria is not None and not re.fullmatch("[0-9]{1,15}", categoria):
            raise ErrorNotas("Categoría no válida")
        notas = self.cuaderno.listar(
            uno("vista", "activas"), uno("buscar", ""),
            int(categoria) if categoria is not None else None,
            uno("tipo") or None, uno("orden", "modificada"))
        self._json({"notas": notas})

    def _nota(self, id_nota):
        self._json(self.cuaderno.nota(int(id_nota)))

    def _crear(self):
        campos = self._campos(self._cuerpo(), "titulo", "texto", "color", "fijada", "categorias")
        self._json(self.cuaderno.crear(**campos), HTTPStatus.CREATED)

    @staticmethod
    def _campos(datos: dict, *admitidos) -> dict:
        return {c: datos[c] for c in admitidos if c in datos}

    def _editar(self, id_nota):
        campos = self._campos(self._cuerpo(), "version", "titulo", "texto", "color", "fijada",
                              "archivada", "categorias")
        self._json(self.cuaderno.editar(int(id_nota), **campos))

    def _lote(self):
        datos = self._cuerpo()
        accion, ids = datos.get("accion"), datos.get("ids")
        if accion == "eliminar":
            cambiadas = self.cuaderno.eliminar(ids)
        else:
            cambiadas = self.cuaderno.lote(ids, accion, datos.get("valor"))
        self._json({"cambiadas": cambiadas})

    def _vaciar(self):
        self._json({"borradas": self.cuaderno.vaciar_papelera(self._cuerpo().get("confirmar"))})

    # --- categorías ---

    def _crear_categoria(self):
        self._json(self.cuaderno.crear_categoria(self._cuerpo().get("nombre")),
                   HTTPStatus.CREATED)

    def _renombrar_categoria(self, id_categoria):
        self._json(self.cuaderno.renombrar_categoria(int(id_categoria),
                                                     self._cuerpo().get("nombre")))

    def _borrar_categoria(self, id_categoria):
        self.cuaderno.borrar_categoria(int(id_categoria))
        self._json({"ok": True})

    # --- adjuntos ---

    def _adjuntar(self, id_nota):
        """El cuerpo es el archivo; nombre y duración van en cabeceras."""
        longitud = self._longitud(adj.MAX_BYTES)
        adjunto = self.cuaderno.adjuntar(
            int(id_nota), self.cuerpo, unquote(self.headers.get("X-Nombre", "")),
            self.headers.get("Content-Type", ""), self.headers.get("X-Duracion"), longitud)
        self._json(adjunto, HTTPStatus.CREATED)

    def _quitar_adjunto(self, id_adjunto, accion):
        self._json(self.cuaderno.quitar_adjunto(int(id_adjunto), accion == "quitar"))

    def _adjunto(self, id_adjunto):
        adjunto = self.cuaderno.adjunto(int(id_adjunto))
        disposicion = "attachment" if "descargar" in self.consulta else "inline"
        self._archivo(adjunto["ruta"], adjunto["mime"],
                      f"{disposicion}; filename*=UTF-8''{quote(adjunto['nombre'])}")

    def _miniatura(self, id_adjunto):
        adjunto = self.cuaderno.adjunto(int(id_adjunto))
        if adjunto["tipo"] != adj.IMAGEN:
            raise NoEncontrada("Solo las imágenes tienen miniatura")
        mini = adj.miniatura(self.cuaderno.carpeta, adjunto["archivo"])
        self._archivo(mini or adjunto["ruta"], "image/webp" if mini else adjunto["mime"], "inline")

    def _archivo(self, ruta: Path, mime: str, disposicion: str):
        """Sirve un archivo, entero o el rango pedido (necesario para saltar en un audio)."""
        try:
            tamano = os.path.getsize(ruta)
        except OSError:
            raise NoEncontrada("El archivo ya no está en el cuaderno") from None
        comunes = {"Content_Disposition": disposicion, "Accept_Ranges": "bytes",
                   "Cache_Control": "private, max-age=31536000, immutable"}
        m = _RE_RANGO.fullmatch((self.headers.get("Range") or "").strip())
        if not m or m.groups() == ("", ""):
            inicio, fin, estado = 0, tamano - 1, HTTPStatus.OK
        else:
            desde, hasta = m.groups()
            if desde == "":                                # bytes=-N: los últimos N
                inicio, fin = max(0, tamano - int(hasta)), tamano - 1
            else:
                inicio, fin = int(desde), min(int(hasta or tamano), tamano - 1)
            if inicio > fin:
                return self._cabeceras(mime, 0, HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                                       Content_Range=f"bytes */{tamano}")
            estado = HTTPStatus.PARTIAL_CONTENT
            comunes["Content_Range"] = f"bytes {inicio}-{fin}/{tamano}"
        with open(ruta, "rb") as f:
            self._cabeceras(mime, fin - inicio + 1, estado, **comunes)
            f.seek(inicio)
            restante = fin - inicio + 1
            while restante > 0 and (bloque := f.read(min(TAM_BLOQUE, restante))):
                self.wfile.write(bloque)
                restante -= len(bloque)

    # --- copia de seguridad ---

    def _copia(self):
        with tempfile.TemporaryFile() as f:
            escribir_copia(self.cuaderno, f)
            tamano = f.tell()
            f.seek(0)
            self._cabeceras("application/zip", tamano,
                            Content_Disposition=f'attachment; filename="{nombre_copia()}"')
            while bloque := f.read(TAM_BLOQUE):
                self.wfile.write(bloque)


class ServidorLocal(ThreadingHTTPServer):
    # En Windows SO_REUSEADDR permite "robar" un puerto ocupado: mejor desactivarlo
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True

    def handle_error(self, request, client_address):
        # El navegador corta conexiones a menudo (al saltar en un audio): no es un error
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def crear_servidor(cuaderno: Cuaderno, puerto: int = PUERTO, intentos: int = 10) -> ServidorLocal:
    """Servidor de `cuaderno` en 127.0.0.1, en el primer puerto libre desde `puerto`."""
    manejador = type("Manejador", (ManejadorNotas,), {"cuaderno": cuaderno})
    ultimo_error = None
    for candidato in range(puerto, puerto + max(1, intentos)):
        try:
            return ServidorLocal(("127.0.0.1", candidato), manejador)
        except OSError as exc:
            ultimo_error = exc
    raise ErrorNotas(f"No hay puertos libres entre {puerto} y {puerto + intentos - 1}: "
                     f"{ultimo_error}")


def ya_abierto(cuaderno: Cuaderno, puerto: int) -> bool:
    """True si en ese puerto ya está este programa con el mismo cuaderno."""
    try:
        sin_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with sin_proxy.open(f"http://127.0.0.1:{puerto}/api/estado", timeout=1) as respuesta:
            datos = json.loads(respuesta.read(MAX_JSON))
        return datos.get("app") == "notas" and datos.get("cuaderno") == str(cuaderno.carpeta)
    except (OSError, ValueError, AttributeError):
        return False


def servir(cuaderno: Cuaderno, puerto: int = PUERTO, abrir_navegador: bool = True):
    if puerto and ya_abierto(cuaderno, puerto):
        url = f"http://127.0.0.1:{puerto}/"
        print(f"Las notas ya están abiertas en {url}")
        if abrir_navegador:
            webbrowser.open(url)
        return
    servidor = crear_servidor(cuaderno, puerto)
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    print(f"Notas disponibles en {url}  (solo desde este equipo; Ctrl+C para detener)")
    print(f"Se guardan en {cuaderno.carpeta}")
    if abrir_navegador:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nNotas detenido.")
    finally:
        servidor.server_close()
