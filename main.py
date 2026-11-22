#!/usr/bin/env python3
"""
Exportador — organiza, renombra y optimiza fotos y vídeos, y crea una galería web local.

Uso:
    python main.py fotos   <origen> [--destino DEST] [--simular] [opciones de fotos]
    python main.py videos  <origen> [--destino DEST] [--simular] [opciones de vídeo]
    python main.py todo    <origen> [--destino DEST] [--simular] [--servir]
    python main.py galeria <carpeta> [--servir] [--puerto N] [--regenerar]

Ejemplos:
    python main.py todo   "C:\\Users\\Tu\\Pictures\\Movil" --simular
    python main.py fotos  "C:\\Users\\Tu\\Pictures\\MisFotos" --formato webp
    python main.py videos "C:\\Users\\Tu\\Videos" --codec h265
    python main.py galeria "C:\\Users\\Tu\\Pictures\\Movil_organizados" --servir

Ejecuta `python main.py <comando> -h` para ver todas las opciones.
"""

import argparse
import shutil
import sys
from pathlib import Path

from media_utils import configurar_consola


def _positivo(texto: str) -> int:
    valor = int(texto)
    if valor < 0:
        raise argparse.ArgumentTypeError("debe ser 0 o mayor")
    return valor


def _calidad(texto: str) -> int:
    valor = int(texto)
    if not 1 <= valor <= 100:
        raise argparse.ArgumentTypeError("debe estar entre 1 y 100")
    return valor


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exportador",
        description="Organiza, renombra y optimiza tus fotos y vídeos.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("origen", type=Path, help="Carpeta con los archivos a importar")
    comun.add_argument("--destino", type=Path, default=None,
                       help="Biblioteca destino (por defecto: <origen>_organizados)")
    comun.add_argument("--simular", action="store_true",
                       help="Muestra qué haría sin crear, mover ni modificar nada")

    op_fotos = argparse.ArgumentParser(add_help=False)
    g = op_fotos.add_argument_group("fotos")
    g.add_argument("--max-lado", dest="max_lado_fotos", type=_positivo, default=2560,
                   help="Lado largo máximo de las fotos en px (0 = no reducir; por defecto 2560)")
    g.add_argument("--calidad", type=_calidad, default=88,
                   help="Calidad de compresión 1-100 (por defecto 88)")
    g.add_argument("--formato", choices=["jpeg", "webp"], default="jpeg",
                   help="jpeg = universal | webp = ~30 %% menos peso (por defecto jpeg)")
    g.add_argument("--sin-originales", action="store_true",
                   help="No guardar copia de las fotos originales (el origen no se toca)")
    g.add_argument("--hilos", type=_positivo, default=0,
                   help="Fotos en paralelo (por defecto: según los núcleos del equipo)")

    op_videos = argparse.ArgumentParser(add_help=False)
    g = op_videos.add_argument_group("vídeos")
    g.add_argument("--codec", choices=["h264", "h265", "vp9"], default="h264",
                   help="h264 = MP4 universal | h265 = MP4 más ligero | vp9 = WebM libre")
    g.add_argument("--max-lado-video", dest="max_lado_video", type=_positivo, default=1920,
                   help="Lado largo máximo de los vídeos en px (0 = mantener; por defecto 1920)")
    g.add_argument("--crf", type=_positivo, default=None,
                   help="Calidad constante (menor = mejor; por defecto 23 h264, 28 h265, 32 vp9)")
    g.add_argument("--preset", default="medium",
                   choices=["ultrafast", "superfast", "veryfast", "faster", "fast",
                            "medium", "slow", "slower", "veryslow"],
                   help="Velocidad de codificación h264/h265 (más lento = archivos menores)")

    servir = argparse.ArgumentParser(add_help=False)
    g = servir.add_argument_group("galería")
    g.add_argument("--servir", action="store_true",
                   help="Levanta un servidor local y abre el navegador")
    g.add_argument("--puerto", type=int, default=8080,
                   help="Puerto del servidor local (por defecto 8080; si está ocupado, el siguiente)")
    g.add_argument("--sin-navegador", action="store_true",
                   help="Con --servir, no abrir el navegador automáticamente")

    sub.add_parser("fotos", parents=[comun, op_fotos], help="Organizar y optimizar fotos")

    p_videos = sub.add_parser("videos", parents=[comun, op_videos],
                              help="Organizar y comprimir vídeos")
    # Compatibilidad: en "videos" --max-lado sigue refiriéndose a los vídeos
    p_videos.add_argument("--max-lado", dest="max_lado_video", type=_positivo,
                          help=argparse.SUPPRESS)

    p_todo = sub.add_parser("todo", parents=[comun, op_fotos, op_videos, servir],
                            help="Fotos + vídeos + galería en un solo paso")
    p_todo.add_argument("--sin-galeria", action="store_true",
                        help="No generar la galería al terminar")

    p_gal = sub.add_parser("galeria", parents=[servir],
                           help="Generar (y servir) la galería web local")
    p_gal.add_argument("carpeta", type=Path, help="Biblioteca ya organizada")
    p_gal.add_argument("--regenerar", action="store_true",
                       help="Rehacer metadatos y miniaturas aunque no hayan cambiado")
    return parser


