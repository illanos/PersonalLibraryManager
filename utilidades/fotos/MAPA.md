# Mapa de Fotos

<!-- Generado por herramientas/mapas.py. No editar a mano: `python herramientas/mapas.py` -->

Paquete `exportador` (`src/exportador/`). Las rutas son relativas a `utilidades/fotos/`. Para el porqué de las cosas, `doc/ARQUITECTURA.md`; para cómo trabajar aquí, `CLAUDE.md`.

## Módulos

| Módulo | Qué hace | Usa | Lo usan | Pruebas (`tests/`) |
|---|---|---|---|---|
| `audio.py` | Notas de voz y audio: organización por fecha, copiados tal cual (sin recomprimir) | `catalogo`, `clasificacion`, `danados`, `media_utils`, `videos` | `cli` | `test_audio` |
| `caras.py` | Caras: detección local y agrupación de caras parecidas para nombrarlas en la galería | `descargas`, `media_utils` | `cli`, `galeria`, `reorganizar`, `servidor` | `test_lugares_caras` |
| `catalogo.py` | Catálogo persistente de la biblioteca (SQLite) e informe CSV de cada ejecución | `media_utils` | `audio`, `fotos`, `fusionar`, `galeria`, `limpieza`, `reorganizar`, `videos` | `test_fechas`, `test_fusionar`, `test_galeria`, `test_limpieza`, `test_similares`, `test_whatsapp` |
| `clasificacion.py` | Clasificación del contenido: WhatsApp, pegatinas, capturas y fotos en movimiento | `media_utils` | `audio`, `fotos`, `fusionar`, `galeria`, `limpieza`, `reorganizar`, `videos` | `test_galeria`, `test_whatsapp` |
| `cli.py` | Línea de comandos del Exportador: organiza, renombra y optimiza fotos, vídeos y audio, y crea una galería web local | `audio`, `caras`, `fotos`, `fusionar`, `galeria`, `lugares`, `media_utils`, `panel`, `reorganizar`, `servidor`, `takeout`, `videos` | `__main__`, `panel` | `test_audio`, `test_fechas`, `test_fusionar`, `test_lugares_caras`, `test_main`, `test_panel`, `test_skill`, `test_takeout`, `test_videos_hw`, `test_whatsapp` |
| `danados.py` | Archivos dañados: vacíos, sin cabecera válida o truncados | `media_utils` | `audio`, `fotos`, `videos` | `test_danados` |
| `descargas.py` | Descargas únicas de datos opcionales (ciudades, modelos de caras) | — | `caras`, `lugares`, `panel` | — |
| `fotos.py` | Tratamiento de fotos: fecha de captura, organización Año/Mes y optimización | `catalogo`, `clasificacion`, `danados`, `media_utils`, `metadatos`, `similares` | `cli`, `fusionar`, `limpieza` | `test_danados`, `test_fechas`, `test_fotos`, `test_fusion_metadatos`, `test_fusionar`, `test_galeria`, `test_limpieza`, `test_lugares_caras`, `test_panel`, `test_similares`, `test_takeout`, `test_whatsapp` |
| `fusion_metadatos.py` | Fusionar los metadatos de las copias iguales de una foto o un vídeo (ver fusionar.py) | `media_utils`, `metadatos`, `videos` | `fusionar` | `test_fusion_metadatos` |
| `fusionar.py` | Fusionar colecciones: añadir a una biblioteca las fotos y vídeos de otra colección sin repetir lo que ya tiene, quedándose siempre con la copia de más calidad | `catalogo`, `clasificacion`, `fotos`, `fusion_metadatos`, `galeria`, `limpieza`, `media_utils`, `metadatos`, `similares`, `videos` | `cli` | `test_fusion_metadatos`, `test_fusionar` |
| `galeria.py` | Galería web local: índice de la biblioteca, miniaturas y página HTML | `caras`, `catalogo`, `clasificacion`, `lugares`, `media_utils`, `metadatos`, `similares`, `videos` | `cli`, `fusionar`, `limpieza`, `reorganizar` | `test_audio`, `test_fusion_metadatos`, `test_fusionar`, `test_galeria`, `test_limpieza`, `test_lugares_caras`, `test_similares`, `test_whatsapp` |
| `limpieza.py` | Limpiar fotos repetidas: grupos, mejor copia, papelera y decisiones guardadas | `catalogo`, `clasificacion`, `fotos`, `galeria`, `media_utils`, `similares`, `videos` | `fusionar`, `servidor` | `test_fusionar`, `test_limpieza` |
| `lugares.py` | Lugares a partir del GPS, sin conexión (geocodificación inversa local) | `descargas` | `cli`, `galeria` | `test_lugares_caras` |
| `media_utils.py` | Utilidades compartidas entre fotos, vídeos y galería | — | `audio`, `caras`, `catalogo`, `clasificacion`, `cli`, `danados`, `fotos`, `fusion_metadatos`, `fusionar`, `galeria`, `limpieza`, `metadatos`, `panel`, `reorganizar`, `servidor`, `takeout`, `videos` | `test_fechas`, `test_fusion_metadatos`, `test_media_utils`, `test_panel`, `test_takeout` |
| `metadatos.py` | Metadatos de fotos: lectura (para buscar y filtrar) y conservación al exportar | `media_utils` | `fotos`, `fusion_metadatos`, `fusionar`, `galeria`, `takeout` | `test_fotos`, `test_fusion_metadatos`, `test_takeout` |
| `panel.py` | Panel web local: configurar las opciones, lanzar y seguir el progreso | `cli`, `descargas`, `media_utils`, `servidor` | `cli` | `test_panel` |
| `reorganizar.py` | Reorganiza una biblioteca ya importada, solo cuando se pide explícitamente | `caras`, `catalogo`, `clasificacion`, `galeria`, `media_utils` | `cli` | `test_whatsapp` |
| `servidor.py` | Servidor HTTP local de la galería | `caras`, `limpieza`, `media_utils` | `cli`, `panel` | `test_galeria`, `test_limpieza`, `test_lugares_caras` |
| `similares.py` | Fotos casi idénticas: hash perceptual (dHash) y agrupación de parecidas | — | `fotos`, `fusionar`, `galeria`, `limpieza` | `test_fusionar`, `test_similares` |
| `takeout.py` | Google Fotos (Google Takeout): empareja cada foto y vídeo con su JSON de metadatos | `media_utils`, `metadatos` | `cli` | `test_takeout` |
| `videos.py` | Tratamiento de vídeos: fecha de grabación, organización Año/Mes y recodificación | `catalogo`, `clasificacion`, `danados`, `media_utils` | `audio`, `cli`, `fusion_metadatos`, `fusionar`, `galeria`, `limpieza` | `test_danados`, `test_fechas`, `test_fusionar`, `test_takeout`, `test_videos`, `test_videos_hw` |

