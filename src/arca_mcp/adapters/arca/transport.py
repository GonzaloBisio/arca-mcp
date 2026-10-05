import ssl

import requests
from requests.adapters import HTTPAdapter
from zeep.transports import Transport


class _LegacyTLSAdapter(HTTPAdapter):
    """Algunos endpoints de ARCA usan parámetros DH que OpenSSL 3 rechaza por defecto
    ("dh key too small"). Bajar el nivel de seguridad solo para estas conexiones lo resuelve."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def build_transport(timeout: int = 30, legacy_tls: bool = True) -> Transport:
    session = requests.Session()
    if legacy_tls:
        session.mount("https://", _LegacyTLSAdapter())
    return Transport(session=session, timeout=timeout, operation_timeout=timeout)
