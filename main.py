#!/usr/bin/env python3
"""
Exportador — organiza, renombra y optimiza fotos, vídeos y audio, y crea una galería web local.

Uso:
    python main.py fotos   <origen> [--destino DEST] [--simular] [opciones de fotos]
    python main.py videos  <origen> [--destino DEST] [--simular] [opciones de vídeo]
    python main.py audio   <origen> [--destino DEST] [--simular]
    python main.py todo    <origen> [--destino DEST] [--simular] [--servir] [--sin-audio]
    python main.py galeria <carpeta> [--servir] [--puerto N] [--regenerar] [--caras]
    python main.py reorganizar <biblioteca> [--whatsapp] [--fechas-aproximadas] [--simular]
    python main.py fusionar <colección> --destino <biblioteca> [--simular]
    python main.py panel   [--puerto N]      (panel web: opciones, ejecución y progreso)

Ejemplos:
    python main.py todo   "C:\\Users\\Tu\\Pictures\\Movil" --simular
    python main.py fotos  "C:\\Users\\Tu\\Pictures\\MisFotos" --formato webp
    python main.py videos "C:\\Users\\Tu\\Videos" --codec h265
    python main.py galeria "C:\\Users\\Tu\\Pictures\\Movil_organizados" --servir

Ejecuta `python main.py <comando> -h` para ver todas las opciones.
"""

import argparse
import shutil
import signal
import sys
from pathlib import Path

from media_utils import configurar_consola, progreso


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


def _umbral_fusion(texto: str) -> int:
    valor = int(texto)
    if not 0 <= valor <= 12:
        raise argparse.ArgumentTypeError("debe estar entre 0 y 12")
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

    p_fus = sub.add_parser(
        "fusionar", help="Añadir a una biblioteca otra colección sin repetir fotos ni vídeos",
        description="Añade a una biblioteca las fotos y vídeos de otra colección (otra biblioteca "
                    "del exportador o cualquier carpeta). Compara por días: lo que ya está no se "
                    "añade y, de dos copias iguales, se queda la de más calidad; la peor va a la "
                    "papelera de la biblioteca (restaurable). La colección solo se lee.")
    p_fus.add_argument("coleccion", type=Path, help="Colección a añadir (solo se lee)")
    p_fus.add_argument("--destino", type=Path, required=True,
                       help="Biblioteca a la que se añade (debe existir)")
    p_fus.add_argument("--simular", action="store_true",
                       help="Muestra qué haría sin tocar nada (el informe CSV va a la carpeta "
                            "temporal del sistema)")
    p_fus.add_argument("--umbral", type=_umbral_fusion, default=5,
                       help="Bits de diferencia (0-12, de 128) para considerar dos fotos la misma "
                            "(por defecto 5: copias recomprimidas o reducidas). Más = más agresivo")
    p_fus.add_argument("--margen-dias", type=_positivo, default=1,
                       help="Días antes y después con los que se compara cada foto o vídeo "
                            "(por defecto 1, por medianoche y zonas horarias; 0 = el mismo día)")
    p_fus.add_argument("--max-lado", dest="max_lado_fotos", type=_positivo, default=3200,
                       help="Las fotos más grandes se reducen al añadirlas, como al importar "
                            "(0 = copiarlas siempre tal cual; por defecto 3200)")
    p_fus.add_argument("--calidad", type=_calidad, default=88,
                       help="Calidad al reducir o convertir una foto (por defecto 88)")
    p_fus.add_argument("--hilos", type=_positivo, default=0,
                       help="Archivos en paralelo (por defecto: según los núcleos del equipo)")
    p_fus.add_argument("--sin-galeria", action="store_true",
                       help="No actualizar la galería de la biblioteca al terminar")

    p_gal = sub.add_parser("galeria", parents=[servir],
                           help="Generar (y servir) la galería web local")
    p_gal.add_argument("carpeta", type=Path, help="Biblioteca ya organizada")
    p_gal.add_argument("--regenerar", action="store_true",
                       help="Rehacer metadatos y miniaturas aunque no hayan cambiado")

    p_panel = sub.add_parser(
        "panel", help="Panel web local para elegir opciones, lanzar y ver el progreso",
        description="Abre en el navegador un panel para configurar y lanzar importaciones, "
                    "galerías y reorganizaciones, con su progreso en directo.")
    p_panel.add_argument("--puerto", type=int, default=8765,
                         help="Puerto del panel (por defecto 8765; si está ocupado, el siguiente)")
    p_panel.add_argument("--sin-navegador", action="store_true",
                         help="No abrir el navegador automáticamente")
    return parser


COMANDOS_IMPORTACION = ("fotos", "videos", "audio", "todo")


def destino_de(origen: Path, destino: Path = None) -> Path:
    """Biblioteca destino: la indicada o, por defecto, <origen>_organizados."""
    origen = origen.resolve()
    return (destino or origen.with_name(origen.name + "_organizados")).resolve()