Otros archivos del paquete: `plantillas/galeria.html`, `plantillas/limpiar.html`, `plantillas/panel.html`.

## Qué hay en cada módulo

Solo lo público (sin `_` delante), en el orden en que aparece.

### `audio.py`

- `hay_ffprobe()`
- `fecha_audio()` — (fecha, fuente): metadatos > nombre > fecha de modificación
- `procesar_audio()` — Copia los audios a la biblioteca por fecha

### `caras.py`

- `disponible()`
- `descargar_modelos()`
- `ruta_nombres()`
- `leer_nombres()`
- `class Motor` — Detecta las caras de una foto: [(x, y, w, h, vector)], caja en fracciones (0-1)
  - `.caras`
- `class MotorOpenCV`
  - `.caras`
- `class Caras` — Caché de caras de una galería y agrupación incremental
  - `.cerrar`, `.pendientes`, `.analizar`
- `aplicar_caras()` — Paso de la galería: devuelve (fotos analizadas ahora, aviso o '')
- `renombrar_en_cache()` — Tras `reorganizar`: las fotos movidas conservan sus caras ya calculadas

### `catalogo.py`

- `ruta_catalogo()`
- `class Catalogo` — Acceso al catálogo, seguro entre hilos
  - `.buscar_por_origen`, `.buscar_por_hash`, `.fotos_con_phash`, `.buscar_descarte`, `.hash_descartado`, `.filas`, `.descartar`, `.olvidar_descarte`, `.cambiar_destino`, `.registrar`, `.cerrar`
- `info_por_destino()` — {destino_relativo: {original, origen, fuente_fecha}} según el catálogo (vacío si no hay)
- `class Informe` — CSV con una fila por archivo tratado, en <biblioteca>/.exportador/informes/
  - `.anotar`, `.cerrar`

