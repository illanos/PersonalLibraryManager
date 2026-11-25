"""Notas: gestor local de notas de texto, imágenes y notas de voz, con categorías y búsqueda.

Línea de comandos:  python -m notas <comando> ...   (o `notas`, una vez instalado)

Módulos principales (ver doc/ARQUITECTURA.md y MAPA.md):
    cli         Comandos y opciones (argparse)
    cuaderno    Notas, categorías, búsqueda y papelera (SQLite)
    adjuntos    Imágenes y notas de voz: identificarlas, guardarlas, miniaturas
    copia       Copia de seguridad en un ZIP
    servidor    Servidor local: la página web y su API
"""

__version__ = "1.0.0"