def comprobar_argumentos(args):
    """Motivo por el que no se puede empezar (carpeta que no existe...), o None."""
    if args.comando == "reorganizar":
        if not args.biblioteca.resolve().is_dir():
            return f"La carpeta no existe: {args.biblioteca.resolve()}"
        if not (args.whatsapp or args.fechas_aproximadas):
            return "Indica qué reorganizar: --whatsapp y/o --fechas-aproximadas"
    elif args.comando == "galeria":
        if not args.carpeta.resolve().is_dir():
            return f"La carpeta no existe: {args.carpeta.resolve()}"
    elif args.comando == "fusionar":
        coleccion, destino = args.coleccion.resolve(), args.destino.resolve()
        if not coleccion.is_dir():
            return f"La colección no existe: {coleccion}"
        if not destino.is_dir():
            return f"La biblioteca no existe: {destino}"
        if coleccion == destino or coleccion in destino.parents or destino in coleccion.parents:
            return ("La colección y la biblioteca deben ser carpetas distintas y ninguna "
                    "dentro de la otra.")
    elif args.comando in COMANDOS_IMPORTACION:
        origen = args.origen.resolve()
        if not origen.is_dir():
            return f"La carpeta de origen no existe: {origen}"
        destino = destino_de(origen, args.destino)
        if origen == destino or origen in destino.parents:
            return "El destino no puede estar dentro del origen ni coincidir con él."
    return None


def validar_origen_destino(origen: Path, destino: Path, simular: bool):
    origen = origen.resolve()
    if not origen.is_dir():
        sys.exit(f"La carpeta de origen no existe: {origen}")
    destino = destino_de(origen, destino)
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


def _descarga_opcional(funcion, que: str):
    """Los datos descargables son opcionales: sin conexión, la galería se genera igual."""
    try:
        funcion()
    except OSError as exc:   # también urllib.error.URLError
        print(f"AVISO: no se han podido descargar {que} ({exc}); la galería se genera "
              "igualmente. Se reintentará en la próxima ejecución.")


def galeria(carpeta: Path, args, regenerar: bool = False):
    if not hay_pillow():
        sys.exit(MENSAJE_PILLOW)
    progreso("inicio", "galeria")
    if args.descargar_lugares or args.descargar_modelos_caras:
        progreso("avance", "galeria", paso="Descargando datos")
    if args.descargar_lugares:
        from lugares import descargar_lugares
        _descarga_opcional(descargar_lugares, "las ciudades")
    if args.descargar_modelos_caras:
        from caras import descargar_modelos
        _descarga_opcional(descargar_modelos, "los modelos de caras")
    from galeria import generar_galeria
    generada = generar_galeria(carpeta, regenerar, caras=args.caras)
    progreso("fin", "galeria")
    if generada and args.servir:
        from servidor import servir
        servir(carpeta, args.puerto, abrir_navegador=not args.sin_navegador)


def reorganizar_biblioteca(biblioteca: Path, simular: bool, **kwargs):
    from reorganizar import reorganizar
    progreso("inicio", "reorganizar")
    progreso("fin", "reorganizar", resumen=reorganizar(biblioteca, simular, **kwargs))


def main(argv=None):
    configurar_consola()
    args = construir_parser().parse_args(argv)

    if args.comando == "panel":
        from panel import servir_panel
        servir_panel(args.puerto, abrir_navegador=not args.sin_navegador)
        return

    error = comprobar_argumentos(args)
    if error:
        sys.exit(error)

    if args.comando == "reorganizar":
        reorganizar_biblioteca(args.biblioteca.resolve(), args.simular, whatsapp=args.whatsapp,
                               fechas=args.fechas_aproximadas,
                               pegatinas_aparte=args.pegatinas_aparte)
        return

    if args.comando == "fusionar":
        if not hay_pillow():
            sys.exit(MENSAJE_PILLOW)
        from fusionar import OpcionesFusion, fusionar
        fusionar(args.coleccion.resolve(), args.destino.resolve(), args.simular, OpcionesFusion(
            umbral=args.umbral, margen_dias=args.margen_dias, max_lado=args.max_lado_fotos,
            calidad=args.calidad, hilos=args.hilos, galeria=not args.sin_galeria))
        return

    if args.comando == "galeria":
        galeria(args.carpeta.resolve(), args, args.regenerar)
        return

    origen, destino = validar_origen_destino(args.origen, args.destino, args.simular)
    print(f"Origen  : {origen}\nDestino : {destino}")

    if args.comando in ("fotos", "todo"):
        if not hay_pillow():
            sys.exit(MENSAJE_PILLOW)
        from fotos import procesar_fotos
        progreso("inicio", "fotos")
        progreso("fin", "fotos",
                 resumen=procesar_fotos(origen, destino, args.simular, opciones_fotos(args)))

    if args.comando in ("videos", "todo"):
        if hay_ffmpeg():
            from videos import procesar_videos
            progreso("inicio", "videos")
            progreso("fin", "videos", resumen=procesar_videos(
                origen, destino, args.simular, opciones_videos(args)))
        elif args.comando == "videos":
            sys.exit(MENSAJE_FFMPEG)
        else:
            print("\nAVISO: se omiten los vídeos porque FFmpeg no está instalado "
                  "(winget install Gyan.FFmpeg).")
            progreso("omitida", "videos", motivo="FFmpeg no está instalado")

    if args.comando == "audio" or (args.comando == "todo" and not args.sin_audio):
        from audio import procesar_audio
        progreso("inicio", "audio")
        progreso("fin", "audio", resumen=procesar_audio(origen, destino, args.simular))

    if args.renombrar_aproximadas and (destino / ".exportador").exists():
        reorganizar_biblioteca(destino, args.simular, fechas=True)

    if args.comando == "todo" and not args.simular and not args.sin_galeria:
        print()
        galeria(destino, args)


if __name__ == "__main__":
    if hasattr(signal, "SIGBREAK"):
        # Ctrl+Break (y el botón «Detener» del panel) se trata igual que Ctrl+C: el
        # programa se detiene en orden, sin dejar archivos a medias ni FFmpeg en marcha
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