### `clasificacion.py`

- `es_whatsapp()` — Por el nombre (IMG-AAAAMMDD-WA0001) o por estar en una carpeta de WhatsApp
- `es_pegatina()` — STK-*.webp, o webp pequeño (≤ 512 px) dentro de WhatsApp / de una carpeta de pegatinas
- `es_captura()`
- `es_foto_en_movimiento()` — Vídeo de menos de SEGUNDOS_MOVIMIENTO
- `categoria()` — 'pegatina' \| 'whatsapp' \| 'captura' \| '' (contenido normal)
- `carpeta_destino()` — Carpeta relativa dentro de la biblioteca (con '/')
- `en_carpeta_whatsapp()` — ¿Está ya dentro de WhatsApp/ en la biblioteca? (`rel` relativo, con '/')
- `ambito()` — 'whatsapp' si el elemento de la galería es de WhatsApp (por su carpeta en la biblioteca o, en bibliotecas antiguas, por el archivo de origen); si no, ''

### `cli.py`

- `construir_parser()`
- `destino_de()` — Biblioteca destino: la indicada o, por defecto, <origen>_organizados
- `comprobar_argumentos()` — Motivo por el que no se puede empezar (carpeta que no existe...), o None
- `validar_origen_destino()`
- `hay_pillow()`
- `hay_ffmpeg()`
- `opciones_fotos()`
- `opciones_videos()`
- `galeria()`
- `reorganizar_biblioteca()`
- `main()`
- `ejecutar()` — Punto de entrada de `python -m exportador` y del comando `exportador`

### `danados.py`

- `firma_valida()`
- `formato_imagen()` — Extensión que corresponde al contenido de una imagen ('.png'...), o None
- `diagnosticar()` — (problema, detalle) si el archivo está dañado; None si parece sano
- `problema_de_excepcion()` — Clasifica un error de lectura/decodificación de Pillow o FFmpeg, o None
- `class RegistroDanados` — Acumula los dañados de una ejecución; CSV aparte y resumen por carpeta al final
  - `.anotar`, `.cerrar`
- `imprimir_resumen_danados()`

### `descargas.py`

- `carpeta_datos()` — Dónde se guardan las descargas y las preferencias del panel
- `descargar()` — Descarga `url` en `destino` de forma atómica (primero a .part)

### `fotos.py`

- `class OpcionesFotos`
- `obtener_fecha()` — (fecha, fuente): EXIF > nombre del archivo > fecha de modificación
- `calidad_jpeg()` — Calidad (1-100) con la que se guardó un JPEG, estimada por su tabla de luminancia como hace libjpeg al escalarla; None si no es JPEG
- `guardar_optimizada()` — Escribe en `destino` la versión reducida y recomprimida (de forma atómica)
- `procesar_fotos()`

### `fusion_metadatos.py`

- `class Datos` — Lo que dicen los metadatos de una copia (y, en la que se queda, lo que va ganando)
  - `.describir`
