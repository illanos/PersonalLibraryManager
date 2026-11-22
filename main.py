#!/usr/bin/env python3
"""
Exportador — organiza, renombra y optimiza fotos y vídeos.

Uso:
    python main.py fotos  <origen> [--destino DEST] [--simular]
    python main.py videos <origen> [--destino DEST] [--simular] [--codec h264|vp9] [--max-lado N]

Ejemplos:
    python main.py fotos  "C:\\Users\\Tu\\Pictures\\MisFotos" --simular
    python main.py videos "C:\\Users\\Tu\\Videos" --codec vp9
"""

import argparse
import shutil
import sys
from pathlib import Path

from fotos import procesar_fotos
from videos import procesar_videos


def validar_origen_destino(args):
    origen = args.origen.resolve()
    if not origen.is_dir():
        sys.exit(f"La carpeta de origen no existe: {origen}")

    destino = (args.destino or origen.with_name(origen.name + "_organizados")).resolve()
    destino.mkdir(parents=True, exist_ok=True)

    if origen == destino or origen in destino.parents:
        sys.exit("El destino no puede estar dentro del origen ni coincidir con él.")

    return origen, destino


def main():
    parser = argparse.ArgumentParser(
        prog="exportador",
        description="Organiza, renombra y optimiza tus fotos y vídeos.",
    )
    subparsers = parser.add_subparsers(dest="comando", required=True)

    # --- fotos ---
    p_fotos = subparsers.add_parser("fotos", help="Organizar y optimizar fotos")
    p_fotos.add_argument("origen", type=Path, help="Carpeta con las fotos")
    p_fotos.add_argument("--destino", type=Path, default=None,
                         help="Carpeta destino (por defecto: <origen>_organizados)")
    p_fotos.add_argument("--simular", action="store_true",
                         help="Muestra qué haría sin modificar nada")

    # --- videos ---
    p_videos = subparsers.add_parser("videos", help="Organizar y comprimir vídeos")
    p_videos.add_argument("origen", type=Path, help="Carpeta con los vídeos")
    p_videos.add_argument("--destino", type=Path, default=None,
                          help="Carpeta destino (por defecto: <origen>_organizados)")
    p_videos.add_argument("--simular", action="store_true",
                          help="Muestra qué haría sin modificar nada")
    p_videos.add_argument("--codec", choices=["h264", "vp9"], default="h264",
                          help="h264 = MP4 universal | vp9 = WebM totalmente libre")
    p_videos.add_argument("--max-lado", type=int, default=1920,
                          help="Resolución máxima del lado largo en px (1920 = Full HD)")

    # --- galeria ---
    p_gal = subparsers.add_parser("galeria",
                                  help="Generar y servir una galería web local")
    p_gal.add_argument("carpeta", type=Path,
                       help="Carpeta con las fotos/vídeos ya organizados")
    p_gal.add_argument("--servir", action="store_true",
                       help="Levanta un servidor local y abre el navegador")
    p_gal.add_argument("--puerto", type=int, default=8080,
                       help="Puerto del servidor local (por defecto 8080)")

    args = parser.parse_args()

    if args.comando == "galeria":
        from galeria import generar_galeria, servir
        carpeta = args.carpeta.resolve()
        if not carpeta.is_dir():
            sys.exit(f"La carpeta no existe: {carpeta}")
        if generar_galeria(carpeta) and args.servir:
            servir(carpeta, args.puerto)
        return

    origen, destino = validar_origen_destino(args)

    print(f"Origen  : {origen}\nDestino : {destino}")

    if args.comando == "fotos":
        try:
            import PIL  # noqa: F401
        except ImportError:
            sys.exit("Falta la librería Pillow. Instálala con:  pip install Pillow")
        procesar_fotos(origen, destino, args.simular)
    else:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            sys.exit("FFmpeg no está disponible en la terminal. Instálalo con:\n"
                     "    winget install Gyan.FFmpeg\n"
                     "y abre una terminal nueva antes de volver a ejecutar.")
        procesar_videos(origen, destino, args.simular, args.codec, args.max_lado)


if __name__ == "__main__":
    main()
