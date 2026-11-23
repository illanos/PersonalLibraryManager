"""Servidor HTTP local de la galería.

Sobre el servidor estático de Python añade lo que una galería necesita:
  - Peticiones parciales (Range / 206): sin ellas no se puede saltar a un punto
    del vídeo y Safari ni siquiera lo reproduce.
  - API mínima de favoritos (GET/POST /api/favoritos -> _galeria/favoritos.json).
  - Solo escucha en 127.0.0.1 y rechaza cabeceras Host que no sean locales, lo que
    impide que una web maliciosa lea tus fotos mediante "DNS rebinding".
  - Si el puerto está ocupado prueba los siguientes.
  - «Limpiar repetidas» (limpiar.html + /api/limpieza/..., ver limpieza.py). Las
    peticiones que mueven o borran archivos exigen, además, el mismo origen (Origin y
    Sec-Fetch-Site) y un token secreto de esta ejecución que solo puede leer la propia
    página: otra web no puede provocarlas (CSRF).
"""

import functools
import hmac
import ipaddress
import json
import os
import re
import secrets
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from media_utils import CARPETA_GALERIA

RUTA_API_FAVORITOS = "/api/favoritos"
RUTA_API_CARAS = "/api/caras"        # nombres de los grupos de caras: {grupo: nombre}
RUTA_API_LIMPIEZA = "/api/limpieza/"
RUTA_LIMPIAR = "/limpiar.html"
PLANTILLA_LIMPIAR = Path(__file__).with_name("limpiar_plantilla.html")
CABECERA_TOKEN = "X-Exportador-Token"
# Secreto de esta ejecución del servidor para las acciones de limpieza (anti-CSRF)
TOKEN_LIMPIEZA = secrets.token_urlsafe(24)
ACCIONES_LIMPIEZA = {"decidir", "no-repetidas", "deshacer", "restaurar", "vaciar"}
MAX_CUERPO = 5 * 1024 * 1024
TAM_BLOQUE = 256 * 1024
_RE_RANGO = re.compile(r"bytes=(\d*)-(\d*)")


def _es_local(nombre_host: str) -> bool:
    nombre = (nombre_host or "").strip("[]").lower()
    if nombre == "localhost":
        return True
    try:
        return ipaddress.ip_address(nombre).is_loopback
    except ValueError:
        return False


class SoloLocal:
    """Comprobaciones comunes a los servidores locales (galería y panel)."""

    def _host_valido(self) -> bool:
        host = self.headers.get("Host", "")
        return _es_local(re.sub(r":\d+$", "", host))

    def _origen_valido(self) -> bool:
        origen = self.headers.get("Origin")
        return origen is None or _es_local(urlsplit(origen).hostname)

    def _ruta_peticion(self) -> str:
        return urlsplit(getattr(self, "path", "")).path


