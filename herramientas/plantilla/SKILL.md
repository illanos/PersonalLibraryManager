---
name: @@nombre@@
description: Experta en usar @@titulo@@ (el paquete Python `@@nombre@@`, en `utilidades/@@nombre@@` de este monorepo) - @@resumen@@. Úsala siempre que el usuario quiera hacer algo de esto, aunque no nombre la herramienta ni el comando.
---

# @@titulo@@: guía de uso

@@resumen@@.

## Cómo ejecutarlo

Desde la raíz del monorepo, sin instalar nada:

```bash
PYTHONPATH=utilidades/@@nombre@@/src python -m @@nombre@@ estado
```

En PowerShell: `$env:PYTHONPATH="utilidades/@@nombre@@/src"; python -m @@nombre@@ estado`.

## Qué comando para cada objetivo

| El usuario quiere… | Comando |
|---|---|
| Comprobar que funciona | `estado` |

## Reglas

- (Qué hay que confirmar con el usuario antes de hacerlo, y qué no se hace nunca.)
