"""
Línea de comandos de Notas: notas de texto, imágenes y notas de voz, con categorías y búsqueda.

Uso (con el paquete instalado, `notas` equivale a `python -m notas`):
    python -m notas abrir      [--puerto N]                 (la página web)
    python -m notas nueva      [texto] [--titulo T] [--categoria C] [--adjunto ARCHIVO]
    python -m notas listar     [--buscar T] [--categoria C] [--tipo texto|imagen|voz]
    python -m notas ver        <id>
    python -m notas editar     <id> [--titulo T] [--texto T] [--poner-categoria C] ...
    python -m notas borrar     <id> ...                     (a la papelera)
    python -m notas restaurar  <id> ...
    python -m notas categorias [--crear C] [--renombrar VIEJA NUEVA] [--borrar C]
    python -m notas copia      [destino.zip]
    python -m notas importar   <carpeta del Takeout>        (notas de Google Keep)

Las notas se guardan en ~/Notas, en la carpeta de NOTAS_CUADERNO o en la de --cuaderno.
"""

import argparse
import json
import signal
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .copia import crear_copia
from .cuaderno import COLORES, SIN_CATEGORIA, TIPOS, Cuaderno, carpeta_cuaderno
from .errores import ErrorNotas, NoEncontrada
from .keep import CALIDAD, LADO
from .servidor import PUERTO


def _puerto(texto: str) -> int:
    return _entre(1, 65535, texto)


def _entre(minimo: int, maximo: int, texto: str) -> int:
    valor = int(texto)
    if not minimo <= valor <= maximo:
        raise argparse.ArgumentTypeError(f"debe estar entre {minimo} y {maximo}")
    return valor


def _lado(texto: str) -> int:
    return 0 if texto == "0" else _entre(320, 20000, texto)


