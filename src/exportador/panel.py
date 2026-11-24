"""Panel web local: configurar las opciones, lanzar y seguir el progreso.

    python -m exportador panel        ->  http://127.0.0.1:8765/

- Las opciones salen del propio argparse de cli.py (valores por defecto, ayudas,
  listas y validación): la web y la línea de comandos no pueden desincronizarse.
- Cada ejecución es un `python -m exportador <comando> ...` aparte. El panel lee su salida:
  las líneas normales forman el registro y las que empiezan por MARCA_PROGRESO son
  eventos (ver media_utils.progreso). «Detener» equivale a pulsar Ctrl+C en la
  terminal: el programa termina en orden y no deja archivos a medias.
- Una sola ejecución a la vez (todas escriben en el mismo catálogo).
- Solo escucha en 127.0.0.1, rechaza cabeceras Host/Origin no locales y exige JSON en
  los POST, así que ninguna web puede lanzar nada desde el navegador.
"""

import argparse
import contextlib
import io
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .descargas import CARPETA_DATOS
from .cli import (COMANDOS_IMPORTACION, _calidad, _positivo, _umbral_fusion,
                  comprobar_argumentos, construir_parser, destino_de)
from .media_utils import MARCA_PROGRESO, VARIABLE_PROGRESO
from .servidor import SoloLocal, crear_servidor, ligar_local

CARPETA_PAQUETE = Path(__file__).resolve().parent
# Carpeta que contiene el paquete (src/ o site-packages): las ejecuciones se lanzan desde
# ella con `python -m exportador`, así siempre usan este mismo código, esté instalado o no
CARPETA_PROGRAMA = CARPETA_PAQUETE.parent
PAQUETE = CARPETA_PAQUETE.name
PLANTILLA = CARPETA_PAQUETE / "plantillas" / "panel.html"
PREFERENCIAS = CARPETA_DATOS / "panel.json"

COMANDOS_PANEL = ("todo", "fotos", "videos", "audio", "galeria", "reorganizar", "fusionar")
# El panel ya abre la galería por su cuenta (un servidor que no termina nunca no
# cabe en una ejecución con principio y fin)
NO_EN_PANEL = {"help", "servir", "puerto", "sin_navegador"}
RANGOS = {_positivo: (0, None), _calidad: (1, 100), _umbral_fusion: (0, 12)}
# Qué pedir cuando falta una carpeta obligatoria («Elige …»)
CARPETAS_OBLIGATORIAS = {"origen": "la carpeta de origen",
                         "coleccion": "la colección que quieres añadir",
                         "destino": "la biblioteca a la que añadirla"}
# En el panel, la galería sale completa por defecto (caras y lugares). Las descargas solo
# ocurren la primera vez; después ya están en datos/ y se saltan. En la CLI siguen
# siendo opciones que hay que pedir.
DEFECTOS_PANEL = {"caras": True, "descargar_lugares": True, "descargar_modelos_caras": True}

TITULOS = {
    "todo": "Importar todo", "fotos": "Importar fotos", "videos": "Importar vídeos",
    "audio": "Importar audio", "galeria": "Generar la galería",
    "reorganizar": "Reorganizar la biblioteca", "fusionar": "Fusionar otra colección",
}
TITULOS_FASE = {"fotos": "Fotos", "videos": "Vídeos", "audio": "Audio",
                "galeria": "Galería", "reorganizar": "Reorganizar", "fusionar": "Fusionar"}

MAX_LINEAS = 20000        # registro en memoria por ejecución
LINEAS_POR_RESPUESTA = 2000
MAX_HISTORIAL = 20
MAX_RECIENTES = 10
ESPERA_DETENER = 45       # s hasta forzar el cierre si no se detiene solo
MAX_CUERPO = 256 * 1024


class ErrorPanel(Exception):
    """Error que se muestra tal cual al usuario."""


# ----------------------------- Opciones (desde argparse) -----------------------------

