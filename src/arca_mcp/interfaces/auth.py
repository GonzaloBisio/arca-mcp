from __future__ import annotations

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def extraer_bearer(valor: str | None) -> str | None:
    if valor and valor.lower().startswith("bearer "):
        return valor[7:].strip() or None
    return None


class ApiKeyMiddleware:
    """Rechaza con 401 cualquier request sin una API key conocida (salvo rutas públicas)."""

    def __init__(self, app: ASGIApp, claves: set[str], publicas: tuple[str, ...] = ("/health",)):
        self.app = app
        self.claves = claves
        self.publicas = publicas

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.publicas:
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        key = extraer_bearer(headers.get("authorization"))
        if key is None or not any(hmac.compare_digest(key, c) for c in self.claves):
            await JSONResponse({"error": "no autorizado"}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)
