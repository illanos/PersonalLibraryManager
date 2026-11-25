---
name: nueva-utilidad
description: Cómo añadir una utilidad nueva a este monorepo (o renombrarla, o quitarla) manteniendo los mapas, las skills, las pruebas y la documentación. Úsala cuando el usuario pida una herramienta, aplicación, gestor o proyecto nuevo en este repositorio que no encaje en las utilidades que ya hay (Fotos, Notas…), o pregunte cómo está organizado el monorepo para ampliarlo.
---

# Añadir una utilidad al monorepo

## 1. ¿De verdad es nueva?

Mira `MAPA.md` (raíz). Si lo que pide es una función más de una utilidad que ya existe, va en ella. Es
nueva si tiene sus propios datos y se usa por separado.

## 2. Crear el esqueleto

Acuerda con el usuario el nombre (minúsculas sin acentos: será carpeta, paquete y comando), el título
y una frase de resumen. Desde la raíz:

```bash
python herramientas/nueva_utilidad.py recetas --titulo "Recetas" --resumen "Recetas de cocina, con ingredientes y búsqueda"
```

Crea, sin tocar lo demás:

```
utilidades/recetas/      paquete en src/, tests/, doc/ARQUITECTURA.md, README.md, CLAUDE.md, recetas.bat
recetas.bat              abrirla con doble clic desde la raíz
.claude/skills/recetas/  su skill
MAPA.md, README.md       regenerados con la utilidad nueva
```

## 3. Completarla

1. `pyproject.toml`, sección `[tool.monorepo]`: `abrir`, `datos` (dónde guarda lo del usuario, **fuera
   del repositorio**) y `puertos` si tiene servidor (que no los use otra: mira `MAPA.md`).
2. El código, siguiendo las *Reglas comunes* de `CLAUDE.md` (raíz): independiente de las demás, solo
   local, escritura atómica, papelera, biblioteca estándar primero, en español.
3. **Si necesita página web**, parte de `utilidades/notas/src/notas/servidor.py` (comprobaciones de
   `Host`, `Origin`, `Sec-Fetch-Site` y token, CSP, rangos) y de su página sin `innerHTML`. Cópialo: las
   utilidades no se importan entre sí.
4. `CLAUDE.md` de la utilidad: la tabla «dónde se cambia cada cosa» y las reglas que no se deducen del
   código. `doc/ARQUITECTURA.md`: las decisiones. La skill: qué comando para cada objetivo y qué hay
   que confirmar. Los textos entre paréntesis de la plantilla son para sustituirlos.
5. Pruebas con carpetas temporales, nunca con datos reales. Copia de `utilidades/notas/tests/test_skill.py`
   para que la skill no se quede atrás de los comandos.

## 4. Comprobar

```bash
python herramientas/mapas.py
python herramientas/pruebas.py
```

`herramientas/tests` comprueba que toda utilidad tiene `README.md`, `CLAUDE.md`, `doc/ARQUITECTURA.md`,
`MAPA.md` al día, pruebas, su `.bat` en la raíz y su skill, y que no hay puertos ni nombres repetidos.

## Renombrar o quitar una

- **Renombrar**: `git mv` de la carpeta, el `.bat` y la skill; `pyproject.toml`; y buscar el nombre viejo
  en todo el repositorio. Los datos del usuario no se mueven: si cambia su ubicación por defecto, la
  utilidad tiene que seguir encontrando la de antes.
- **Quitar**: borrar su carpeta, su `.bat` y su skill, y regenerar los mapas. Los datos del usuario se
  quedan donde estén.