def _calidad(texto: str) -> int:
    return _entre(1, 95, texto)


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notas", description="Notas de texto, imágenes y notas de voz, con categorías y "
                                  "búsqueda. Todo se queda en este equipo.")
    parser.add_argument("--version", action="version", version=f"notas {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)

    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("--cuaderno", type=Path, default=None,
                       help="Carpeta de las notas (por defecto la de NOTAS_CUADERNO, o ~/Notas)")
    en_json = argparse.ArgumentParser(add_help=False)
    en_json.add_argument("--json", action="store_true", help="Salida en JSON")
    colores = [c for c in COLORES if c]

    p = sub.add_parser("abrir", parents=[comun], help="Abrir la página web de las notas")
    p.add_argument("--puerto", type=_puerto, default=PUERTO,
                   help=f"Puerto (por defecto {PUERTO}; si está ocupado, el siguiente)")
    p.add_argument("--sin-navegador", action="store_true",
                   help="No abrir el navegador automáticamente")

    p = sub.add_parser("nueva", parents=[comun, en_json], help="Crear una nota")
    p.add_argument("texto", nargs="?", default="",
                   help="Texto de la nota («-» para leerlo de la entrada estándar)")
    p.add_argument("--titulo", default="", help="Título")
    p.add_argument("--categoria", action="append", default=[], metavar="NOMBRE",
                   help="Categoría (se crea si no existe; se puede repetir)")
    p.add_argument("--adjunto", action="append", type=Path, default=[], metavar="ARCHIVO",
                   help="Imagen o audio que se copia a la nota (se puede repetir)")
    p.add_argument("--color", choices=colores, default="", help="Color de la nota")
    p.add_argument("--fijar", action="store_true", help="Dejarla fijada arriba")

    p = sub.add_parser("listar", parents=[comun, en_json], help="Listar y buscar notas")
    p.add_argument("--buscar", default="", metavar="TEXTO",
                   help="Todas las palabras, sin distinguir mayúsculas ni acentos; \"frase "
                        "exacta\" entre comillas y -palabra para excluir")
    p.add_argument("--categoria", metavar="NOMBRE", help="Solo las de esta categoría")
    p.add_argument("--sin-categoria", action="store_true", help="Solo las que no tienen categoría")
    p.add_argument("--tipo", choices=TIPOS, help="texto = sin adjuntos | lista = con casillas | imagen | voz")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--archivadas", action="store_true", help="Las archivadas")
    g.add_argument("--papelera", action="store_true", help="Las de la papelera")
    g.add_argument("--todas", action="store_true", help="También las archivadas")
    p.add_argument("--orden", choices=["modificada", "creada", "titulo"], default="modificada",
                   help="Orden (por defecto, las modificadas más recientemente)")
    p.add_argument("--limite", type=int, default=0, metavar="N", help="Como mucho N notas")

    p = sub.add_parser("ver", parents=[comun, en_json], help="Ver una nota entera")
    p.add_argument("id", type=int)

    p = sub.add_parser("editar", parents=[comun, en_json], help="Cambiar una nota")
    p.add_argument("id", type=int)
    p.add_argument("--titulo", default=None, help="Título nuevo")
    p.add_argument("--texto", default=None,
                   help="Texto nuevo («-» para leerlo de la entrada estándar)")
    p.add_argument("--anadir", default=None, metavar="TEXTO",
                   help="Añadir una línea al final del texto")
    p.add_argument("--poner-categoria", action="append", default=[], metavar="NOMBRE",
                   help="Ponerle una categoría (se puede repetir)")
    p.add_argument("--quitar-categoria", action="append", default=[], metavar="NOMBRE",
                   help="Quitarle una categoría (se puede repetir)")
    p.add_argument("--adjunto", action="append", type=Path, default=[], metavar="ARCHIVO",
                   help="Imagen o audio que se copia a la nota (se puede repetir)")
    p.add_argument("--color", choices=[*colores, "ninguno"], help="Color de la nota")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--fijar", action="store_true", help="Fijarla arriba")
    g.add_argument("--soltar", action="store_true", help="Dejar de tenerla fijada")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--archivar", action="store_true", help="Archivarla")
    g.add_argument("--desarchivar", action="store_true", help="Sacarla del archivo")

    p = sub.add_parser("borrar", parents=[comun],
                       help="Mandar notas a la papelera (se pueden restaurar)")
    p.add_argument("id", type=int, nargs="+")

    p = sub.add_parser("restaurar", parents=[comun], help="Sacar notas de la papelera")
    p.add_argument("id", type=int, nargs="+")

    p = sub.add_parser("categorias", parents=[comun, en_json],
                       help="Listar, crear, renombrar o quitar categorías")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--crear", metavar="NOMBRE", help="Crear una categoría")
    g.add_argument("--renombrar", nargs=2, metavar=("VIEJA", "NUEVA"), help="Cambiarle el nombre")
    g.add_argument("--borrar", metavar="NOMBRE",
                   help="Quitar la categoría (sus notas se quedan, sin ella)")

    p = sub.add_parser("copia", parents=[comun],
                       help="Copia de seguridad de todo el cuaderno en un ZIP")
    p.add_argument("destino", type=Path, nargs="?", default=None,
                   help="Archivo o carpeta (por defecto, en copias/ dentro del cuaderno)")

    p = sub.add_parser("importar", parents=[comun],
                       help="Importar las notas de Google Keep de un Takeout (que no se toca)")
    p.add_argument("carpeta", type=Path, help="Carpeta del Takeout, ya descomprimido")
    p.add_argument("--simular", action="store_true", help="Solo decir qué se importaría")
    p.add_argument("--lado", type=_lado, default=LADO, metavar="PX",
                   help=f"Lado mayor de las imágenes, en píxeles (por defecto {LADO}; "
                        "0 = tal cual están)")
    p.add_argument("--calidad", type=_calidad, default=CALIDAD, metavar="1-95",
                   help=f"Calidad JPEG de las imágenes (por defecto {CALIDAD})")
    return parser


# --- salida por la terminal ---

def _fecha(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M")


def _duracion(segundos) -> str:
    if not segundos:
        return ""
    minutos, resto = divmod(round(segundos), 60)
    return f" {minutos}:{resto:02d}"


def _linea(nota: dict) -> str:
    titulo = nota["titulo"] or next((l for l in nota["texto"].split("\n") if l.strip()), "")
    titulo = titulo.strip() or "(sin texto)"
    if len(titulo) > 70:
        titulo = titulo[:69] + "…"
    n_img = sum(a["tipo"] == "imagen" for a in nota["adjuntos"])
    n_voz = len(nota["adjuntos"]) - n_img
    extras = [f"{n_img} img" if n_img else "", f"{n_voz} voz" if n_voz else "",
              "fijada" if nota["fijada"] else "", "archivada" if nota["archivada"] else "",
              ", ".join(c["nombre"] for c in nota["categorias"])]
    extras = " · ".join(e for e in extras if e)
    return f"{nota['id']:>5}  {_fecha(nota['modificada'])}  {titulo}" + (
        f"  [{extras}]" if extras else "")


def _imprimir_nota(nota: dict, carpeta: Path):
    print(f"Nota {nota['id']}" + (f": {nota['titulo']}" if nota["titulo"] else ""))
    estado = [e for e, si in (("fijada", nota["fijada"]), ("archivada", nota["archivada"]),
                              ("en la papelera", nota["papelera"])) if si]
    print(f"  creada {_fecha(nota['creada'])} · modificada {_fecha(nota['modificada'])}"
          + (f" · {', '.join(estado)}" if estado else ""))
    if nota["categorias"]:
        print("  categorías: " + ", ".join(c["nombre"] for c in nota["categorias"]))
    if nota["texto"]:
        print("\n" + nota["texto"])
    if nota["adjuntos"]:
        print()
        for a in nota["adjuntos"]:
            print(f"  [{a['tipo']}]{_duracion(a['duracion'])} {a['nombre']}\n"
                  f"      {carpeta / a['archivo']}")
    if nota["detalles"]:
        print()
        _imprimir_detalles(nota["detalles"])


def _imprimir_detalles(detalles: dict):
    for e in detalles.get("enlaces", ()):
        print(f"  [enlace] {e['titulo']}\n      {e['url']}")
    if detalles.get("compartida"):
        print("  compartida con: " + ", ".join(detalles["compartida"]))
    if detalles.get("recordatorio"):
        print("  tenía un recordatorio")
    if detalles.get("faltan"):
        print("  faltan archivos: " + ", ".join(detalles["faltan"]))
    if detalles.get("fuente"):
        print(f"  importada de {detalles['fuente']}")


def _json(datos):
    print(json.dumps(datos, ensure_ascii=False, indent=1))


# --- comandos ---

def _leer_texto(texto: str) -> str:
    return sys.stdin.read() if texto == "-" else texto


def _comprobar_adjuntos(rutas):
    """Antes de crear nada: que existan todos y se puedan guardar."""
    from .adjuntos import BYTES_CABECERA, identificar
    for ruta in rutas:
        if not ruta.is_file():
            raise NoEncontrada(f"No existe el archivo {ruta}")
        with open(ruta, "rb") as f:
            identificar(f.read(BYTES_CABECERA), ruta.name)


def _nueva(cuaderno, args):
    texto = _leer_texto(args.texto)
    if not (texto.strip() or args.titulo.strip() or args.adjunto):
        raise ErrorNotas("La nota está vacía: escribe un texto, un título o añade un --adjunto")
    _comprobar_adjuntos(args.adjunto)
    nota = cuaderno.crear(args.titulo, texto, args.color, args.fijar, args.categoria)
    for ruta in args.adjunto:
        cuaderno.adjuntar_archivo(nota["id"], ruta)
    nota = cuaderno.nota(nota["id"])
    _json(nota) if args.json else print(f"Creada la nota {nota['id']}\n{_linea(nota)}")


def _id_categoria(cuaderno, nombre: str) -> int:
    id_categoria = cuaderno.buscar_categoria(nombre)
    if id_categoria is None:
        hay = ", ".join(c["nombre"] for c in cuaderno.categorias()) or "ninguna"
        raise NoEncontrada(f"No hay ninguna categoría «{nombre}» (hay: {hay})")
    return id_categoria


def _listar(cuaderno, args):
    vista = ("papelera" if args.papelera else "archivadas" if args.archivadas
             else "todas" if args.todas else "activas")
    categoria = (SIN_CATEGORIA if args.sin_categoria
                 else _id_categoria(cuaderno, args.categoria) if args.categoria else None)
    notas = cuaderno.listar(vista, args.buscar, categoria, args.tipo, args.orden,
                            max(0, args.limite) or None)
    if args.json:
        return _json(notas)
    for nota in notas:
        print(_linea(nota))
    print(f"{len(notas)} nota{'' if len(notas) == 1 else 's'}")


def _ver(cuaderno, args):
    nota = cuaderno.nota(args.id)
    _json(nota) if args.json else _imprimir_nota(nota, cuaderno.carpeta)


def _editar(cuaderno, args):
    nota = cuaderno.nota(args.id)
    cambios = {}
    if args.titulo is not None:
        cambios["titulo"] = args.titulo
    if args.texto is not None:
        cambios["texto"] = _leer_texto(args.texto)
    if args.anadir is not None:
        texto = cambios.get("texto", nota["texto"])
        cambios["texto"] = f"{texto.rstrip()}\n{args.anadir}" if texto.strip() else args.anadir
    if args.color is not None:
        cambios["color"] = "" if args.color == "ninguno" else args.color
    if args.fijar or args.soltar:
        cambios["fijada"] = args.fijar
    if args.archivar or args.desarchivar:
        cambios["archivada"] = args.archivar
    if not (cambios or args.adjunto or args.poner_categoria or args.quitar_categoria):
        raise ErrorNotas("No has indicado ningún cambio (mira `notas editar -h`)")
    _comprobar_adjuntos(args.adjunto)
    cuaderno.editar(args.id, nota["version"], **cambios)
    for nombre in args.quitar_categoria:
        cuaderno.lote([args.id], "quitar_categoria", nombre)
    for nombre in args.poner_categoria:
        cuaderno.lote([args.id], "poner_categoria", nombre)
    for ruta in args.adjunto:
        cuaderno.adjuntar_archivo(args.id, ruta)
    nota = cuaderno.nota(args.id)
    _json(nota) if args.json else print(_linea(nota))


def _mover(cuaderno, ids, accion: str, hecho: str):
    for id_nota in ids:
        cuaderno.nota(id_nota)           # si alguna no existe, no se toca ninguna
    n = cuaderno.lote(ids, accion)
    print(f"{n} nota{'' if n == 1 else 's'} {hecho}")


def _categorias(cuaderno, args):
    if args.crear:
        cuaderno.crear_categoria(args.crear)
    elif args.renombrar:
        cuaderno.renombrar_categoria(_id_categoria(cuaderno, args.renombrar[0]), args.renombrar[1])
    elif args.borrar:
        cuaderno.borrar_categoria(_id_categoria(cuaderno, args.borrar))
    categorias = cuaderno.categorias()
    if args.json:
        return _json(categorias)
    for c in categorias:
        print(f"{c['total']:>5}  {c['nombre']}")
    if not categorias:
        print("No hay categorías")


def _importar(carpeta: Path, args):
    from .keep import importar, leer

    def progreso(i, total):
        if not args.simular and (i % 100 == 0 or i == total):
            print(f"  {i} de {total}", flush=True)

    r = importar(carpeta, leer(args.carpeta), args.simular, args.lado, args.calidad, progreso)
    t = r.tipos
    mb = lambda b: f"{b / 1e6:.0f} MB"
    print(("Se importarían " if args.simular else "Importadas ")
          + f"{r.importadas} nota{'' if r.importadas == 1 else 's'} en {carpeta}")
    if r.importadas:
        print(f"  {t['activas']} activas · {t['archivadas']} archivadas · {t['papelera']} en la papelera "
              f"· {t['fijadas']} fijadas")
        print(f"  {t['texto']} sin adjuntos · {t['lista']} listas · {t['imagen']} con imágenes · "
              f"{t['voz']} con notas de voz")
        print(f"  {t['etiquetadas']} con categoría · {t['color']} con color · {t['enlaces']} con enlaces · "
              f"{t['compartidas']} compartidas · {t['recordatorio']} con recordatorio")
        print(f"  {t['imagenes']} imágenes y {t['audios']} audios: {mb(r.bytes_origen)}"
              + ("" if args.simular else f" -> {mb(r.bytes_final)}"))
    if r.repetidas:
        print(f"  {r.repetidas} ya estaban importadas")
    if r.vacias:
        print(f"  {r.vacias} vacías, que no se importan")
    for texto in r.avisos:
        print(f"  AVISO: {texto}")


def main(argv=None):
    args = construir_parser().parse_args(argv)
    carpeta = carpeta_cuaderno(args.cuaderno)
    try:
        if args.comando == "importar":
            return _importar(carpeta, args)
        # Solo al importar, abrir la página o crear una nota o categoría se estrena un cuaderno
        estrena = args.comando in ("abrir", "nueva") or getattr(args, "crear", None)
        cuaderno = Cuaderno(carpeta, crear=bool(estrena))
        if args.comando == "abrir":
            from .servidor import servir
            servir(cuaderno, args.puerto, not args.sin_navegador)
        elif args.comando == "nueva":
            _nueva(cuaderno, args)
        elif args.comando == "listar":
            _listar(cuaderno, args)
        elif args.comando == "ver":
            _ver(cuaderno, args)
        elif args.comando == "editar":
            _editar(cuaderno, args)
        elif args.comando == "borrar":
            _mover(cuaderno, args.id, "papelera", "a la papelera")
        elif args.comando == "restaurar":
            _mover(cuaderno, args.id, "restaurar", "fuera de la papelera")
        elif args.comando == "categorias":
            _categorias(cuaderno, args)
        elif args.comando == "copia":
            print(f"Copia guardada en {crear_copia(cuaderno, args.destino)}")
    except ErrorNotas as exc:
        sys.exit(f"ERROR: {exc}")
    except (sqlite3.Error, OSError) as exc:
        sys.exit(f"ERROR: no se puede usar el cuaderno {carpeta}: {exc}")


def ejecutar():
    """Punto de entrada: consola en UTF-8 y salida limpia al interrumpir."""
    for flujo in (sys.stdout, sys.stderr, sys.stdin):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8")
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
