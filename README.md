# PersonalLibraryManager

Utilidades para gestionar tus cosas personales —fotos, vídeos, notas— **en tu propio equipo, sin
subir nada a ningún sitio**. Cada una es un proyecto independiente: usa solo las que quieras.

<!-- utilidades:inicio -->

| Utilidad | Para qué | Se abre con |
|---|---|---|
| [Fotos](utilidades/fotos/README.md) | Importar, ordenar, optimizar y explorar fotos, vídeos y audios (galería, Google Fotos, repetidas) | `fotos.bat` o `python -m exportador panel` |
| [Notas](utilidades/notas/README.md) | Notas de texto, imágenes y notas de voz, con categorías y búsqueda | `notas.bat` o `python -m notas abrir` |

<!-- utilidades:fin -->

## Empezar

Necesitas **Python 3.10 o superior** ([python.org](https://www.python.org), marca *Add python.exe to
PATH*).

```powershell
git clone https://github.com/illanos/PersonalLibraryManager.git
cd PersonalLibraryManager
```

- **Notas**: doble clic en `notas.bat`. No hay que instalar nada más.
- **Fotos**: instala antes sus dependencias (y FFmpeg para los vídeos) como explica su
  [README](utilidades/fotos/README.md), y doble clic en `fotos.bat`.

En macOS y Linux, o desde la terminal, mira el README de cada utilidad.

> **Si ya tenías el repositorio** de cuando solo era el gestor de fotos: todo lo suyo está ahora en
> `utilidades/fotos/`. Si usabas `panel.bat`, ahora es `fotos.bat`; si lo instalaste con
> `pip install -e .`, repítelo con `pip install -e "utilidades/fotos[todo]"`; y si tienes una carpeta
> `datos/` en la raíz (ciudades, modelos de caras), muévela a `utilidades/fotos/`. Tus bibliotecas
> no cambian.

## Estructura

```
utilidades/
├── fotos/               el gestor de fotos (paquete exportador)
└── notas/               el gestor de notas (paquete notas)
herramientas/            mapas, pruebas y plantilla para utilidades nuevas
.claude/skills/          skills de Claude Code, una por utilidad
CLAUDE.md, MAPA.md       guía y mapa del repositorio para el agente
fotos.bat, notas.bat     abrir cada utilidad con doble clic
```

Dentro de cada utilidad: `src/` (el código), `tests/`, `doc/ARQUITECTURA.md` (decisiones de diseño),
`README.md` (cómo se usa), `CLAUDE.md` (cómo trabajar en ella) y `MAPA.md` (dónde está cada cosa).

## Pruebas

```powershell
python herramientas/pruebas.py          # todo
python herramientas/pruebas.py notas    # solo una utilidad
```

## Añadir otra utilidad

```powershell
python herramientas/nueva_utilidad.py recetas --titulo "Recetas" --resumen "Recetas de cocina, con ingredientes y búsqueda"
```

Crea la carpeta con su código de partida, pruebas, documentación, skill y `.bat`, y actualiza los
mapas y la tabla de arriba. `herramientas/` necesita Python 3.11 o superior.

Si cambias módulos o funciones, regenera los mapas con `python herramientas/mapas.py` (las pruebas
avisan si se quedan atrás).

## Ayuda con Claude Code

Abre [Claude Code](https://claude.com/claude-code) en esta carpeta y pídele, en tus palabras, lo que
quieras hacer: «importa las fotos del móvil», «apúntame que el martes viene el instalador», «busca lo
que tenía anotado de la cocina», «añade una utilidad para las recetas». `CLAUDE.md` y los mapas le
dicen dónde está cada cosa y las skills, cómo se usa cada utilidad.

## Licencia

[MIT](LICENSE)