def _subcomandos(parser):
    for accion in parser._actions:
        if isinstance(accion, argparse._SubParsersAction):
            return accion
    raise RuntimeError("cli.py no define subcomandos")


def _tipo(accion) -> str:
    if not accion.option_strings or accion.type is Path:
        return "ruta"
    if isinstance(accion, argparse._StoreTrueAction):
        return "si_no"
    if accion.choices:
        return "lista"
    if accion.type in RANGOS or accion.type in (int, float):
        return "numero"
    return "texto"


def _ayuda(texto) -> str:
    return (texto or "").replace("%%", "%")


def calcular_esquema() -> dict:
    """{comando: {titulo, ayuda, simular, opciones: [...]}} sacado del parser de cli.py."""
    subcomandos = _subcomandos(construir_parser())
    ayudas = {a.dest: a.help for a in subcomandos._choices_actions}
    esquema = {}
    for nombre in COMANDOS_PANEL:
        sub = subcomandos.choices[nombre]
        grupo_de = {id(a): g.title for g in sub._action_groups for a in g._group_actions}
        opciones = []
        for a in sub._actions:
            if a.dest in NO_EN_PANEL or a.help == argparse.SUPPRESS:
                continue
            tipo = _tipo(a)
            defecto = a.default if isinstance(a.default, (bool, int, float, str)) else None
            defecto = DEFECTOS_PANEL.get(a.dest, defecto)
            op = {"dest": a.dest, "opcion": a.option_strings[0] if a.option_strings else None,
                  "tipo": tipo, "defecto": defecto, "ayuda": _ayuda(a.help),
                  "grupo": grupo_de.get(id(a)), "posicional": not a.option_strings,
                  "obligatoria": bool(a.option_strings and a.required)}
            if a.choices:
                op["opciones"] = list(a.choices)
            if a.type in RANGOS:
                op["min"], op["max"] = RANGOS[a.type]
            opciones.append(op)
        esquema[nombre] = {
            "titulo": TITULOS[nombre], "ayuda": _ayuda(ayudas.get(nombre)),
            "simular": any(o["dest"] == "simular" for o in opciones),
            "opciones": opciones,
        }
    return esquema


ESQUEMA = calcular_esquema()


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def construir_argv(comando: str, valores: dict, simular: bool = False) -> list:
    """Argumentos de cli.py para `comando` con los valores del formulario.

    Solo se usan las opciones que ese comando admite; las que coinciden con el valor
    por defecto se omiten para que la línea de comandos quede limpia.
    """
    if comando not in ESQUEMA:
        raise ErrorPanel(f"Acción desconocida: {comando}")
    if not isinstance(valores, dict):
        raise ErrorPanel("Valores no válidos")
    posicionales, opciones = [], []
    for op in ESQUEMA[comando]["opciones"]:
        if op["dest"] == "simular":
            valor = simular
        elif op["tipo"] == "si_no":   # sin valor: el del panel (DEFECTOS_PANEL)
            valor = valores.get(op["dest"], op["defecto"])
        else:
            valor = valores.get(op["dest"])
        if (op["posicional"] or op.get("obligatoria")) and not _texto(valor):
            raise ErrorPanel("Elige " + CARPETAS_OBLIGATORIAS.get(op["dest"],
                                                                  "la carpeta de la biblioteca"))
        if op["posicional"]:
            posicionales.append(_texto(valor))
        elif op["tipo"] == "si_no":
            if valor is True:
                opciones.append(op["opcion"])
        elif _texto(valor) and _texto(valor) != _texto(op["defecto"]):
            opciones += [op["opcion"], _texto(valor)]
    return [comando, *posicionales, *opciones]


def validar(argv: list):
    """Pasa `argv` por el parser real. Devuelve los argumentos o lanza ErrorPanel."""
    errores = io.StringIO()
    try:
        with contextlib.redirect_stderr(errores):
            args = construir_parser().parse_args(argv)
    except SystemExit:
        lineas = errores.getvalue().strip().splitlines()
        mensaje = lineas[-1] if lineas else "Opciones no válidas"
        raise ErrorPanel(mensaje.split("error: ", 1)[-1]) from None
    problema = comprobar_argumentos(args)
    if problema:
        raise ErrorPanel(problema)
    return args


