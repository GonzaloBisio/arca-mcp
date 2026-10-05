import base64
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from arca_mcp.adapters.arca.wsaa import build_tra, firmar_cms, parsear_respuesta


@pytest.fixture
def credenciales(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "arca-mcp-test")])
    ahora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(ahora).not_valid_after(ahora + timedelta(days=1))
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "t.crt", tmp_path / "t.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path


def test_tra_tiene_servicio_y_ventana():
    tra = build_tra("wsfe").decode()
    assert "<service>wsfe</service>" in tra and "<generationTime>" in tra and "<expirationTime>" in tra


@pytest.mark.skipif(shutil.which("openssl") is None, reason="requiere openssl")
def test_cms_embebe_el_tra_y_verifica(credenciales, tmp_path):
    cert_path, key_path = credenciales
    tra = build_tra("wsfe")
    cms = tmp_path / "tra.cms"
    cms.write_bytes(base64.b64decode(firmar_cms(tra, cert_path, key_path)))
    contenido = subprocess.run(
        ["openssl", "cms", "-verify", "-inform", "DER", "-in", str(cms), "-noverify"],
        capture_output=True, check=True,
    ).stdout
    assert contenido == tra


def test_parsea_respuesta_de_wsaa():
    xml = ('<?xml version="1.0" encoding="UTF-8"?><loginTicketResponse version="1.0"><header>'
           '<expirationTime>2026-10-05T00:10:00.123-03:00</expirationTime></header>'
           '<credentials><token>TOK</token><sign>SIG</sign></credentials></loginTicketResponse>')
    t = parsear_respuesta(xml)
    assert (t.token, t.sign) == ("TOK", "SIG") and t.expira.utcoffset() == timedelta(hours=-3)
