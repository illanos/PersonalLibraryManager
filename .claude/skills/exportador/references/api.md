# Usar el paquete desde Python

Para scripts propios, automatizar o investigar. Cada comando de la CLI es una función con
sus opciones en una *dataclass*. Las funciones imprimen su progreso en la consola, igual que
la CLI, y respetan las mismas garantías (origen de solo lectura, `simular`, incremental).

Importación: con el paquete instalado, `import exportador`; desde el proyecto sin instalar,
añadir `<raíz>/src` a `sys.path` (o `PYTHONPATH=src`).

## Importar

```python
from pathlib import Path
from exportador.fotos import OpcionesFotos, procesar_fotos
from exportador.videos import OpcionesVideos, procesar_videos
from exportador.audio import procesar_audio

origen, biblioteca = Path(r"E:\DCIM"), Path(r"D:\Biblioteca")
resumen = procesar_fotos(origen, biblioteca, simular=True,
                         opciones=OpcionesFotos(formato="webp", omitir_parecidas=True))
print(resumen["procesados"], resumen["ya_importados"], resumen["bytes_despues"])
```

`OpcionesFotos`: `max_lado=3200` (0 = no reducir), `calidad=88`, `formato="jpeg"|"webp"`,
`conservar_originales=False`, `hilos=0` (automático), `omitir_parecidas=False`,
`pegatinas_aparte=False`, `externos=None` (metadatos externos, p. ej. un `IndiceTakeout`).

`OpcionesVideos`: `codec="h264"|"h265"|"vp9"`, `max_lado=1920` (0 = mantener),
`crf=None` (el del perfil: 23/28/32), `preset="medium"`, `conservar_originales=False`,
`hilos=1` (vídeos a la vez), `hw="no"|"auto"|"nvenc"|"qsv"|"amf"`, `externos=None`.
Necesita FFmpeg y ffprobe en el PATH.

`procesar_audio(origen, biblioteca, simular)` no tiene opciones (copia sin recomprimir).

Resumen devuelto (`media_utils.nuevas_estadisticas`): `procesados`, `sin_cambios`,
`ya_importados`, `duplicados`, `omitidos`, `errores`, `bytes_antes`, `bytes_despues`,
`parecidas`, `parecidas_omitidas`, `danados`, `editadas`, `con_json`, `sin_json`.

La CLI crea la biblioteca si no existe (`destino.mkdir`) antes de llamar a estas funciones;
haz lo mismo fuera de simulación.

## Google Takeout

```python
from exportador.takeout import IndiceTakeout
indice = IndiceTakeout(Path(r"G:\Takeout\Google Fotos"))
print(indice.resumen())
opciones = OpcionesFotos(); opciones.externos = indice
procesar_fotos(indice.raiz, Path(r"D:\Google"), simular=True, opciones=opciones)
# Para vídeos, OpcionesVideos(externos=indice): así también importa los clips .MP
```

## Galería y servidor

```python
from exportador.galeria import generar_galeria
from exportador.servidor import servir, crear_servidor
generar_galeria(Path(r"D:\Biblioteca"), regenerar=False, caras=False)   # -> bool (generada)
servir(Path(r"D:\Biblioteca"), puerto=8080, abrir_navegador=True)       # bloquea hasta Ctrl+C
srv = crear_servidor(Path(r"D:\Biblioteca"), 8080)  # para controlarlo uno mismo (serve_forever)
```

Descargas únicas: `exportador.lugares.descargar_lugares()` y
`exportador.caras.descargar_modelos()` (a la carpeta de datos, `descargas.CARPETA_DATOS`).

## Fusionar

```python
from exportador.fusionar import OpcionesFusion, fusionar, EspacioInsuficiente
try:
    r = fusionar(Path(r"D:\Google"), Path(r"D:\Biblioteca"), simular=True,
                 opciones=OpcionesFusion(umbral=5, margen_dias=1))
except EspacioInsuficiente as exc:
    print(exc)
```

`OpcionesFusion`: `umbral=5` (0-12), `margen_dias=1`, `max_lado=3200`, `calidad=88`,
`max_lado_video=1920`, `metadatos=True`, `hilos=0`, `galeria=True`.
Resumen: `fotos`, `videos`, `anadidas`, `sustituidas`, `ya_estaban`, `repetidas`,
`quitadas`, `ya_fusionadas`, `ya_comparadas`, `parecidas`, `convertidas`, `metadatos`,
`metadatos_sin_poder`, `errores`, `omitidos`, `bytes_anadidos`, `bytes_papelera`.

## Reorganizar

```python
from exportador.reorganizar import reorganizar
reorganizar(Path(r"D:\Biblioteca"), simular=True, whatsapp=True, fechas=True,
            pegatinas_aparte=False)   # -> {"movidos": n, "errores": n, ...}
```

## Piezas sueltas útiles para investigar

```python
from exportador.metadatos import leer_metadatos      # fecha, fuente, ancho, alto, gps, camara,
leer_metadatos(Path("foto.jpg"))                     # etiquetas, personas, titulo, valoracion…
from exportador.similares import dhash, distancia    # hash perceptual de 128 bits
distancia(dhash(Path("a.jpg")), dhash(Path("b.jpg")))  # bits distintos: ≤5 copia, ≤12 parecida
from exportador.danados import diagnosticar          # (problema, detalle) o None
diagnosticar(Path("x.jpg"), Path("x.jpg").stat().st_size, imagen=True)
from exportador.clasificacion import categoria, es_whatsapp  # 'pegatina'|'whatsapp'|'captura'|''
from exportador.media_utils import fecha_desde_nombre        # fecha deducida del nombre o None
from exportador.videos import sondear                        # ffprobe de un vídeo (dict) o None
from exportador.catalogo import Catalogo, ruta_catalogo, info_por_destino
info_por_destino(Path(r"D:\Biblioteca"))   # {destino: {original, origen, fuente_fecha}}
```

La línea de comandos entera también se puede llamar: `from exportador.cli import main;
main(["fotos", r"E:\DCIM", "--destino", r"D:\Biblioteca", "--simular"])`.
