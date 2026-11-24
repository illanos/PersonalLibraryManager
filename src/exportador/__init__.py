"""Exportador: organiza, renombra y optimiza bibliotecas de fotos, vídeos y notas de voz.

Línea de comandos:  python -m exportador <comando> ...   (o `exportador`, una vez instalado)

Módulos principales (ver doc/ARQUITECTURA.md):
    cli            Comandos y opciones (argparse)
    fotos          Importación de fotos            videos     Importación de vídeos (FFmpeg)
    audio          Notas de voz y audios           takeout    Google Fotos (Takeout)
    galeria        Índice y miniaturas             servidor   Servidor local de la galería
    fusionar       Añadir otra colección           limpieza   «Limpiar repetidas»
    reorganizar    Ordenar una biblioteca          panel      Panel web
"""

__version__ = "1.0.0"
