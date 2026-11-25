# Notas — Arquitectura y decisiones

## Qué es

Libreta personal en local: notas de texto, imágenes y notas de voz, con categorías y búsqueda. La
página web es la interfaz principal; la línea de comandos sirve para apuntar deprisa, automatizar y
para que el agente pueda usarla (skill `notas`).

Las rutas de este documento son relativas a `utilidades/notas/`. La lista de módulos y funciones está
en `MAPA.md` (generado); aquí va lo que no se ve en el código.

## Capas

```
Interfaces       cli ───────────── servidor ── plantillas/ (notas.html · notas.css · notas.js)
                  │                   │
Operaciones      copia               │
                  │                   │
Base             cuaderno ────── adjuntos ────── errores
```

Cada capa solo usa las de debajo. `cuaderno.Cuaderno` es la única puerta a los datos: valida todo lo
que recibe, así la web y la terminal se comportan igual. Solo se usa la biblioteca estándar; Pillow es
opcional y solo lo importan `medidas` y `miniatura`, en `adjuntos.py`.

## El cuaderno

```
<cuaderno>/                      ~/Notas, NOTAS_CUADERNO o --cuaderno
├── notas.sqlite                 notas, categorías y qué adjuntos tiene cada una
├── adjuntos/AAAA/MM/…           20261125_074820_8b48dde3.webm
│   └── ../.miniaturas/          se pueden borrar: se vuelven a hacer
└── copias/                      notas_AAAAMMDD_HHMMSS.zip
```

- **Fuera del repositorio, y por defecto en la carpeta del usuario.** Son datos que no se pueden volver
  a generar. El gestor de fotos guarda sus datos (que sí se pueden) en `datos/`, dentro del proyecto;
  aquí no, porque un `git clean` o borrar una copia de trabajo se llevaría las notas.
- **SQLite para el texto, archivos sueltos para lo demás.** Los adjuntos se pueden ver y copiar sin el
  programa, y la base de datos se mantiene pequeña.
- **Una conexión por operación**, con espera de 30 s si está ocupada. La web (varios hilos) y la
  terminal pueden usar el mismo cuaderno a la vez. Cada escritura es una transacción: o todo o nada.
- **`PRAGMA user_version`** lleva la versión del esquema. Si cambia, `_preparar` tiene que migrar los
  cuadernos que ya existen; uno de una versión más nueva se rechaza con un mensaje claro.
- **Los identificadores no se reutilizan** (`AUTOINCREMENT`), y la dirección de cada adjunto lleva el
  nombre de su archivo (`?v=…`): el navegador los puede guardar en la caché para siempre.
- **Fechas en UTC** (ISO 8601 con milisegundos): se ordenan como texto y cada interfaz las enseña en la
  hora local.

### Notas

`titulo`, `texto`, `color`, `fijada`, `archivada`, `papelera` (cuándo se mandó, o nada), `creada`,
`modificada` y `version`.

- `modificada` y `version` solo suben al cambiar el título o el texto (y `modificada`, también al añadir
  o quitar adjuntos): ponerle un color a una nota vieja no la sube arriba.
- Archivar una nota la suelta, y fijar una archivada la saca del archivo. Estar fijada y archivada a la
  vez no significa nada.
- Una nota en la papelera no se puede cambiar: primero se restaura.

### Categorías

Una nota puede tener varias. Se identifican por su nombre sin mayúsculas ni acentos (`clave`): «Cocina»
y «cocina» son la misma, y se enseña como se escribió la primera vez. Se crean al usarlas. Quitar una
categoría no toca sus notas.

### Búsqueda

Todos los términos tienen que aparecer, cada uno en cualquier sitio: título y texto (columna `busqueda`,
ya normalizada), nombres de categorías o nombres de adjuntos. Es una búsqueda de trozos (`instr`), no de
palabras enteras: «instal» encuentra «instalador».

Se descartó FTS5: busca por palabras o prefijos, no por trozos, y hay que mantener su índice. Recorrer
3.000 notas tarda unos 15 ms, de sobra para una libreta personal.

En la página, al buscar desde las vistas normales se mira también en el archivo (aparecen aparte, en
«Archivadas»); la papelera solo se mira si se está en ella.

### Papelera

Nada se borra directamente. Las notas van a la papelera; los adjuntos que se quitan de una nota se
marcan (`quitado`) y se pueden recuperar con «Deshacer». Borran de verdad solo:

- `eliminar`, que ignora las notas que no estén en la papelera;
- `vaciar_papelera`, que pide escribir `VACIAR` y se lleva también los adjuntos quitados.

Ninguna de las dos está en la línea de comandos, a propósito: se hace desde la página, con una pregunta.

## Adjuntos

- **El tipo se decide por los primeros bytes** (`identificar`). El nombre y el tipo que declara el
  navegador solo desempatan WebM y MP4, que pueden llevar audio o vídeo. Así nunca se guarda ni se sirve
  como imagen un HTML o un SVG, que podrían ejecutar código en la página de las notas.
- **Se copian tal cual**, sin recomprimir, a un `.part` que se renombra al final. Si la petición se corta
  o no se puede anotar en la base de datos, no queda nada a medias.
- **Miniaturas** WebP de 720 px, hechas la primera vez que se piden y giradas según su EXIF. No se hacen
  si la imagen es pequeña o animada, ni sin Pillow: se sirve la original.
