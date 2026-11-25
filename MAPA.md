# Mapa del monorepo

<!-- Generado por herramientas/mapas.py. No editar a mano: `python herramientas/mapas.py` -->

## Utilidades

| Utilidad | Para qué | Código | Se abre con | Datos del usuario | Puertos | Skill |
|---|---|---|---|---|---|---|
| **Fotos** | Importar, ordenar, optimizar y explorar fotos, vídeos y audios (galería, Google Fotos, repetidas) | `utilidades/fotos/src/exportador/` | `fotos.bat` o `python -m exportador panel` | La biblioteca que elija el usuario (`<biblioteca>/.exportador/`) | 8080, 8765 | `exportador` |
| **Notas** | Notas de texto, imágenes y notas de voz, con categorías y búsqueda | `utilidades/notas/src/notas/` | `notas.bat` o `python -m notas abrir` | `~/Notas` (o `NOTAS_CUADERNO`, o `--cuaderno`) | 8790 | `notas` |

## Dónde mirar

| Utilidad | Cómo trabajar en ella | Mapa del código | Decisiones | Pruebas |
|---|---|---|---|---|
| Fotos | `utilidades/fotos/CLAUDE.md` | `utilidades/fotos/MAPA.md` | `utilidades/fotos/doc/ARQUITECTURA.md` | `cd utilidades/fotos` y `python -m unittest discover -s tests -t .` |
| Notas | `utilidades/notas/CLAUDE.md` | `utilidades/notas/MAPA.md` | `utilidades/notas/doc/ARQUITECTURA.md` | `cd utilidades/notas` y `python -m unittest discover -s tests -t .` |