def linea_de_comandos(argv: list) -> str:
    partes = ["python", "-m", PAQUETE, *argv]
    return subprocess.list2cmdline(partes) if os.name == "nt" else shlex.join(partes)


def carpeta_resultado(args) -> Path:
    """Biblioteca sobre la que trabaja (o trabajará) la ejecución."""
    if args.comando == "galeria":
        return args.carpeta.resolve()
    if args.comando == "reorganizar":
        return args.biblioteca.resolve()
    if args.comando == "fusionar":
        return args.destino.resolve()
    return destino_de(args.origen, args.destino)


def fases_previstas(args) -> list:
    """Fases en el orden en que las ejecuta cli.py."""
    if args.comando == "fusionar":   # actualiza la galería de la biblioteca, si la tiene
        galeria = (not args.simular and not args.sin_galeria
                   and (args.destino.resolve() / "galeria.json").is_file())
        return ["fusionar"] + (["galeria"] if galeria else [])
    if args.comando not in COMANDOS_IMPORTACION:
        return [args.comando]
    if args.comando == "todo":
        fases = ["fotos", "videos"] + ([] if args.sin_audio else ["audio"])
    elif args.comando == "google":   # Takeout: sin audio
        fases = ["fotos", "videos"]
    else:
        fases = [args.comando]
    if args.renombrar_aproximadas:
        fases.append("reorganizar")
    if args.comando in ("todo", "google") and not args.simular and not args.sin_galeria:
        fases.append("galeria")
    return fases


def comprobar(comando: str, valores: dict, simular: bool = False) -> dict:
    """Lo que el formulario necesita saber antes de lanzar: errores, comando y destino."""
    argv = construir_argv(comando, valores, simular)
    args = validar(argv)
    carpeta = carpeta_resultado(args)
    return {"argv": argv, "linea": linea_de_comandos(argv), "args": args,
            "carpeta": str(carpeta), "biblioteca_existe": (carpeta / ".exportador").is_dir(),
            "galeria_existe": (carpeta / "galeria.html").is_file(),
            "fases": fases_previstas(args)}


# ----------------------------- Ejecución -----------------------------

def _nivel(linea: str) -> str:
    """Tipo de línea del registro, para colorearla y contar errores y avisos."""
    texto = linea.strip()
    if not texto:
        return "normal"
    palabras = set(texto.replace("(", " ").replace(":", " ").split())
    if palabras & {"ERROR", "DAÑADO"} or texto.startswith(("Traceback", "Error:")):
        return "error"
    if "AVISO" in palabras or texto.startswith("aviso:"):
        return "aviso"
    if palabras & {"DUPLICADO", "PARECIDA"} or texto.startswith(("YA ESTÁ", "REPETIDA", "QUITADA")):
        return "info"
    if palabras & {"OK", "CAMBIOS", "ANIMADA", "PEGATINA", "AÑADIR", "SUSTITUIR"} \
            and texto.startswith("[") or texto.startswith("METADATOS"):
        return "ok"
    if texto.startswith(("PROCESANDO", "SIMULACIÓN", "REORGANIZANDO", "FUSIONANDO", "-----------",
                         "Galería generada", "Origen", "Destino")):
        return "titulo"
    return "normal"


