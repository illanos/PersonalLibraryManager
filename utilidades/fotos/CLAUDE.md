# Fotos (`utilidades/fotos`)

El Exportador (paquete `exportador`): importa, ordena por fecha, optimiza y explora fotos, vídeos y
audios. Interfaces: línea de comandos, panel web y galería web.

## Antes de tocar nada

- `MAPA.md` — cada módulo, qué hace, quién lo usa y qué pruebas tiene. Léelo antes de buscar.
- `doc/ARQUITECTURA.md` — las capas, el porqué de cada decisión y todas las opciones.
- Para **usar** el programa (no programarlo): skill `exportador`.

## Dónde se cambia cada cosa

| Quiero… | Está en |
|---|---|
| Añadir o cambiar un comando u opción | `src/exportador/cli.py` (el panel la muestra solo); luego regenerar la referencia de la skill |
| Cómo se decide la fecha o el nombre de un archivo | `media_utils.py`, y `fotos.py` / `videos.py` / `audio.py` |
| Qué va a `WhatsApp/`, capturas o pegatinas | `clasificacion.py` |
| Qué se considera ya importado o descartado | `catalogo.py` |
| Fotos parecidas y repetidas | `similares.py` (comparar), `limpieza.py` (decidir y papelera) |
| Leer o conservar EXIF, XMP, IPTC | `metadatos.py` |
| Google Fotos (Takeout) | `takeout.py` |
| Fusionar colecciones | `fusionar.py` y `fusion_metadatos.py` |
| La galería: índice, miniaturas / página / servidor | `galeria.py` / `plantillas/galeria.html` / `servidor.py` |
| Caras y lugares | `caras.py`, `lugares.py` (datos descargados con `descargas.py`) |
| El panel | `panel.py` y `plantillas/panel.html` |

## Reglas de esta utilidad

- **El origen solo se lee.** Nunca se mueve, modifica ni borra nada de la carpeta de origen.
- **No lanzar importaciones ni fusiones reales** sobre la biblioteca del usuario sin que lo diga:
  `--simular`, o una muestra copiada a una carpeta temporal.
- **WhatsApp va siempre aparte** (`WhatsApp/`) y la galería no lo mezcla con el resto.
- Las opciones de cada comando se definen una sola vez, en el `argparse` de `cli.py`.
- Los módulos pesados (vídeo, caras, servidor) se importan dentro de las funciones que los usan.

## Comprobar un cambio

```bash
python herramientas/pruebas.py fotos                                  # desde la raíz del monorepo
python .claude/skills/exportador/scripts/opciones.py --escribir       # si cambia la CLI
python herramientas/mapas.py                                          # si cambian módulos o funciones públicas
```