- **HEIC** se rechaza diciendo qué hacer: los navegadores no lo enseñan.

## Servidor y API

`http://127.0.0.1:8790/` (o el siguiente puerto libre). Si ese puerto ya lo ocupa este programa con el
mismo cuaderno, solo abre el navegador: dos dobles clics no arrancan dos servidores.

| Ruta | Qué hace |
|---|---|
| `GET /` · `GET /estaticos/…` | La página |
| `GET /api/estado` | Token, totales, categorías, colores |
| `GET /api/notas` | Lista: `vista`, `buscar`, `categoria`, `tipo`, `orden` |
| `POST /api/notas` · `GET`/`PATCH /api/notas/ID` | Crear, leer, cambiar (con `version`, 409 si hay conflicto) |
| `POST /api/notas/ID/adjuntos` | El cuerpo es el archivo; `X-Nombre` y `X-Duracion` en cabeceras |
| `POST /api/adjuntos/ID/quitar` · `…/recuperar` | Quitar un adjunto, o recuperarlo |
| `POST /api/lote` | `{ids, accion, valor}` sobre varias notas |
| `POST /api/categorias` · `PATCH`/`DELETE /api/categorias/ID` | Categorías |
| `POST /api/papelera/vaciar` | `{confirmar: "VACIAR"}` |
| `GET /api/copia` | Copia de seguridad (ZIP) |
| `GET /adjuntos/ID` · `…/miniatura` | El archivo (con rangos; `?descargar=1` para bajarlo) |

Los archivos se suben tal cual, uno por petición, en vez de en un formulario `multipart`: no hace falta
interpretarlo y se puede ir escribiendo a disco según llega.

### Seguridad

Cualquier web abierta en el navegador puede mandar peticiones a `127.0.0.1`. Por eso:

- **Solo escucha en 127.0.0.1** y rechaza las cabeceras `Host` que no sean locales (*DNS rebinding*).
- **La API y los adjuntos solo responden a la propia página** (`Sec-Fetch-Site`): otra web no puede leer
  nada, ni incrustar una imagen, ni tampoco otro programa local en otro puerto (la galería de fotos).
- **Cambiar algo exige el mismo origen y un token** de esa ejecución, que se lee de `/api/estado`. Si el
  programa se reinicia, la página recibe `codigo: "token"`, pide el nuevo y repite sola.
- **CSP sin nada en línea ni de fuera**, `nosniff`, y la página nunca interpreta HTML: se construye nodo
  a nodo con `el()`. Los enlaces del texto solo son `http(s)` y se abren sin `opener`.
- Los mensajes de error se dan después de leer lo que quede de la petición: si no, el navegador ve una
  conexión cortada en vez del mensaje.

## La página

HTML, CSS y JavaScript sin dependencias, en tres archivos (la CSP no admite nada en línea). Los colores
claro y oscuro salen de `light-dark()`; las preferencias (tema, orden, vista) se guardan en el navegador.
La vista va en la dirección (`#categoria=3`), así se puede recargar o ir atrás.

- **Rejilla**: cada tarjeta va a la columna más corta, de 60 en 60 según se baja. Con 3.000 notas, la
  carga completa tarda en torno a 0,1 s.
- **Guardado automático**: a los 0,7 s de dejar de escribir y al cerrar. Los guardados van en fila
  (`editor.cadena`): nunca hay dos a la vez. Sin conexión se reintenta cada 3 s, y no deja cerrar la nota
  sin preguntar.
- **Conflictos**: si el texto ha cambiado en otra ventana, se elige entre guardar lo propio encima, usar
  lo otro o guardar lo propio como otra nota. Nunca se pierde ninguno de los dos sin decidirlo.
- **Notas vacías**: una nota nueva que se queda sin nada desaparece al cerrarla; si ya existía, o llegó a
  tener adjuntos, va a la papelera.
- **Grabadora**: `MediaRecorder` en Opus (WebM u Ogg según el navegador), con pausa y nivel. La duración la
  mide la página, porque los WebM que graba el navegador no la llevan. Cerrar la nota mientras se graba
  guarda la grabación; si no se puede subir, se queda en la nota para reintentar o descargarla.
- **Reproductor** propio en vez del del navegador: cabe en la tarjeta, no descarga nada hasta que se pulsa,
  solo suena uno a la vez y tiene velocidad.
- **Avisos**: se mueven dentro del diálogo que esté abierto, porque lo de fuera no se puede pulsar.

## Pruebas

```powershell
python -m unittest discover -s tests -t .
```

`test_pagina.py` comprueba que lo que usa el JavaScript (identificadores, iconos, colores, rutas de la API)
existe de verdad, y que la página no tiene nada en línea ni de fuera. `test_skill.py`, que la skill
explica todos los comandos y opciones y no cita ninguno que no exista. Lo que necesita un navegador
(grabar, reproducir, arrastrar) se prueba a mano: ver `CLAUDE.md`.

## Posibles ampliaciones

- Transcribir las notas de voz en local (p. ej. con `faster-whisper`, opcional) para poder buscar en ellas.
- Importar las notas de Google Keep desde un Takeout.
- Listas con casillas.
- Abrirlas desde el móvil en la red local (con contraseña y HTTPS: sin él no se puede grabar).