class Trabajo:
    """Una ejecución de cli.py y todo lo que se sabe de su progreso."""

    def __init__(self, numero: int, comando: str, valores: dict, simular: bool, previa: dict):
        self.numero, self.comando, self.valores, self.simular = numero, comando, valores, simular
        self.argv, self.linea = previa["argv"], previa["linea"]
        self.carpeta = Path(previa["carpeta"])
        self.titulo = TITULOS[comando] + (" (simulación)" if simular else "")
        self.fases = [self._fase(f) for f in previa["fases"]]
        self.lock = threading.Lock()
        self.estado = "en_marcha"   # en_marcha | deteniendo | terminado | detenido | error
        self.codigo = None
        self.inicio, self.fin = time.time(), None
        self.lineas, self.base = [], 0       # registro (con las primeras descartadas)
        self.errores = self.avisos = 0
        self.videos = {}                     # vídeos codificándose: ruta -> porcentaje
        self.detener_pedido = False
        self.proceso = None
        self.al_terminar = None

    @staticmethod
    def _fase(nombre: str) -> dict:
        return {"fase": nombre, "titulo": TITULOS_FASE.get(nombre, nombre.capitalize()),
                "estado": "pendiente", "paso": "", "hecho": 0, "total": 0, "archivo": "",
                "t_paso": None, "inicio": None, "fin": None, "resumen": None, "motivo": ""}

    # --- proceso ---

    def lanzar(self, ejecutable: list = None):
        cmd = ejecutable or [sys.executable, "-u", "-m", PAQUETE, *self.argv]
        ruta_python = os.pathsep.join(filter(None, [str(CARPETA_PROGRAMA),
                                                    os.environ.get("PYTHONPATH")]))
        entorno = {**os.environ, VARIABLE_PROGRESO: "1", "PYTHONIOENCODING": "utf-8",
                   "PYTHONUNBUFFERED": "1", "PYTHONPATH": ruta_python}
        extra = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                 else {"start_new_session": True})
        self.proceso = subprocess.Popen(
            cmd, cwd=CARPETA_PROGRAMA, env=entorno, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, **extra)
        threading.Thread(target=self._leer, name=f"trabajo-{self.numero}", daemon=True).start()

    def _leer(self):
        try:
            for linea in self.proceso.stdout:
                self.procesar_linea(linea.rstrip("\r\n"))
        finally:
            self.proceso.stdout.close()
            self.terminar(self.proceso.wait())

    def detener(self) -> bool:
        """Como Ctrl+C: el programa se detiene en orden. Si no responde, se fuerza."""
        with self.lock:
            if self.estado != "en_marcha" or self.proceso is None:
                return False
            self.estado, self.detener_pedido = "deteniendo", True
        self._anotar("normal", "— Deteniendo (como Ctrl+C): se descarta lo que estaba a medias…")
        try:
            if os.name == "nt":
                self.proceso.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(self.proceso.pid, signal.SIGINT)
        except OSError:
            self._forzar()
            return True
        temporizador = threading.Timer(ESPERA_DETENER, self._forzar)
        temporizador.daemon = True
        temporizador.start()
        return True

    def _forzar(self):
        if self.proceso is None or self.proceso.poll() is not None:
            return
        self._anotar("aviso", "AVISO: no se detenía; se fuerza el cierre (vuelve a ejecutar "
                              "para completar lo que quedara a medias).")
        try:
            if os.name == "nt":   # también sus FFmpeg
                subprocess.run(["taskkill", "/PID", str(self.proceso.pid), "/T", "/F"],
                               capture_output=True, timeout=30)
            else:
                os.killpg(self.proceso.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            self.proceso.kill()

    def terminar(self, codigo: int):
        with self.lock:
            self.codigo, self.fin = codigo, time.time()
            if codigo == 0:
                self.estado = "terminado"
            else:
                self.estado = "detenido" if self.detener_pedido else "error"
            for f in self.fases:
                if f["estado"] == "en_curso":
                    f["estado"] = "hecha" if codigo == 0 else (
                        "detenida" if self.detener_pedido else "fallida")
                    f["fin"] = self.fin
                elif f["estado"] == "pendiente" and codigo == 0:
                    f["estado"] = "omitida"
            self.videos.clear()
        if self.al_terminar:
            self.al_terminar(self)

    # --- salida del programa ---

    def _anotar(self, nivel: str, texto: str):
        with self.lock:
            self.lineas.append((nivel, texto))
            self.errores += nivel == "error"
            self.avisos += nivel == "aviso"
            if len(self.lineas) > MAX_LINEAS:
                quitar = len(self.lineas) - MAX_LINEAS + MAX_LINEAS // 4
                del self.lineas[:quitar]
                self.base += quitar

    def procesar_linea(self, linea: str):
        if linea.startswith(MARCA_PROGRESO):
            try:
                evento = json.loads(linea[len(MARCA_PROGRESO):])
            except ValueError:
                evento = None
            if isinstance(evento, dict):
                with self.lock:
                    self._evento(evento)
                return
        self._anotar(_nivel(linea), linea)

    def _buscar_fase(self, nombre: str) -> dict:
        for f in self.fases:
            if f["fase"] == nombre:
                return f
        f = self._fase(nombre)
        self.fases.append(f)
        return f

    def _evento(self, e: dict):
        if not e.get("fase"):
            return
        ahora = time.time()
        tipo, f = e.get("evento"), self._buscar_fase(str(e["fase"]))
        if tipo in ("inicio", "avance") and f["estado"] == "pendiente":
            f["estado"], f["inicio"] = "en_curso", ahora
            for anterior in self.fases[:self.fases.index(f)]:
                if anterior["estado"] == "pendiente":
                    anterior["estado"] = "omitida"
        if tipo == "avance":
            paso = str(e.get("paso", ""))
            if paso != f["paso"]:
                f["paso"], f["t_paso"] = paso, ahora
            f["hecho"], f["total"] = int(e.get("hecho") or 0), int(e.get("total") or 0)
            f["archivo"] = str(e.get("archivo", ""))
        elif tipo == "video":
            self.videos[str(e.get("archivo", ""))] = e.get("porcentaje") or 0
        elif tipo == "video_fin":
            self.videos.pop(str(e.get("archivo", "")), None)
        elif tipo == "resumen":
            f["resumen"] = e.get("resumen")
        elif tipo == "fin":
            f["estado"], f["fin"], f["archivo"] = "hecha", ahora, ""
            if e.get("resumen") is not None:
                f["resumen"] = e["resumen"]
            if f["fase"] == "videos":
                self.videos.clear()
        elif tipo == "omitida":
            f["estado"], f["motivo"] = "omitida", str(e.get("motivo", ""))

    # --- estado para la web ---

    def estado_json(self, desde: int = 0) -> dict:
        ahora = time.time()
        with self.lock:
            desde = max(self.base, min(desde, self.base + len(self.lineas)))
            lineas = self.lineas[desde - self.base:desde - self.base + LINEAS_POR_RESPUESTA]
            fases = []
            for f in self.fases:
                fase = {k: v for k, v in f.items() if k not in ("t_paso", "inicio", "fin")}
                activa = f["estado"] == "en_curso"
                fase["segundos_paso"] = round(ahora - f["t_paso"], 1) \
                    if activa and f["t_paso"] else None
                if f["inicio"]:
                    fase["duracion"] = round((f["fin"] or ahora) - f["inicio"], 1)
                fases.append(fase)
            return {
                "numero": self.numero, "comando": self.comando, "titulo": self.titulo,
                "simular": self.simular, "valores": self.valores, "linea": self.linea,
                "estado": self.estado, "codigo": self.codigo, "carpeta": str(self.carpeta),
                "galeria_existe": (self.carpeta / "galeria.html").is_file(),
                "inicio": self.inicio, "fin": self.fin,
                "duracion": round((self.fin or ahora) - self.inicio, 1),
                "fases": fases, "errores": self.errores, "avisos": self.avisos,
                "videos": [{"archivo": a, "porcentaje": p} for a, p in self.videos.items()],
                "mensaje": self._mensaje_final(),
                "registro": {"desde": desde, "lineas": lineas,
                             "total": self.base + len(self.lineas)},
            }

    def _mensaje_final(self) -> str:
        """Si terminó con error, la última línea con texto (p. ej. el motivo de sys.exit)."""
        if self.estado != "error":
            return ""
        for _, texto in reversed(self.lineas):
            if texto.strip():
                return texto.strip()
        return f"El programa terminó con el código {self.codigo}"

    def registro_texto(self) -> str:
        with self.lock:
            return "\n".join(texto for _, texto in self.lineas) + "\n"

    def para_historial(self) -> dict:
        with self.lock:
            return {
                "numero": self.numero, "comando": self.comando, "titulo": self.titulo,
                "simular": self.simular, "valores": self.valores, "linea": self.linea,
                "estado": self.estado, "carpeta": str(self.carpeta),
                "inicio": self.inicio, "fin": self.fin, "errores": self.errores,
                "resumen": {f["fase"]: f["resumen"] for f in self.fases if f["resumen"]},
            }


# ----------------------------- Panel (estado global) -----------------------------

class Panel:
    """Ejecución en curso, historial, preferencias y servidores de galería abiertos."""

    def __init__(self, ruta_preferencias: Path = PREFERENCIAS):
        self.ruta_preferencias = ruta_preferencias
        self.lock = threading.Lock()
        self.trabajo = None
        self.galerias = {}
        self.lock_dialogo = threading.Lock()
        self.preferencias = self._leer_preferencias()
        historial = self.preferencias["historial"]
        self.siguiente = max((h.get("numero", 0) for h in historial), default=0) + 1

    # --- preferencias ---

    def _leer_preferencias(self) -> dict:
        try:
            datos = json.loads(self.ruta_preferencias.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            datos = {}
        if not isinstance(datos, dict):
            datos = {}
        return {"comando": datos.get("comando") if datos.get("comando") in ESQUEMA else "todo",
                "valores": datos.get("valores") if isinstance(datos.get("valores"), dict) else {},
                "recientes": [r for r in datos.get("recientes", []) if isinstance(r, str)],
                "historial": [h for h in datos.get("historial", []) if isinstance(h, dict)]}

    def _guardar_preferencias(self):
        try:
            self.ruta_preferencias.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.ruta_preferencias.with_name(self.ruta_preferencias.name + ".part")
            tmp.write_text(json.dumps(self.preferencias, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, self.ruta_preferencias)
        except OSError as exc:
            print(f"AVISO: no se han podido guardar las preferencias del panel: {exc}")

    def _recordar(self, comando: str, valores: dict, carpetas: list):
        p = self.preferencias
        p["comando"], p["valores"] = comando, {**p["valores"], **valores}
        recientes = [c for c in carpetas if c] + p["recientes"]
        p["recientes"] = list(dict.fromkeys(recientes))[:MAX_RECIENTES]
        self._guardar_preferencias()

    # --- ejecuciones ---

    def ejecutar(self, comando: str, valores: dict, simular: bool) -> Trabajo:
        previa = comprobar(comando, valores, simular)
        with self.lock:
            if self.trabajo and self.trabajo.estado in ("en_marcha", "deteniendo"):
                raise ErrorPanel("Ya hay una ejecución en marcha: espera a que termine o detenla.")
            dests = {o["dest"] for o in ESQUEMA[comando]["opciones"]}
            valores = {k: v for k, v in valores.items()
                       if k in dests and k != "simular" and isinstance(v, (str, bool, int, float))}
            trabajo = Trabajo(self.siguiente, comando, valores, simular, previa)
            trabajo.al_terminar = self._terminado
            try:
                trabajo.lanzar()
            except OSError as exc:
                raise ErrorPanel(f"No se ha podido lanzar el exportador: {exc}") from None
            self.siguiente += 1
            self.trabajo = trabajo
            args = previa["args"]
            carpetas = [str(getattr(args, d).resolve()) for d in ("origen", "coleccion", "destino",
                                                                  "carpeta", "biblioteca")
                        if getattr(args, d, None)]
            self._recordar(comando, valores, carpetas + [previa["carpeta"]])
        return trabajo

    def _terminado(self, trabajo: Trabajo):
        with self.lock:
            historial = [trabajo.para_historial()] + [
                h for h in self.preferencias["historial"] if h.get("numero") != trabajo.numero]
            self.preferencias["historial"] = historial[:MAX_HISTORIAL]
            self._guardar_preferencias()

    def detener(self) -> bool:
        trabajo = self.trabajo
        return bool(trabajo and trabajo.detener())

    def cerrar(self, esperar: float = ESPERA_DETENER):
        trabajo = self.trabajo
        if trabajo and trabajo.detener():
            print("Deteniendo la ejecución en curso…")
            try:
                trabajo.proceso.wait(esperar)
            except subprocess.TimeoutExpired:
                trabajo._forzar()
        for servidor in self.galerias.values():
            servidor.shutdown()
            servidor.server_close()

    # --- utilidades del escritorio ---

    def abrir_galeria(self, carpeta: str) -> str:
        carpeta = Path(carpeta).resolve()
        if not (carpeta / "galeria.html").is_file():
            raise ErrorPanel("Esa carpeta aún no tiene galería: genérala primero.")
        with self.lock:
            servidor = self.galerias.get(str(carpeta))
            if servidor is None:
                servidor = crear_servidor(carpeta, 8080)
                threading.Thread(target=servidor.serve_forever, daemon=True).start()
                self.galerias[str(carpeta)] = servidor
        return f"http://127.0.0.1:{servidor.server_address[1]}/galeria.html"

    def elegir_carpeta(self, inicial: str = "", titulo: str = "Elige una carpeta") -> str:
        """Diálogo nativo de Windows/macOS/Linux para elegir carpeta ("" si se cancela)."""
        if not self.lock_dialogo.acquire(blocking=False):
            raise ErrorPanel("Ya hay una ventana para elegir carpeta abierta.")
        try:
            inicial = inicial if inicial and Path(inicial).is_dir() else ""
            r = subprocess.run([sys.executable, "-I", "-c", _DIALOGO, inicial, titulo],
                               capture_output=True, timeout=1800, encoding="utf-8",
                               errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        except (OSError, subprocess.SubprocessError) as exc:
            raise ErrorPanel(f"No se ha podido abrir el selector de carpetas: {exc}") from None
        finally:
            self.lock_dialogo.release()
        if r.returncode != 0:
            raise ErrorPanel("No se ha podido abrir el selector de carpetas (falta tkinter); "
                             "escribe o pega la ruta.")
        ruta = r.stdout.strip()
        return str(Path(ruta)) if ruta else ""

    @staticmethod
    def abrir_carpeta(carpeta: str):
        ruta = Path(carpeta)
        if not ruta.is_dir():
            raise ErrorPanel(f"La carpeta no existe: {carpeta}")
        if os.name == "nt":
            os.startfile(ruta)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(ruta)])


_DIALOGO = r"""
import sys, tkinter
from tkinter import filedialog
raiz = tkinter.Tk()
raiz.withdraw()
raiz.attributes("-topmost", True)
raiz.update()
ruta = filedialog.askdirectory(parent=raiz, initialdir=sys.argv[1] or None,
                               title=sys.argv[2], mustexist=True)
sys.stdout.write(ruta or "")
"""


# ----------------------------- HTTP -----------------------------

class ManejadorPanel(SoloLocal, BaseHTTPRequestHandler):
    panel: Panel = None   # se asigna al crear el servidor

    def log_message(self, formato, *args):
        pass

    def _json(self, estado, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _error(self, estado, mensaje):
        self._json(estado, {"error": mensaje})

    def do_GET(self):
        if not self._host_valido():
            return self.send_error(HTTPStatus.FORBIDDEN, "Host no permitido")
        ruta = self._ruta_peticion()
        consulta = parse_qs(urlsplit(self.path).query)
        if ruta in ("/", "/index.html", "/panel.html"):
            cuerpo = PLANTILLA.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(cuerpo)
        elif ruta == "/api/esquema":
            self._json(HTTPStatus.OK, ESQUEMA)
        elif ruta == "/api/preferencias":
            with self.panel.lock:
                self._json(HTTPStatus.OK, self.panel.preferencias)
        elif ruta == "/api/estado":
            try:
                desde = int(consulta.get("desde", ["0"])[0])
            except ValueError:
                desde = 0
            trabajo = self.panel.trabajo
            self._json(HTTPStatus.OK, {"trabajo": trabajo.estado_json(desde) if trabajo else None})
        elif ruta == "/api/registro":
            trabajo = self.panel.trabajo
            if not trabajo:
                return self.send_error(HTTPStatus.NOT_FOUND)
            cuerpo = trabajo.registro_texto().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition",
                             f'attachment; filename="exportador_{trabajo.numero}.log"')
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if not self._host_valido() or not self._origen_valido():
            return self.send_error(HTTPStatus.FORBIDDEN, "Origen no permitido")
        # Exigir JSON obliga al navegador a pedir permiso (CORS) a cualquier otra web
        if "application/json" not in self.headers.get("Content-Type", ""):
            return self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            longitud = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            longitud = -1
        if not 0 <= longitud <= MAX_CUERPO:
            return self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            datos = json.loads(self.rfile.read(longitud) or b"{}")
        except ValueError:
            return self._error(HTTPStatus.BAD_REQUEST, "JSON no válido")
        if not isinstance(datos, dict):
            return self._error(HTTPStatus.BAD_REQUEST, "Se esperaba un objeto JSON")
        acciones = {
            "/api/comprobar": self._comprobar, "/api/ejecutar": self._ejecutar,
            "/api/detener": self._detener, "/api/galeria": self._galeria,
            "/api/elegir-carpeta": self._elegir_carpeta, "/api/abrir-carpeta": self._abrir,
        }
        accion = acciones.get(self._ruta_peticion())
        if accion is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        try:
            accion(datos)
        except ErrorPanel as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def _comprobar(self, datos):
        try:
            r = comprobar(datos.get("comando"), datos.get("valores") or {},
                          bool(datos.get("simular")))
        except ErrorPanel as exc:
            # Aun con error, la línea de comandos ayuda a ver qué se va a hacer
            try:
                argv = construir_argv(datos.get("comando"), datos.get("valores") or {},
                                      bool(datos.get("simular")))
                linea = linea_de_comandos(argv)
            except ErrorPanel:
                linea = ""
            return self._json(HTTPStatus.OK, {"error": str(exc), "linea": linea})
        r.pop("args")
        self._json(HTTPStatus.OK, r)

    def _ejecutar(self, datos):
        trabajo = self.panel.ejecutar(datos.get("comando"), datos.get("valores") or {},
                                      bool(datos.get("simular")))
        self._json(HTTPStatus.OK, {"numero": trabajo.numero})

    def _detener(self, datos):
        self._json(HTTPStatus.OK, {"ok": self.panel.detener()})

    def _galeria(self, datos):
        self._json(HTTPStatus.OK, {"url": self.panel.abrir_galeria(str(datos.get("carpeta", "")))})

    def _elegir_carpeta(self, datos):
        ruta = self.panel.elegir_carpeta(str(datos.get("inicial") or ""),
                                         str(datos.get("titulo") or "Elige una carpeta")[:120])
        self._json(HTTPStatus.OK, {"ruta": ruta})

    def _abrir(self, datos):
        self.panel.abrir_carpeta(str(datos.get("carpeta", "")))
        self._json(HTTPStatus.OK, {"ok": True})


def crear_panel(puerto: int = 8765, intentos: int = 10, panel: Panel = None):
    """(servidor, panel) ligado a 127.0.0.1 en el primer puerto libre desde `puerto`."""
    panel = panel or Panel()
    manejador = type("ManejadorPanelConEstado", (ManejadorPanel,), {"panel": panel})
    return ligar_local(manejador, puerto, intentos), panel


def servir_panel(puerto: int = 8765, abrir_navegador: bool = True):
    servidor, panel = crear_panel(puerto)
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    print(f"Panel del exportador en {url}  (solo desde este equipo; Ctrl+C para cerrarlo)")
    if abrir_navegador:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando el panel…")
    finally:
        panel.cerrar()
        servidor.server_close()
