"""Integración de punta a punta: servidor HTTP real + cliente MCP real + gateway falso."""
import json
import socket
import threading
import time
from pathlib import Path

import anyio
import httpx2
import pytest
import uvicorn
from conftest import FakeGateway
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from arca_mcp.config import ClienteConfig, Settings
from arca_mcp.core.models import Emisor
from arca_mcp.main import build_app

KEY_AXIS = "a" * 64
KEY_PULPIX = "b" * 64


@pytest.fixture(scope="module")
def url(tmp_path_factory, monkeypatch_module):
    monkeypatch_module.setenv("KEY_AXIS", KEY_AXIS)
    monkeypatch_module.setenv("KEY_PULPIX", KEY_PULPIX)
    settings = Settings(
        db_path=tmp_path_factory.mktemp("db") / "arca.db",
        emisores=[Emisor(id="mono", cuit=20123456786, razon_social="Gon", condicion_iva="monotributo",
                         puntos_venta=[1], certificado=Path("x"), clave_privada=Path("x"))],
        clientes=[ClienteConfig(nombre="axis", api_key_env="KEY_AXIS", emisores=["mono"]),
                  ClienteConfig(nombre="pulpix", api_key_env="KEY_PULPIX", emisores=[])],
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(build_app(settings, FakeGateway()), port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def llamar(url: str, key: str, pasos):
    async def run():
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"}) as http:
            async with streamable_http_client(f"{url}/mcp", http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    return await pasos(session)
    return anyio.run(run)


def datos(resultado) -> dict:
    assert not resultado.is_error, resultado.content
    if not resultado.content:  # una lista vacía no genera bloques de contenido
        return []
    return json.loads(resultado.content[0].text)


SOLICITUD = {
    "emisor_id": "mono", "tipo": "factura_c", "punto_venta": 1, "concepto": "productos",
    "receptor": {"doc_tipo": "sin_identificar", "doc_nro": 0, "condicion_iva": "consumidor_final"},
    "importes": {"neto_gravado": "1500.00", "total": "1500.00"},
    "referencia": {"sistema": "axis", "id": "venta-1234"},
}


def test_health_publico(url):
    assert httpx2.get(f"{url}/health").json() == {"status": "ok"}


def test_sin_api_key_401(url):
    assert httpx2.post(f"{url}/mcp", json={}).status_code == 401


def test_flujo_completo(url):
    async def pasos(session):
        nombres = {t.name for t in (await session.list_tools()).tools}
        preview = datos(await session.call_tool("preview_invoice", {"solicitud": SOLICITUD}))
        emitida = datos(await session.call_tool("emit_invoice", {"preview_id": preview["preview_id"]}))
        repetida = datos(await session.call_tool("preview_invoice", {"solicitud": SOLICITUD}))
        return nombres, preview, emitida, repetida

    nombres, preview, emitida, repetida = llamar(url, KEY_AXIS, pasos)
    assert {"preview_invoice", "emit_invoice", "get_invoice", "list_issuers"} <= nombres
    assert preview["estado"] == "pendiente_de_confirmacion"
    assert preview["resumen"]["total"] == "1500.00"
    assert emitida["estado"] == "aprobado" and emitida["numero"] == 1
    assert repetida["estado"] == "ya_emitido"


def test_error_de_validacion_llega_legible(url):
    async def pasos(session):
        mala = {**SOLICITUD, "importes": {"neto_gravado": "1000.00", "iva": "210.00", "total": "1210.00"}}
        return await session.call_tool("preview_invoice", {"solicitud": mala})

    r = llamar(url, KEY_AXIS, pasos)
    assert r.is_error and "no discrimina IVA" in r.content[0].text


def test_aislamiento_entre_sistemas(url):
    async def pasos(session):
        emisores = datos(await session.call_tool("list_issuers", {}))
        intento = await session.call_tool("preview_invoice", {"solicitud": SOLICITUD})
        return emisores, intento

    emisores, intento = llamar(url, KEY_PULPIX, pasos)
    assert emisores == []
    assert intento.is_error and "no está habilitado" in intento.content[0].text
