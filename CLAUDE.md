# PersonalLibraryManager — guía del agente

Monorepo de utilidades personales que funcionan en local, sin subir nada a ningún sitio. Cada una
vive en `utilidades/<nombre>/` y es un proyecto Python independiente: su paquete, sus pruebas, su
documentación y su skill.

@MAPA.md

## Cómo orientarse

1. **Decide de qué utilidad va la petición** con la tabla de arriba. Si la petición es de *usar* la
   utilidad (importar fotos, apuntar algo…), su skill sabe cómo. Si es de *programarla*, sigue.
2. **Lee `utilidades/<x>/CLAUDE.md` y `utilidades/<x>/MAPA.md`** antes de buscar por el código: el
   mapa dice qué hace cada módulo, quién lo usa y qué pruebas lo cubren.
3. Para el porqué de algo, `utilidades/<x>/doc/ARQUITECTURA.md`.

«Notas de voz» puede ser de las dos: los audios del móvil o de WhatsApp que se guardan con las
fotos son de **Fotos** (`exportador audio`); apuntar algo hablando, como en una libreta, es **Notas**.

## Raíz

| Qué | Para qué |
|---|---|
| `utilidades/` | Las utilidades, una por carpeta |
| `herramientas/mapas.py` | Regenera los `MAPA.md` y la tabla del README a partir del código |
| `herramientas/pruebas.py` | Pasa las pruebas de todo, o de lo que se diga (`pruebas.py notas`) |
| `herramientas/nueva_utilidad.py` | Crea una utilidad nueva ya conectada (skill `nueva-utilidad`) |
| `herramientas/plantilla/` | El esqueleto que copia `nueva_utilidad.py` |
| `.claude/skills/` | Una skill por utilidad, más `nueva-utilidad` |
| `fotos.bat`, `notas.bat`… | Abrir cada utilidad con doble clic |

## Reglas comunes

- **Las utilidades no se importan entre sí** ni comparten dependencias: se puede instalar, mover o
  borrar una sin tocar las demás. Un trozo pequeño repetido (p. ej. el servidor local) es a propósito.
- **Los datos del usuario no están en el repositorio** y no se tocan sin que lo pida: nada de
  importar, fusionar, borrar o editar en su biblioteca o en sus notas «para probar». Las pruebas,
  con carpetas temporales y datos inventados.
- **Nada se borra directamente**: hay papelera, y vaciarla es siempre decisión del usuario.
- **Escritura atómica**: a un `.part` y renombrar al final.
- **Solo local**: los servidores escuchan en `127.0.0.1`, comprueban `Host` y `Origin` y exigen un
  token para cambiar algo. Nada sale a internet sin pedirlo expresamente.
- **Biblioteca estándar primero**: las dependencias opcionales se omiten con un aviso si faltan. Las
  páginas web son HTML + CSS + JS sin dependencias.
- **Todo en español**: código, comentarios, mensajes, documentación y commits.
- Python 3.10+ en las utilidades; `herramientas/` necesita 3.11+.

## Al terminar un cambio

```bash
python herramientas/pruebas.py <utilidad>   # sus pruebas (sin argumentos, todas)
python herramientas/mapas.py                # si cambian módulos, funciones públicas o docstrings
```

Las pruebas de `herramientas` fallan si un mapa se queda atrasado, si falta el `CLAUDE.md`, la
documentación o la skill de una utilidad, o si dos usan el mismo puerto. Si cambia el
comportamiento, actualiza también la arquitectura, el README y la skill de esa utilidad.
