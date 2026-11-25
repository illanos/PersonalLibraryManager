# @@titulo@@ (`utilidades/@@nombre@@`)

@@resumen@@.

## Antes de tocar nada

- `MAPA.md` — cada módulo, qué hace, quién lo usa y qué pruebas tiene. Léelo antes de buscar.
- `doc/ARQUITECTURA.md` — el porqué de las decisiones.
- Para **usar** la utilidad (no programarla): skill `@@nombre@@`.

## Dónde se cambia cada cosa

| Quiero… | Está en |
|---|---|
| Añadir o cambiar un comando u opción | `src/@@nombre@@/cli.py`, y la skill `.claude/skills/@@nombre@@/SKILL.md` |

## Reglas de esta utilidad

- (Escribe aquí lo que no se deduce del código: qué datos son del usuario y dónde están, qué no
  se puede romper, qué ha pedido expresamente el usuario.)

## Comprobar un cambio

```bash
python herramientas/pruebas.py @@nombre@@     # desde la raíz del monorepo
python herramientas/mapas.py               # si cambian módulos o funciones públicas
```
