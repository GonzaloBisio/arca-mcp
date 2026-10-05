from __future__ import annotations

import logging
import os
from datetime import timedelta

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from .adapters.arca.endpoints import ENDPOINTS
from .adapters.arca.transport import build_transport
from .adapters.arca.wsaa import WsaaClient
from .adapters.arca.wsfe import WsfeGateway
from .adapters.persistence.sqlite_store import SqliteStore
from .config import Settings, load_settings, resolver_clientes
from .core.ports import FiscalGateway
from .core.service import InvoiceService
from .interfaces.auth import ApiKeyMiddleware
from .interfaces.mcp_server import build_server


def build_app(settings: Settings, gateway: FiscalGateway | None = None) -> Starlette:
    clientes = resolver_clientes(settings)
    store = SqliteStore(settings.db_path)
    if gateway is None:
        urls = ENDPOINTS[settings.ambiente]
        transport = build_transport(settings.timeout_segundos, settings.legacy_tls)
        wsaa = WsaaClient(urls["wsaa"], store, transport)
        gateway = WsfeGateway(urls["wsfe"], wsaa, transport)
    service = InvoiceService(
        emisores={e.id: e for e in settings.emisores},
        gateway=gateway,
        store=store,
        preview_ttl=timedelta(minutes=settings.preview_ttl_minutos),
    )
    # Protección DNS rebinding: solo se aceptan estos Host (nombre del servicio en Docker + local)
    hosts = os.environ.get("ARCA_ALLOWED_HOSTS", "arca-mcp:*,localhost:*,127.0.0.1:*").split(",")
    app = build_server(service, clientes).streamable_http_app(
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(allowed_hosts=[h.strip() for h in hosts if h.strip()]),
    )
    app.add_middleware(ApiKeyMiddleware, claves=set(clientes))
    return app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings(os.environ.get("ARCA_CONFIG", "/app/config/emisores.yaml"))
    logging.getLogger(__name__).info("Ambiente ARCA: %s", settings.ambiente)
    uvicorn.run(build_app(settings), host=os.environ.get("ARCA_HOST", "0.0.0.0"),
                port=int(os.environ.get("ARCA_PORT", "8000")))


if __name__ == "__main__":
    main()
