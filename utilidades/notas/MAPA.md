# Mapa de Notas

<!-- Generado por herramientas/mapas.py. No editar a mano: `python herramientas/mapas.py` -->

Paquete `notas` (`src/notas/`). Las rutas son relativas a `utilidades/notas/`. Para el porqué de las cosas, `doc/ARQUITECTURA.md`; para cómo trabajar aquí, `CLAUDE.md`.

## Módulos

| Módulo | Qué hace | Usa | Lo usan | Pruebas (`tests/`) |
|---|---|---|---|---|
| `adjuntos.py` | Imágenes y notas de voz: identificar el archivo, guardarlo y sacar su miniatura | `errores` | `cli`, `copia`, `cuaderno`, `keep`, `servidor` | `test_adjuntos` |
| `cli.py` | Línea de comandos de Notas: notas de texto, imágenes y notas de voz, con categorías y búsqueda | `adjuntos`, `copia`, `cuaderno`, `errores`, `keep`, `servidor` | `__main__` | `test_cli`, `test_skill` |
| `copia.py` | Copia de seguridad del cuaderno en un ZIP | `adjuntos`, `cuaderno`, `errores` | `cli`, `servidor` | `test_copia` |
| `cuaderno.py` | El cuaderno: notas, categorías, búsqueda y papelera, en una carpeta del usuario | `adjuntos`, `errores` | `cli`, `copia`, `keep`, `servidor` | `test_cli`, `test_copia`, `test_cuaderno`, `test_keep`, `test_pagina`, `test_servidor`, `test_skill` |
| `errores.py` | Errores que se pueden enseñar tal cual al usuario (en la web o en la terminal) | — | `adjuntos`, `cli`, `copia`, `cuaderno`, `keep`, `servidor` | `test_adjuntos`, `test_copia`, `test_cuaderno`, `test_keep` |
| `keep.py` | Importar las notas de Google Keep desde una exportación de Google Takeout | `adjuntos`, `cuaderno`, `errores` | `cli` | `test_keep` |
| `servidor.py` | Servidor local de las notas: la página web y su API | `adjuntos`, `copia`, `cuaderno`, `errores` | `cli` | `test_pagina`, `test_servidor` |

Otros archivos del paquete: `plantillas/icono.svg`, `plantillas/notas.css`, `plantillas/notas.html`, `plantillas/notas.js`.

## Qué hay en cada módulo

Solo lo público (sin `_` delante), en el orden en que aparece.

### `adjuntos.py`

- `identificar()` — (tipo, mime, extensión) según los primeros bytes; AdjuntoNoValido si no se admite
- `limpiar_nombre()` — Nombre para enseñar y descargar: sin rutas ni caracteres de control, acotado
- `guardar()` — Copia `flujo` en `carpeta`/adjuntos/AAAA/MM/ y devuelve los datos del adjunto
- `ruta_segura()` — Ruta absoluta de un adjunto, comprobando que no se sale de la carpeta de adjuntos
- `medidas()` — (ancho, alto) ya girada según su EXIF, o (None, None) sin Pillow o si no se puede leer
- `miniatura()` — Ruta de la miniatura WebP (se crea la primera vez) o None si no se puede o no hace falta
- `borrar_archivos()` — Borra de verdad los archivos de adjuntos ya eliminados de la base de datos

### `cli.py`

- `construir_parser()`
- `main()`
- `ejecutar()` — Punto de entrada: consola en UTF-8 y salida limpia al interrumpir

### `copia.py`

- `nombre_copia()`
- `crear_copia()` — Crea el ZIP (por defecto en <cuaderno>/copias/) y devuelve su ruta
- `escribir_copia()` — Escribe el ZIP de la copia en un archivo binario ya abierto

### `cuaderno.py`

- `carpeta_cuaderno()` — La carpeta del cuaderno: la elegida, la de NOTAS_CUADERNO o ~/Notas
- `normalizar()` — Sin mayúsculas ni acentos, para buscar y comparar: «Reunión» -> «reunion»
- `terminos()` — [(excluir, término normalizado)] de lo que escribe el usuario en el buscador
- `class Cuaderno` — Acceso a las notas de una carpeta
  - `.listar`, `.nota`, `.estado`, `.crear`, `.editar`, `.lote`, `.importadas`, `.importar`, `.eliminar`, `.vaciar_papelera`, `.categorias`, `.buscar_categoria`, `.crear_categoria`, `.renombrar_categoria`, `.borrar_categoria`, `.adjuntar`, `.adjuntar_archivo`, `.adjunto`, `.quitar_adjunto`

### `errores.py`

- `class ErrorNotas` — Petición que no se puede hacer; el mensaje está escrito para el usuario
- `class NoEncontrada` — La nota, la categoría o el adjunto no existe
- `class Conflicto` — El texto de la nota ha cambiado desde que se abrió (en otra ventana o terminal)
- `class AdjuntoNoValido` — El archivo no es una imagen ni un audio que se pueda guardar en una nota

### `keep.py`

- `class NotaKeep` — Una nota del Takeout, ya en el idioma del cuaderno
  - `.vacia`
- `class Takeout`
- `class Resumen` — Qué ha pasado (o pasaría, al simular)
- `momento_adjunto()` — Cuándo se añadió un adjunto, según el nombre que le pone Keep, o None si no lo dice
- `leer()` — Las notas de Keep que hay en `carpeta` (la del Takeout, o la de Keep dentro de él)
- `reducir_imagen()` — La imagen a tamaño de pantalla, o la original si ya ocupa menos o no hay Pillow
- `convertir_audio()` — (datos, extensión, segundos) de una nota de voz: tal cual, o en M4A si es 3GP o AMR
- `importar()` — Añade al cuaderno las notas del Takeout que aún no tenga; con `simular`, solo las cuenta

### `servidor.py`

- `es_local()`
- `class PeticionNoValida`
- `class ManejadorNotas`
- `class ServidorLocal`
- `crear_servidor()` — Servidor de `cuaderno` en 127.0.0.1, en el primer puerto libre desde `puerto`
- `ya_abierto()` — True si en ese puerto ya está este programa con el mismo cuaderno
- `servir()`