- `leer()` — Metadatos de una copia
- `gana_la_fecha()` — ¿La fecha de `d` sabe más que la de `k`? Solo si `k` no la trae en sus metadatos
- `aportar()` — Lo que la copia `d` sabe y la que se queda (`k`) no: lo añade a `extra` (lo que se escribirá en `k`) y lo apunta en `k`
- `se_puede_completar()` — ¿Se le pueden añadir metadatos sin recomprimir? (O se convierte de todos modos.)
- `argumentos_video()` — -metadata de FFmpeg (`aportar` solo pone fecha y ubicación si le faltan)
- `escribir()` — `origen` con los metadatos de `extra` en `destino` (puede ser el mismo archivo: se escribe aparte y se sustituye de una vez, con la misma fecha de…

### `fusionar.py`

- `class OpcionesFusion`
- `class Elemento` — Una foto o un vídeo de la biblioteca ('b'), de su papelera ('p') o de la colección ('c')
  - `.dia`, `.proporcion`
- `pixeles()` — Píxeles con los que quedaría en la biblioteca: lo que pasa del límite de la exportación y se reduce al añadirlo cuenta ya reducido
- `mismo_original()` — ¿Se hicieron las dos del mismo archivo? (El MD5 del original en los dos catálogos.) Con el mismo nombre y hora no basta: una puede salir de una versión…
- `es_el_original()` — ¿Es el original tal cual, sin recomprimir? Pesa lo mismo que el original según su catálogo y lo confirma el MD5 (solo se calcula entonces)
- `comparar()` — (>0 si `a` es mejor que `b`, <0 si es peor, 0 si equivalen; motivo legible)
- `hash_fotograma()` — dHash del fotograma del vídeo en `instante` segundos (girado como se ve), o None
- `distancia_video()` — Mayor diferencia (bits) entre los fotogramas comparables, o None si no se puede saber (vídeos casi negros, FFmpeg falla...): ante la duda, no son iguales
- `class Indice` — Elementos por tipo y día (los de la biblioteca y lo que ya va a entrar)
  - `.anadir`, `.quitar`, `.candidatos`
- `normalizar_nombre()` — Nombre del original para compararlo: en minúsculas y sin el «(1)» que añade Takeout a los archivos con el mismo nombre (DSCN0169(1).JPG es DSCN0169.JPG)
- `hash_de_archivo()` — dHash calculado del propio archivo (girado `giro` grados), con caché
- `buscar_pareja()` — (copia igual a `c` en el índice o None, cómo se sabe)
- `planificar()` — Decide qué hacer con cada elemento de la colección (rellena `accion`, `pareja`...)
- `leer_elemento()` — Elemento de un archivo, con lo que ya saben su catálogo (`fila`) y su galería (`previo`, si el archivo no ha cambiado); solo lee el archivo para lo que falte
- `ruta_de()`
- `extension_final()`
- `copias_iguales()` — [(la que se queda, [las otras copias iguales])], para fusionar sus metadatos
- `class EspacioInsuficiente` — Lo que hay que añadir no cabe en el disco de la biblioteca: no se copia nada
- `comprobar_espacio()` — Anota en `stats` el espacio necesario y el libre; devuelve el problema o ""
- `nuevas_estadisticas()`
- `fusionar()` — Añade a `biblioteca` lo de `coleccion` que no tiene (ver el docstring del módulo)

### `galeria.py`

- `etiquetas_automaticas()`
- `construir_indice()` — Lista de elementos (más recientes primero) y estadísticas de la regeneración
- `marcar_parecidas()` — Pone `parecidas` (número de grupo) a las fotos casi idénticas
- `actualizar_parecidas()` — Como `marcar_parecidas`, pero rehace solo los grupos afectados: los de número en `numeros_quitados` (de fotos que se han quitado) y los que tocan las fotos…
- `generar_galeria()`

### `limpieza.py`

- `class RutaNoValida` — Ruta que no es una foto de la biblioteca (fuera de ella, interna, origen...)
- `class ErrorLimpieza` — Petición coherente pero imposible (p. ej. quitar todas las copias de un grupo)
- `id_grupo()`
- `elegir_mejor()` — (src de la mejor copia, motivo legible) de un grupo de fotos (dicts)
- `class Limpieza` — Estado de la limpieza de una biblioteca
  - `.validar`, `.grupos`, `.decidir`, `.no_repetidas`, `.deshacer`, `.mover_a_papelera`, `.contenido_papelera`, `.restaurar`, `.vaciar`

### `lugares.py`

- `preparar()` — Filas (nombre, lat, lon, región, país) a partir de los archivos de GeoNames
- `descargar_lugares()` — Descarga GeoNames una vez y deja `datos/lugares.tsv` (si ya está, no hace nada)
- `guardar()`
- `class Geocodificador`
  - `.buscar`
- `cargar()` — Geocodificador listo, o None si no se ha descargado el archivo de lugares
- `asignar_lugares()` — Pone 'lugar' y 'pais' a los elementos con GPS que aún no lo tengan

### `media_utils.py`

- `configurar_consola()` — Evita que un carácter no representable en la consola de Windows aborte el programa
- `imprimir()` — print() seguro entre hilos
- `progreso()` — Evento de progreso para el panel: inicio/fin de una fase, avance (hecho/total)
- `formato_bytes()`
- `hash_archivo()` — MD5 del contenido (detección de duplicados, no seguridad)
- `recorrer_archivos()` — `os.DirEntry` de los archivos con esas extensiones, sin entrar en carpetas internas ni ocultas (ni en enlaces a carpetas), en cualquier orden
- `listar_archivos()` — Rutas ordenadas de `recorrer_archivos`
- `nombre_libre()` — Ruta no ocupada: base.ext, base_01.ext, base_02.ext
- `ruta_temporal()` — Archivo temporal junto al destino; se renombra al terminar (escritura atómica)
- `copiar_atomico()` — Copia (con metadatos) sin dejar nunca un archivo a medias en `destino`
- `subcarpeta_fecha()` — Subcarpeta relativa Año/Mes, ej.: '2024/05-Mayo'
- `fecha_plausible()`
- `fecha_mtime()`
- `fecha_desde_nombre()` — Fecha deducida del nombre del archivo (móviles, WhatsApp, capturas...) o None
- `nombre_tiene_hora()` — ¿El nombre trae fecha *y hora* (IMG_20240512_102030) y no solo fecha (IMG-20240512-WA0001)?
- `fecha_aproximada()` — Fecha deducida de un nombre *sin hora* (WhatsApp): (fecha, fuente, base_del_nombre)
- `fecha_y_nombre()` — (fecha, fuente, base) para un archivo nuevo
- `parsear_fecha_iso()` — Fecha ISO 8601 de metadatos de vídeo -> datetime local sin zona, o None
- `class MetadatosExtra` — Metadatos que vienen aparte del archivo (p. ej. el JSON de Google Fotos)
  - `.aporta_xmp`, `.combinar`
- `elegir_fecha()` — (fecha, fuente) combinando la del archivo con la de unos metadatos externos
- `metadatos_para_escribir()` — `extra` con la fecha que debe grabarse en el archivo exportado: la elegida por `elegir_fecha`, salvo que salga del nombre sin hora o de la fecha del archivo…
- `resumen_extra()` — ' [añade: fecha, GPS, 2 álbum(es)…]': lo que se graba en el archivo exportado (para la consola y el informe). `copia`: se copia tal cual (GIF animado,…
- `contar_extra()`
- `nuevas_estadisticas()`
- `imprimir_resumen()`

### `metadatos.py`

- `fecha_exif()` — DateTimeOriginal > DateTimeDigitized > DateTime
- `gps_exif()` — [lat, lon] en grados decimales, o None
- `camara_exif()`
- `exposicion_exif()` — Ej.: '1/120 s · f/1.8 · ISO 100 · 26 mm'
- `xmp_de()` — Paquete XMP de la imagen (bytes) o None
- `leer_xmp()`
- `leer_iptc()`
- `leer_metadatos()` — Metadatos de una foto
- `parametros_guardado()` — Argumentos para `im.save()` que trasladan los metadatos de `original`
- `completar_exif()` — Añade al EXIF la fecha y el GPS de `extra` si la foto no los trae, y las etiquetas sueltas de `extra.exif` que no tenga (el GPS, entero y solo si no tiene)
- `completar_xmp()` — Paquete XMP con los álbumes, personas, descripción y favorita de `extra` añadidos
- `jpeg_con_extra()` — El mismo JPEG, sin recomprimir, con el EXIF y el XMP completados con `extra`

### `panel.py`

- `class ErrorPanel` — Error que se muestra tal cual al usuario
- `calcular_esquema()` — {comando: {titulo, ayuda, simular, opciones: [...]}} sacado del parser de cli.py
- `construir_argv()` — Argumentos de cli.py para `comando` con los valores del formulario
- `validar()` — Pasa `argv` por el parser real
- `linea_de_comandos()`
- `carpeta_resultado()` — Biblioteca sobre la que trabaja (o trabajará) la ejecución
- `fases_previstas()` — Fases en el orden en que las ejecuta cli.py
- `comprobar()` — Lo que el formulario necesita saber antes de lanzar: errores, comando y destino
- `class Trabajo` — Una ejecución de cli.py y todo lo que se sabe de su progreso
  - `.lanzar`, `.detener`, `.terminar`, `.procesar_linea`, `.estado_json`, `.registro_texto`, `.para_historial`
- `class Panel` — Ejecución en curso, historial, preferencias y servidores de galería abiertos
  - `.ejecutar`, `.detener`, `.cerrar`, `.abrir_galeria`, `.elegir_carpeta`, `.abrir_carpeta`
- `class ManejadorPanel`
- `crear_panel()` — (servidor, panel) ligado a 127.0.0.1 en el primer puerto libre desde `puerto`
- `servir_panel()`

### `reorganizar.py`

- `plan()` — Nueva ruta relativa para una fila del catálogo, o None si se queda donde está
- `reorganizar()`

### `servidor.py`

- `class SoloLocal` — Comprobaciones comunes a los servidores locales (galería y panel)
- `class ManejadorGaleria`
- `class ServidorLocal`
- `ligar_local()` — Servidor ligado a 127.0.0.1 en el primer puerto libre desde `puerto`
- `crear_servidor()` — Servidor de la galería de `carpeta` en el primer puerto libre desde `puerto`
- `servir()`

### `similares.py`

- `dhash_imagen()` — dHash de 128 bits (hex de 32 caracteres) de una imagen ya abierta
- `dhash()` — dHash de un archivo de imagen (con la rotación EXIF aplicada)
- `distancia()`
- `con_detalle()`
- `indice_bandas()` — {(banda, trozo): [claves]} de {clave: hash como entero}
- `candidatos()` — Claves de `indice_bandas` que pueden estar a `umbral` bits o menos de `valor`
- `agrupar()` — Grupos (listas de claves, con 2 o más) de elementos parecidos entre sí
- `es_copia()` — ¿Es `h` una copia recomprimida de la mejor (y no otra toma de una ráfaga)?
- `calidad()` — Clave para elegir la mejor copia: más píxeles, luego con EXIF, luego más bytes

### `takeout.py`

- `nombre_album()` — Nombre del álbum para usarlo como etiqueta, o None si no aporta nada
- `bases_json()` — [(archivo cuyo JSON se busca, contador)] de más a menos probable
- `nombres_json()` — Nombres posibles del JSON de `nombre`, de más a menos probable
- `original_de_editada()` — 'foto-editada.jpg' -> 'foto' (nombre sin extensión del original); si no, None
- `class IndiceTakeout` — Metadatos de los JSON de un Takeout de Google Fotos, por archivo (ver el módulo)
  - `.omitir`, `.json_de`, `.metadatos`, `.resumen`

### `videos.py`

- `class OpcionesVideos`
- `sondear()` — Metadatos vía ffprobe (fecha, dimensiones de visualización, duración...) o None
- `fecha_nombre_camara()` — Fecha local *con hora* del nombre que pone la cámara (VID_20160812_203028), o None
- `fecha_video()` — (fecha, fuente): metadatos > nombre del archivo > fecha de modificación
- `obtener_fecha()`
- `dimensiones_objetivo()` — Dimensiones finales previstas (pares) manteniendo la proporción
- `filtro_escala()` — Filtro de escalado que FFmpeg evalúa sobre la imagen YA girada
- `codificadores_ffmpeg()` — Nombres de los codificadores que trae el FFmpeg instalado (`ffmpeg -encoders`)
- `codificador_funciona()` — Que FFmpeg lo liste no basta (puede no haber GPU o driver): prueba 1 fotograma
- `detectar_hw()` — Familias de aceleración que funcionan en este equipo, p. ej. ['nvenc']
- `elegir_hw()` — (familia o None, aviso). 'no' = software; 'auto' = la primera que funcione
- `argumentos_hw()` — Parámetros de vídeo del codificador por hardware, con calidad constante aproximada
- `argumento_fecha()` — `-metadata creation_time=...` (UTC) para una hora local de este equipo
- `metadatos_del_trabajo()` — Todos los -metadata de un vídeo: los externos y, si el nombre ha corregido la fecha de unos metadatos que no cuadraban (ver fecha_video), la fecha buena
- `argumentos_metadatos()` — `-metadata` de FFmpeg con lo que el vídeo no trae: fecha y ubicación solo si le faltan; descripción y palabras clave (álbumes y personas) siempre que las haya
- `comando_codificacion()`
- `comando_remux()` — Mismo vídeo y audio, sin recodificar, con metadatos añadidos
- `detener_ffmpeg()`
- `ejecutar_ffmpeg()` — Ejecuta FFmpeg mostrando el porcentaje (si hay etiqueta)
- `procesar_videos()` — Recodifica y organiza
