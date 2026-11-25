"""Errores que se pueden enseñar tal cual al usuario (en la web o en la terminal)."""


class ErrorNotas(Exception):
    """Petición que no se puede hacer; el mensaje está escrito para el usuario."""


class NoEncontrada(ErrorNotas):
    """La nota, la categoría o el adjunto no existe."""


class Conflicto(ErrorNotas):
    """El texto de la nota ha cambiado desde que se abrió (en otra ventana o terminal)."""

    def __init__(self, nota: dict):
        super().__init__("La nota ha cambiado en otra ventana")
        self.nota = nota


class AdjuntoNoValido(ErrorNotas):
    """El archivo no es una imagen ni un audio que se pueda guardar en una nota."""