class ManejadorGaleria(SoloLocal, SimpleHTTPRequestHandler):
    _lock_favoritos = threading.Lock()
    # El registro de Windows a veces trae tipos MIME raros; .mov (H.264 de iPhone)
    # se anuncia como MP4 para que Chrome y Firefox también lo reproduzcan.
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/mp4",
        ".webm": "video/webm", ".webp": "image/webp", ".avif": "image/avif",
        ".json": "application/json", ".js": "text/javascript",
        # Notas de voz de WhatsApp: Opus en contenedor Ogg
        ".opus": "audio/ogg", ".ogg": "audio/ogg", ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav",
    }

    def log_message(self, formato, *args):   # sin una línea por cada miniatura
        pass

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        if self._ruta_peticion().endswith((".html", ".json")):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    # --- GET / HEAD ---

    def do_HEAD(self):
        if not self._host_valido():
            return self.send_error(HTTPStatus.FORBIDDEN, "Host no permitido")
        super().do_HEAD()

    def do_GET(self):
        if not self._host_valido():
            return self.send_error(HTTPStatus.FORBIDDEN, "Host no permitido")
        if self._ruta_peticion() == RUTA_API_FAVORITOS:
            return self._responder_json(HTTPStatus.OK, self._leer_favoritos())
        if self._ruta_peticion() == RUTA_API_CARAS:
            from caras import leer_nombres
            return self._responder_json(HTTPStatus.OK, leer_nombres(Path(self.directory)))
        if self._ruta_peticion() == RUTA_LIMPIAR:
            return self._servir_texto(PLANTILLA_LIMPIAR.read_bytes(), "text/html; charset=utf-8")
        if self._ruta_peticion().startswith(RUTA_API_LIMPIEZA):
            return self._limpieza_get(self._ruta_peticion()[len(RUTA_API_LIMPIEZA):])
        rango = self.headers.get("Range")
        if rango and self._servir_rango(rango):
            return
        super().do_GET()

    def _servir_rango(self, cabecera: str) -> bool:
        """Responde 206/416. Devuelve False si no aplica (se sirve el archivo entero)."""
        ruta = self.translate_path(self.path)
        m = _RE_RANGO.fullmatch(cabecera.strip())
        if not os.path.isfile(ruta) or not m or m.groups() == ("", ""):
            return False
        tamano = os.path.getsize(ruta)
        inicio, fin = m.groups()
        if inicio == "":                       # bytes=-N  (los últimos N)
            inicio, fin = max(0, tamano - int(fin)), tamano - 1
        else:
            inicio = int(inicio)
            fin = min(int(fin), tamano - 1) if fin else tamano - 1
        if inicio >= tamano or inicio > fin:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{tamano}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True

        with open(ruta, "rb") as f:
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Type", self.guess_type(ruta))
            self.send_header("Content-Range", f"bytes {inicio}-{fin}/{tamano}")
            self.send_header("Content-Length", str(fin - inicio + 1))
            self.send_header("Last-Modified", self.date_time_string(os.path.getmtime(ruta)))
            self.end_headers()
            f.seek(inicio)
            restante = fin - inicio + 1
            while restante > 0:
                bloque = f.read(min(TAM_BLOQUE, restante))
                if not bloque:
                    break
                self.wfile.write(bloque)
                restante -= len(bloque)
        return True

    # --- favoritos ---

    def _ruta_favoritos(self) -> Path:
        return Path(self.directory) / CARPETA_GALERIA / "favoritos.json"

    def _leer_favoritos(self) -> list:
        try:
            datos = json.loads(self._ruta_favoritos().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [x for x in datos if isinstance(x, str)] if isinstance(datos, list) else []

    def do_POST(self):
        if not self._host_valido() or not self._origen_valido():
            return self.send_error(HTTPStatus.FORBIDDEN, "Origen no permitido")
        accion = None
        if self._ruta_peticion().startswith(RUTA_API_LIMPIEZA):
            accion = self._ruta_peticion()[len(RUTA_API_LIMPIEZA):]
            if accion not in ACCIONES_LIMPIEZA:
                return self.send_error(HTTPStatus.NOT_FOUND)
            if not self._mismo_origen_estricto():
                return self._error_json(HTTPStatus.FORBIDDEN, "Petición de otro origen o sin token")
        elif self._ruta_peticion() not in (RUTA_API_FAVORITOS, RUTA_API_CARAS):
            return self.send_error(HTTPStatus.NOT_FOUND)
        # Exigir JSON obliga al navegador a pedir permiso (CORS) a otras webs
        if "application/json" not in self.headers.get("Content-Type", ""):
            return self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            longitud = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            longitud = -1
        if not 0 < longitud <= MAX_CUERPO:
            return self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            datos = json.loads(self.rfile.read(longitud))
        except ValueError:
            return self.send_error(HTTPStatus.BAD_REQUEST, "JSON no válido")
        if accion:
            return self._limpieza_post(accion, datos)
        if self._ruta_peticion() == RUTA_API_CARAS:
            return self._guardar_nombre_cara(datos)
        if not isinstance(datos, list) or not all(isinstance(x, str) for x in datos):
            return self.send_error(HTTPStatus.BAD_REQUEST, "Se esperaba una lista de rutas")

        favoritos = sorted(set(datos))
        ruta = self._ruta_favoritos()
        with self._lock_favoritos:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            tmp = ruta.with_name(ruta.name + ".part")
            tmp.write_text(json.dumps(favoritos, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, ruta)
        self._responder_json(HTTPStatus.OK, {"ok": True, "total": len(favoritos)})

    def _guardar_nombre_cara(self, datos):
        """{"grupo": "12", "nombre": "Ana"}; nombre vacío = quitar el nombre."""
        from caras import leer_nombres, ruta_nombres
        grupo = str(datos.get("grupo", "")) if isinstance(datos, dict) else ""
        nombre = datos.get("nombre") if isinstance(datos, dict) else None
        if not grupo.isdigit() or not isinstance(nombre, str) or len(nombre) > 120:
            return self.send_error(HTTPStatus.BAD_REQUEST, "Se esperaba {grupo, nombre}")
        carpeta = Path(self.directory)
        with self._lock_favoritos:
            nombres = leer_nombres(carpeta)
            if nombre.strip():
                nombres[grupo] = nombre.strip()
            else:
                nombres.pop(grupo, None)
            ruta = ruta_nombres(carpeta)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            tmp = ruta.with_name(ruta.name + ".part")
            tmp.write_text(json.dumps(nombres, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, ruta)
        self._responder_json(HTTPStatus.OK, nombres)

    # --- limpiar repetidas ---

    def _mismo_origen_estricto(self) -> bool:
        """Origin presente y con el mismo host:puerto, Sec-Fetch-Site same-origin y token."""
        origen = self.headers.get("Origin")
        if not origen or urlsplit(origen).netloc.lower() != self.headers.get("Host", "").lower():
            return False
        if self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
            return False
        return hmac.compare_digest(self.headers.get(CABECERA_TOKEN, ""), TOKEN_LIMPIEZA)

    def _limpieza(self):
        from limpieza import Limpieza
        return Limpieza(Path(self.directory))

    def _limpieza_get(self, accion: str):
        from limpieza import UMBRAL
        if accion == "grupos":
            try:
                umbral = int(parse_qs(urlsplit(self.path).query).get("umbral", [UMBRAL])[0])
            except ValueError:
                umbral = UMBRAL
            datos = self._limpieza().grupos(umbral)
            datos["token"] = TOKEN_LIMPIEZA   # una web ajena no puede leerlo (sin CORS)
            return self._responder_json(HTTPStatus.OK, datos)
        if accion == "papelera":
            return self._responder_json(HTTPStatus.OK, self._limpieza().contenido_papelera())
        self.send_error(HTTPStatus.NOT_FOUND)

    def _limpieza_post(self, accion: str, datos):
        from limpieza import ErrorLimpieza, RutaNoValida
        if not isinstance(datos, dict):
            return self._error_json(HTTPStatus.BAD_REQUEST, "Se esperaba un objeto JSON")
        limpieza = self._limpieza()
        try:
            if accion == "decidir":
                resultado = limpieza.decidir(datos.get("grupo"), datos.get("quitar", []))
            elif accion == "no-repetidas":
                resultado = limpieza.no_repetidas(datos.get("grupo"))
            elif accion == "deshacer":
                resultado = limpieza.deshacer()
            elif accion == "restaurar":
                resultado = limpieza.restaurar(datos.get("srcs"))
            else:
                resultado = limpieza.vaciar(datos.get("confirmar"))
        except RutaNoValida as exc:
            return self._error_json(HTTPStatus.BAD_REQUEST, f"Ruta no permitida: {exc}")
        except ErrorLimpieza as exc:
            return self._error_json(HTTPStatus.CONFLICT, str(exc))
        except OSError as exc:
            return self._error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error de disco: {exc}")
        self._responder_json(HTTPStatus.OK, resultado)

    def _error_json(self, estado, texto: str):
        self._responder_json(estado, {"ok": False, "error": texto})

    def _servir_texto(self, cuerpo: bytes, tipo: str):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _responder_json(self, estado, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


class ServidorLocal(ThreadingHTTPServer):
    # En Windows SO_REUSEADDR permite "robar" un puerto ocupado: mejor desactivarlo
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True

    def handle_error(self, request, client_address):
        # El navegador corta conexiones a menudo (al saltar en un vídeo): no es un error
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


ServidorGaleria = ServidorLocal   # nombre anterior


def ligar_local(manejador, puerto: int, intentos: int = 10) -> ServidorLocal:
    """Servidor ligado a 127.0.0.1 en el primer puerto libre desde `puerto`."""
    ultimo_error = None
    for candidato in range(puerto, puerto + max(1, intentos)):
        try:
            return ServidorLocal(("127.0.0.1", candidato), manejador)
        except OSError as exc:
            ultimo_error = exc
    raise OSError(f"No hay puertos libres entre {puerto} y {puerto + intentos - 1}: "
                  f"{ultimo_error}")


def crear_servidor(carpeta: Path, puerto: int = 8080, intentos: int = 10):
    """Servidor de la galería de `carpeta` en el primer puerto libre desde `puerto`."""
    return ligar_local(functools.partial(ManejadorGaleria, directory=str(carpeta)),
                       puerto, intentos)


def servir(carpeta: Path, puerto: int = 8080, abrir_navegador: bool = True):
    servidor = crear_servidor(carpeta, puerto)
    url = f"http://127.0.0.1:{servidor.server_address[1]}/galeria.html"
    print(f"Galería disponible en {url}  (solo desde este equipo; Ctrl+C para detener)")
    if abrir_navegador:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        servidor.server_close()
