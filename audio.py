"""Notas de voz y audio: organización por fecha, copiados tal cual (sin recomprimir).

    WhatsApp (PTT-AAAAMMDD-WA0001.opus, AUD-...)  ->  WhatsApp/Audio/Año/Mes/
    Otros audios                                  ->  Audio/Año/Mes/

Fecha: metadatos (con ffprobe, si está instalado) > nombre del archivo > fecha de
modificación; si sale del nombre sin hora se aplica la misma regla que a las fotos
(hora del archivo si es del mismo día, o un nombre como 20250114_WA0003).
FFmpeg es opcional: sin él solo se pierde la fecha de los metadatos y la duración.
"""

import os
import shutil
from pathlib import Path

from catalogo import Catalogo, Informe
from clasificacion import carpeta_destino, categoria
from danados import RegistroDanados, diagnosticar
from media_utils import (
    copiar_atomico, fecha_desde_nombre, fecha_mtime, fecha_y_nombre, hash_archivo, imprimir,
    imprimir_resumen, listar_archivos, nombre_libre, nuevas_estadisticas,
)

EXTENSIONES_AUDIO = {".opus", ".mp3", ".m4a", ".aac", ".ogg", ".wav"}


def hay_ffprobe() -> bool:
    return bool(shutil.which("ffprobe"))


def fecha_audio(ruta: Path, usar_ffprobe: bool):
    """(fecha, fuente): metadatos > nombre > fecha de modificación."""
    if usar_ffprobe:
        from videos import sondear
        info = sondear(ruta) or {}
        if info.get("fecha"):
            return info["fecha"], "metadatos"
    fecha = fecha_desde_nombre(ruta.stem)
    if fecha:
        return fecha, "nombre"
    return fecha_mtime(ruta), "archivo"


def procesar_audio(origen: Path, destino: Path, simular: bool) -> dict:
    """Copia los audios a la biblioteca por fecha. El origen solo se lee."""
    stats = nuevas_estadisticas()
    archivos = listar_archivos(origen, EXTENSIONES_AUDIO)
    if not archivos:
        print(f"No se encontraron audios en {origen}")
        return stats
    usar_ffprobe = hay_ffprobe()
    print(f"\n{'SIMULACIÓN' if simular else 'PROCESANDO'} — {len(archivos)} audio(s) — "
          "se copian sin recomprimir"
          + ("" if usar_ffprobe else " (sin ffprobe: fecha del nombre o del archivo)") + "\n")

    reservados, vistos = set(), {}
    danados = RegistroDanados(destino, origen, "audio", simular)
    with Catalogo(destino, simular) as catalogo, Informe(destino, "audio", simular) as informe:
        for n, ruta in enumerate(archivos, 1):
            rel = ruta.relative_to(origen)
            prefijo = f"  [{n}/{len(archivos)}]"
            try:
                st = ruta.stat()
                if catalogo.buscar_por_origen(ruta, st) is not None:
                    stats["ya_importados"] += 1
                    continue
                descarte = catalogo.buscar_descarte(ruta, st)
                diagnostico = None
                conocido = descarte is not None and descarte["motivo"] == "danado"
                if conocido:
                    diagnostico = (descarte["problema"], descarte["detalle"])
                else:
                    diagnostico = diagnosticar(ruta, st.st_size)
                if diagnostico:
                    imprimir(f"{prefijo} DAÑADO     {rel}  ({diagnostico[0]}: {diagnostico[1]})")
                    danados.anotar(ruta, *diagnostico, st.st_size, conocido)
                    if not conocido:
                        informe.anotar("DANADO", ruta, detalle=": ".join(diagnostico))
                        catalogo.descartar(ruta, st.st_size, st.st_mtime_ns, "audio", "danado",
                                           *diagnostico)
                    stats["danados"] += 1
                    continue
                digest = hash_archivo(ruta)
                if catalogo.buscar_por_hash(digest) is not None:
                    stats["ya_importados"] += 1
                    continue
                if digest in vistos:
                    imprimir(f"{prefijo} DUPLICADO  {rel}  (igual que {vistos[digest]})")
                    informe.anotar("DUPLICADO", ruta, detalle=f"igual que {vistos[digest]}")
                    stats["duplicados"] += 1
                    continue
                vistos[digest] = rel

                fecha, fuente, base = fecha_y_nombre(ruta, *fecha_audio(ruta, usar_ffprobe))
                cat = categoria(rel)
                carpeta_rel = carpeta_destino(fecha, cat if cat == "whatsapp" else "", "audio")
                final = nombre_libre(destino / carpeta_rel, base, ruta.suffix.lower(), reservados)
                if simular:
                    imprimir(f"{prefijo} {rel}  ->  {carpeta_rel}/{final.name}  [fecha: {fuente}]")
                    stats["procesados"] += 1
                    continue

                final.parent.mkdir(parents=True, exist_ok=True)
                copiar_atomico(ruta, final)
                marca = fecha.timestamp()
                os.utime(final, (marca, marca))
                destino_rel = final.relative_to(destino).as_posix()
                catalogo.registrar(
                    hash=digest, tipo="audio", origen=str(ruta), tamano=st.st_size,
                    mtime_ns=st.st_mtime_ns, destino=destino_rel, original=None,
                    fecha=fecha.isoformat(), fuente_fecha=fuente,
                    bytes_antes=st.st_size, bytes_despues=st.st_size)
                informe.anotar("COPIADO", ruta, destino_rel, fecha, fuente, st.st_size, st.st_size)
                imprimir(f"{prefijo} OK  {rel}  ->  {destino_rel}")
                stats["procesados"] += 1
                stats["sin_cambios"] += 1
                stats["bytes_antes"] += st.st_size
                stats["bytes_despues"] += st.st_size
            except KeyboardInterrupt:
                print("\nInterrumpido. Lo ya copiado queda registrado; vuelve a ejecutar.")
                raise
            except Exception as exc:
                imprimir(f"{prefijo} ERROR en {rel}: {exc}")
                informe.anotar("ERROR", ruta, detalle=str(exc))
                stats["errores"] += 1

    imprimir_resumen(stats, "audios", simular, None, informe.ruta if informe.filas else None)
    danados.cerrar()
    return stats
