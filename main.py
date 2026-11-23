#!/usr/bin/env python3
"""
Exportador — organiza, renombra y optimiza fotos, vídeos y audio, y crea una galería web local.

Uso:
    python main.py fotos   <origen> [--destino DEST] [--simular] [opciones de fotos]
    python main.py videos  <origen> [--destino DEST] [--simular] [opciones de vídeo]
    python main.py audio   <origen> [--destino DEST] [--simular]
    python main.py todo    <origen> [--destino DEST] [--simular] [--servir] [--sin-audio]
    python main.py google  <takeout/Google Fotos> [--destino DEST] [--simular] [--servir]
    python main.py galeria <carpeta> [--servir] [--puerto N] [--regenerar] [--caras]
    python main.py reorganizar <biblioteca> [--whatsapp] [--fechas-aproximadas] [--simular]

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
        description="Organiza, renombra y optimiza tus fotos, vídeos y notas de voz, y crea "
                    "una galería web local. El origen solo se lee: nunca se modifica.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("origen", type=Path, help="Carpeta con los archivos a importar")
    comun.add_argument("--destino", type=Path, default=None,
                       help="Biblioteca destino (por defecto: <origen>_organizados)")
    comun.add_argument("--simular", action="store_true",
                       help="Muestra qué haría sin crear, mover ni modificar nada")
    comun.add_argument("--con-originales", action="store_true",
                       help="Guardar además una copia intacta de cada original en "
                            "originales/ (el origen nunca se toca)")
    comun.add_argument("--renombrar-aproximadas", action="store_true",
                       help="Renombrar también lo YA importado con nombre AAAAMMDD_000000 "
                            "(fecha sacada del nombre sin hora); solo dentro de la biblioteca")
    # Compatibilidad: no copiar los originales es ya el comportamiento por defecto
    comun.add_argument("--sin-originales", action="store_true", help=argparse.SUPPRESS)

    op_fotos = argparse.ArgumentParser(add_help=False)
    g = op_fotos.add_argument_group("fotos")
    g.add_argument("--max-lado", dest="max_lado_fotos", type=_positivo, default=3200,
                   help="Lado largo máximo de las fotos en px (0 = no reducir; por defecto 3200)")
    g.add_argument("--calidad", type=_calidad, default=88,
                   help="Calidad de compresión 1-100 (por defecto 88)")
    g.add_argument("--formato", choices=["jpeg", "webp"], default="jpeg",
                   help="jpeg = universal | webp = ~30 %% menos peso (por defecto jpeg)")
    g.add_argument("--hilos", type=_positivo, default=0,
                   help="Fotos en paralelo (por defecto: según los núcleos del equipo)")
    g.add_argument("--omitir-parecidas", action="store_true",
                   help="No importar la peor copia de cada grupo de fotos casi idénticas "
                        "(p. ej. WhatsApp Sent/ e Images/). Nada se borra del origen")
    g.add_argument("--pegatinas-aparte", action="store_true",
                   help="Pegatinas de WhatsApp en WhatsApp/Pegatinas/ en vez de con el resto "
                        "de WhatsApp (que ya va siempre separado, en WhatsApp/)")

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
    g.add_argument("--hilos-video", type=_positivo, default=1,
                   help="Vídeos codificándose a la vez (por defecto 1; 2-3 si sobra CPU/GPU)")
    g.add_argument("--hw", choices=["auto", "nvenc", "qsv", "amf", "no"], default="no",
                   help="Codificación por hardware: auto = la que ofrezca el FFmpeg instalado "
                        "(NVIDIA nvenc, Intel qsv, AMD amf); si falla, se repite por software. "
                        "Por defecto no (software, archivos algo menores)")

    servir = argparse.ArgumentParser(add_help=False)
    g = servir.add_argument_group("galería")
    g.add_argument("--servir", action="store_true",
                   help="Levanta un servidor local y abre el navegador")
    g.add_argument("--puerto", type=int, default=8080,
                   help="Puerto del servidor local (por defecto 8080; si está ocupado, el siguiente)")
    g.add_argument("--sin-navegador", action="store_true",
                   help="Con --servir, no abrir el navegador automáticamente")
    g.add_argument("--caras", action="store_true",
                   help="Detectar y agrupar caras para nombrarlas en la galería (local; "
                        "requiere pip install opencv-python). Solo analiza lo nuevo")
    g.add_argument("--descargar-lugares", action="store_true",
                   help="Descargar una vez las ciudades de GeoNames (~3 MB) para mostrar el "
                        "lugar de las fotos con GPS sin conexión")
    g.add_argument("--descargar-modelos-caras", action="store_true",
                   help="Descargar una vez los modelos YuNet/SFace de OpenCV Zoo (~38 MB) "
                        "para agrupar bien las caras")

    sub.add_parser("fotos", parents=[comun, op_fotos], help="Organizar y optimizar fotos")

    p_videos = sub.add_parser("videos", parents=[comun, op_videos],
                              help="Organizar y comprimir vídeos")
    # Compatibilidad: en "videos" --max-lado sigue refiriéndose a los vídeos
    p_videos.add_argument("--max-lado", dest="max_lado_video", type=_positivo,
                          help=argparse.SUPPRESS)

    sub.add_parser("audio", parents=[comun],
                   help="Organizar notas de voz y audios (.opus .mp3 .m4a .aac .ogg .wav), "
                        "copiados sin recomprimir")

    p_todo = sub.add_parser("todo", parents=[comun, op_fotos, op_videos, servir],
                            help="Fotos + vídeos + audio + galería en un solo paso")
    p_todo.add_argument("--sin-audio", action="store_true",
                        help="No importar notas de voz ni audios")
    p_todo.add_argument("--sin-galeria", action="store_true",
                        help="No generar la galería al terminar")

    p_google = sub.add_parser(
        "google", parents=[comun, op_fotos, op_videos, servir],
        help="Importar un Takeout de Google Fotos (fotos + vídeos + galería) grabando en "
             "cada archivo los metadatos de su JSON",
        description="Como 'todo', para la carpeta 'Google Fotos' de un Takeout. Cada foto y "
                    "vídeo recibe lo que dice su JSON y no trae dentro (fecha, GPS), además "
                    "de descripción, personas y álbumes (como etiquetas). Los JSON no se "
                    "copian. Las copias '-editada' se omiten si está su original, y el clip "
                    "de cada foto con movimiento (.MP) se importa como vídeo con su mismo "
                    "nombre. El origen solo se lee.")
    p_google.add_argument("--sin-galeria", action="store_true",
                          help="No generar la galería al terminar")

    p_reo = sub.add_parser(
        "reorganizar", help="Ordenar una biblioteca ya importada (solo dentro de ella)",
        description="Mueve o renombra archivos ya importados, solo dentro de la biblioteca, "
                    "y actualiza catálogo, galería y favoritos. El origen no se toca.")
    p_reo.add_argument("biblioteca", type=Path, help="Biblioteca ya organizada")
    p_reo.add_argument("--whatsapp", action="store_true",
                       help="Separar en WhatsApp/ lo de WhatsApp importado mezclado con el resto")
    p_reo.add_argument("--fechas-aproximadas", action="store_true",
                       help="Renombrar AAAAMMDD_000000 (fecha del nombre sin hora) con la hora "
                            "del archivo si es del mismo día, o como AAAAMMDD_WA0011")
    p_reo.add_argument("--pegatinas-aparte", action="store_true",
                       help="Con --whatsapp, las pegatinas a WhatsApp/Pegatinas/")
    p_reo.add_argument("--simular", action="store_true",
                       help="Muestra qué movería sin tocar nada")

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
                         formato=args.formato, conservar_originales=args.con_originales,
                         hilos=args.hilos, omitir_parecidas=args.omitir_parecidas,
                         pegatinas_aparte=args.pegatinas_aparte)


def opciones_videos(args):
    from videos import OpcionesVideos
    return OpcionesVideos(codec=args.codec, max_lado=args.max_lado_video,
                          crf=args.crf, preset=args.preset,
                          conservar_originales=args.con_originales,
                          hilos=args.hilos_video or 1, hw=args.hw)


def galeria(carpeta: Path, args, regenerar: bool = False):
    if not hay_pillow():
        sys.exit(MENSAJE_PILLOW)
    if args.descargar_lugares:
        from lugares import descargar_lugares
        descargar_lugares()
    if args.descargar_modelos_caras:
        from caras import descargar_modelos
        descargar_modelos()
    from galeria import generar_galeria
    if generar_galeria(carpeta, regenerar, caras=args.caras) and args.servir:
        from servidor import servir
        servir(carpeta, args.puerto, abrir_navegador=not args.sin_navegador)


def main(argv=None):
    configurar_consola()
    args = construir_parser().parse_args(argv)

    if args.comando == "reorganizar":
        biblioteca = args.biblioteca.resolve()
        if not biblioteca.is_dir():
            sys.exit(f"La carpeta no existe: {biblioteca}")
        if not (args.whatsapp or args.fechas_aproximadas):
            sys.exit("Indica qué reorganizar: --whatsapp y/o --fechas-aproximadas")
        from reorganizar import reorganizar
        reorganizar(biblioteca, args.simular, whatsapp=args.whatsapp,
                    fechas=args.fechas_aproximadas, pegatinas_aparte=args.pegatinas_aparte)
        return

    if args.comando == "galeria":
        carpeta = args.carpeta.resolve()
        if not carpeta.is_dir():
            sys.exit(f"La carpeta no existe: {carpeta}")
        galeria(carpeta, args, args.regenerar)
        return

    origen, destino = validar_origen_destino(args.origen, args.destino, args.simular)
    print(f"Origen  : {origen}\nDestino : {destino}")

    externos = None
    if args.comando == "google":
        if not hay_pillow():
            sys.exit(MENSAJE_PILLOW)
        from takeout import IndiceTakeout
        print("\nLeyendo los JSON de Google Fotos...")
        externos = IndiceTakeout(origen)
        print(externos.resumen())

    if args.comando in ("fotos", "todo", "google"):
        if not hay_pillow():
            sys.exit(MENSAJE_PILLOW)
        from fotos import procesar_fotos
        opciones = opciones_fotos(args)
        opciones.externos = externos
        procesar_fotos(origen, destino, args.simular, opciones)

    if args.comando in ("videos", "todo", "google"):
        if hay_ffmpeg():
            from videos import procesar_videos
            opciones = opciones_videos(args)
            opciones.externos = externos
            procesar_videos(origen, destino, args.simular, opciones)
        elif args.comando == "videos":
            sys.exit(MENSAJE_FFMPEG)
        else:
            print("\nAVISO: se omiten los vídeos porque FFmpeg no está instalado "
                  "(winget install Gyan.FFmpeg).")

    if args.comando == "audio" or (args.comando == "todo" and not args.sin_audio):
        from audio import procesar_audio
        procesar_audio(origen, destino, args.simular)

    if args.renombrar_aproximadas and (destino / ".exportador").exists():
        from reorganizar import reorganizar
        reorganizar(destino, args.simular, fechas=True)

    if args.comando in ("todo", "google") and not args.simular and not args.sin_galeria:
        print()
        galeria(destino, args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
