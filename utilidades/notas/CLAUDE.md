# Notas (`utilidades/notas`)

Notas de texto, imágenes y notas de voz, con categorías y búsqueda. Interfaces: página web local
(`abrir`) y línea de comandos. Solo usa la biblioteca estándar; Pillow es opcional (miniaturas).

## Antes de tocar nada

- `MAPA.md` — cada módulo, qué hace, quién lo usa y qué pruebas tiene. Léelo antes de buscar.
- `doc/ARQUITECTURA.md` — cómo se guardan las notas, la API y el porqué de cada decisión.
- Para **usar** las notas (apuntar, buscar, ordenar): skill `notas`.

## Dónde se cambia cada cosa

| Quiero… | Está en |
|---|---|
| Qué es una nota, qué se puede cambiar, cómo se busca | `src/notas/cuaderno.py` |
| El esquema de la base de datos | `cuaderno.py`: `ESQUEMA`, `VERSION_BD` y `_preparar` (con migración: ya hay cuadernos) |
| Qué archivos se admiten, miniaturas | `adjuntos.py` |
| Añadir una ruta a la API | `servidor.py`: `RUTAS` y su método |
| La página: estructura / aspecto / comportamiento | `plantillas/notas.html` / `notas.css` / `notas.js` |
| Grabar y reproducir voz | `plantillas/notas.js`, secciones «grabadora» y «reproductor» |
| Un color de nota | `COLORES` en `cuaderno.py` y `.color-x` en `notas.css` |
| Comandos y opciones | `cli.py`, y la skill `.claude/skills/notas/SKILL.md` (una prueba comprueba que coinciden) |
| La copia de seguridad | `copia.py` |

## Reglas de esta utilidad

- **Las notas del usuario (`~/Notas`) no se tocan para probar**: `--cuaderno` con una carpeta temporal.
- **No perder nunca lo escrito ni lo grabado**: guardado automático con `version` (un cambio de otra
  ventana no se pisa), reintento si se apaga el programa, una grabación que no se puede subir se
  queda en la página para reintentar o descargar. Si cambias el editor, vuelve a probar esos casos.
- **Nada se borra**: las notas van a la papelera y los adjuntos se marcan como quitados. Solo
  `eliminar` y `vaciar_papelera` borran, y el usuario lo confirma.
- **El tipo de un adjunto se decide por su contenido** (`adjuntos.identificar`), nunca por el nombre ni
  por lo que diga el navegador. No se admiten SVG ni HTML.
- **La página no usa `innerHTML`** (se construye con `el()`) ni nada de fuera ni en línea: la CSP lo bloquea.
- Toda ruta que cambie algo va por POST, PATCH o DELETE (ahí se exigen origen y token), nunca por GET.

## Comprobar un cambio

```bash
python herramientas/pruebas.py notas     # desde la raíz del monorepo
python herramientas/mapas.py             # si cambian módulos o funciones públicas
```

Para ver la página: `PYTHONPATH=utilidades/notas/src python -m notas abrir --cuaderno <carpeta temporal>`.
En un navegador sin micrófono, se puede sustituir `navigator.mediaDevices.getUserMedia` por un
`AudioContext` con un oscilador y `createMediaStreamDestination()`.