def validar_origen_destino(origen: Path, destino: Path, simular: bool):
    origen = origen.resolve()
    if not origen.is_dir():
        sys.exit(f"La carpeta de origen no existe: {origen}")
    destino = (destino or origen.with_name(origen.name + "_organizados")).resolve()
    if origen == destino or origen in destino.parents:
        sys.exit("El destino no puede estar dentro del origen ni coincidir con él.")
    if not simular:
        destino.mkdir(parents=True, exist_ok=True)
    return origen, destino


def hay_pillow() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def hay_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


MENSAJE_PILLOW = "Falta la librería Pillow. Instálala con:  pip install Pillow"
MENSAJE_FFMPEG = ("FFmpeg no está disponible en la terminal. Instálalo con:\n"
                  "    winget install Gyan.FFmpeg\n"
                  "y abre una terminal nueva antes de volver a ejecutar.")


def opciones_fotos(args):
    from fotos import OpcionesFotos
    return OpcionesFotos(max_lado=args.max_lado_fotos, calidad=args.calidad,
                         formato=args.formato, conservar_originales=not args.sin_originales,
                         hilos=args.hilos)


def opciones_videos(args):
    from videos import OpcionesVideos
    return OpcionesVideos(codec=args.codec, max_lado=args.max_lado_video,
                          crf=args.crf, preset=args.preset)


def galeria(carpeta: Path, args, regenerar: bool = False):
    if not hay_pillow():
        sys.exit(MENSAJE_PILLOW)
    from galeria import generar_galeria
    if generar_galeria(carpeta, regenerar) and args.servir:
        from servidor import servir
        servir(carpeta, args.puerto, abrir_navegador=not args.sin_navegador)


def main(argv=None):
    configurar_consola()
    args = construir_parser().parse_args(argv)

    if args.comando == "galeria":
        carpeta = args.carpeta.resolve()
        if not carpeta.is_dir():
            sys.exit(f"La carpeta no existe: {carpeta}")
        galeria(carpeta, args, args.regenerar)
        return

    origen, destino = validar_origen_destino(args.origen, args.destino, args.simular)
    print(f"Origen  : {origen}\nDestino : {destino}")

    if args.comando in ("fotos", "todo"):
        if not hay_pillow():
            sys.exit(MENSAJE_PILLOW)
        from fotos import procesar_fotos
        procesar_fotos(origen, destino, args.simular, opciones_fotos(args))

    if args.comando in ("videos", "todo"):
        if hay_ffmpeg():
            from videos import procesar_videos
            procesar_videos(origen, destino, args.simular, opciones_videos(args))
        elif args.comando == "videos":
            sys.exit(MENSAJE_FFMPEG)
        else:
            print("\nAVISO: se omiten los vídeos porque FFmpeg no está instalado "
                  "(winget install Gyan.FFmpeg).")

    if args.comando == "todo" and not args.simular and not args.sin_galeria:
        print()
        galeria(destino, args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
