"""WSAA: autenticación con certificado X.509 y Ticket de Acceso (token + sign)."""
from __future__ import annotations

import base64
import logging
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7
from zeep import Client
from zeep.transports import Transport

from ...core.errors import ArcaError

log = logging.getLogger(__name__)
TZ_AR = ZoneInfo("America/Argentina/Cordoba")
MARGEN_RENOVACION = timedelta(minutes=10)


@dataclass(frozen=True)
class Ticket:
    token: str
    sign: str
    expira: datetime


class TokenCache(Protocol):
    def obtener_token(self, clave: str) -> Ticket | None: ...

    def guardar_token(self, clave: str, ticket: Ticket) -> None: ...


def build_tra(servicio: str, ahora: datetime | None = None) -> bytes:
    ahora = ahora or datetime.now(TZ_AR)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<loginTicketRequest version="1.0"><header>'
        f"<uniqueId>{int(time.time())}</uniqueId>"
        f"<generationTime>{(ahora - timedelta(minutes=10)).isoformat(timespec='seconds')}</generationTime>"
        f"<expirationTime>{(ahora + timedelta(minutes=10)).isoformat(timespec='seconds')}</expirationTime>"
        f"</header><service>{servicio}</service></loginTicketRequest>"
    ).encode()


def firmar_cms(tra: bytes, cert_path: Path, key_path: Path) -> str:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    cms = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(tra)
        .add_signer(cert, key, hashes.SHA256())
        .sign(serialization.Encoding.DER, [])  # sin DetachedSignature: ARCA exige el contenido embebido
    )
    return base64.b64encode(cms).decode()


def parsear_respuesta(xml: str) -> Ticket:
    root = ET.fromstring(xml.encode())
    token = root.findtext("credentials/token")
    sign = root.findtext("credentials/sign")
    expira = root.findtext("header/expirationTime")
    if not (token and sign and expira):
        raise ArcaError("Respuesta de WSAA incompleta.")
    return Ticket(token=token, sign=sign, expira=datetime.fromisoformat(expira))


class WsaaClient:
    def __init__(self, wsdl: str, cache: TokenCache, transport: Transport):
        self._wsdl = wsdl
        self._cache = cache
        self._transport = transport
        self._client: Client | None = None
        self._lock = threading.Lock()

    def ticket(self, cert_path: Path, key_path: Path, servicio: str = "wsfe") -> Ticket:
        # La clave es el certificado: con delegación, varios emisores comparten el mismo ticket.
        clave = f"{cert_path.resolve()}::{servicio}"
        vigente = self._vigente(clave)
        if vigente:
            return vigente
        with self._lock:
            vigente = self._vigente(clave)  # otro hilo pudo renovarlo mientras esperábamos
            if vigente:
                return vigente
            log.info("Solicitando nuevo TA a WSAA para %s", servicio)
            cms = firmar_cms(build_tra(servicio), cert_path, key_path)
            try:
                respuesta = self._svc().loginCms(in0=cms)
            except Exception as exc:
                # Error típico: "El CEE ya posee un TA valido" -> se perdió el cache.
                raise ArcaError(f"WSAA rechazó la autenticación: {exc}") from exc
            ticket = parsear_respuesta(respuesta)
            self._cache.guardar_token(clave, ticket)
            return ticket

    def _vigente(self, clave: str) -> Ticket | None:
        t = self._cache.obtener_token(clave)
        if t and t.expira - MARGEN_RENOVACION > datetime.now(TZ_AR):
            return t
        return None

    def _svc(self):
        if self._client is None:
            self._client = Client(self._wsdl, transport=self._transport)
        return self._client.service
