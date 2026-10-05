class FiscalError(Exception):
    """Base de errores de dominio. El mensaje está pensado para que el agente se lo explique al usuario."""


class ValidacionError(FiscalError):
    def __init__(self, errores: list[str]):
        self.errores = errores
        super().__init__("La solicitud no es válida: " + " | ".join(errores))


class NoAutorizado(FiscalError):
    pass


class PreviewInvalido(FiscalError):
    pass


class ArcaError(FiscalError):
    """ARCA respondió con error, o falló la comunicación antes de enviar la solicitud de CAE."""


class EstadoIncierto(FiscalError):
    """Se envió la solicitud de CAE pero no hubo respuesta: puede o no haberse emitido."""
