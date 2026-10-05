"""Interfaz MCP. Traduce tools <-> casos de uso. Sin lógica fiscal acá."""
from __future__ import annotations

from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..core.errors import FiscalError
from ..core.models import Cliente, Preview, ResultadoEmision, SolicitudComprobante, TipoComprobante
from ..core.service import InvoiceService
from .auth import extraer_bearer

INSTRUCCIONES = """\
Servidor fiscal para emitir comprobantes electrónicos ante ARCA (ex AFIP).
No calcula precios: recibe importes ya calculados por el sistema origen y valida su consistencia.
Flujo obligatorio para emitir:
1. preview_invoice con la solicitud completa.
2. Mostrar al usuario el resumen devuelto y pedir confirmación explícita.
3. Solo con confirmación, emit_invoice con el preview_id.
Nunca modifiques importes recibidos del sistema origen. Si una validación falla, explicale el error al usuario.
"""


def build_server(service: InvoiceService, clientes: dict[str, Cliente]) -> MCPServer:
    mcp = MCPServer("arca-fiscal", instructions=INSTRUCCIONES, version="0.1.0")

    def cliente_de(ctx: Context) -> Cliente:
        request = ctx.request_context.request
        key = extraer_bearer(request.headers.get("authorization")) if request is not None else None
        cliente = clientes.get(key or "")
        if cliente is None:
            raise ToolError("No autorizado.")
        return cliente

    async def ejecutar(fn, *args) -> Any:
        try:
            return await anyio.to_thread.run_sync(fn, *args)
        except FiscalError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.tool()
    async def list_issuers(ctx: Context) -> list[dict[str, Any]]:
        """Lista los emisores (CUITs) que este sistema puede usar, con su condición fiscal y puntos de venta."""
        cliente = cliente_de(ctx)
        return [
            {"emisor_id": e.id, "cuit": e.cuit, "razon_social": e.razon_social,
             "condicion_iva": e.condicion_iva, "puntos_venta": e.puntos_venta}
            for e in service.emisores_de(cliente)
        ]

    @mcp.tool()
    async def preview_invoice(solicitud: SolicitudComprobante, ctx: Context) -> dict[str, Any]:
        """Valida un comprobante y genera un preview para confirmar. NO emite nada ante ARCA.

        Los importes deben venir calculados por el sistema origen: el total debe ser
        neto_gravado + no_gravado + exento + iva. En factura C, todo el total va en neto_gravado,
        iva = 0 y alicuotas vacío. La referencia (sistema + id de la venta) evita facturar dos veces
        la misma operación: si ya fue facturada, se devuelve la factura existente con estado 'ya_emitido'.
        """
        resultado = await ejecutar(service.preview, cliente_de(ctx), solicitud)
        if isinstance(resultado, ResultadoEmision):
            return {"estado": "ya_emitido", "comprobante": resultado.model_dump(mode="json")}
        return _resumen_preview(resultado)

    @mcp.tool()
    async def emit_invoice(preview_id: str, ctx: Context) -> dict[str, Any]:
        """Emite ante ARCA el comprobante de un preview y obtiene el CAE.

        Llamar SOLO después de que el usuario confirmó explícitamente el preview.
        Es irreversible: una factura emitida solo se anula con nota de crédito.
        """
        resultado: ResultadoEmision = await ejecutar(service.emitir, cliente_de(ctx), preview_id)
        return resultado.model_dump(mode="json")

    @mcp.tool()
    async def get_invoice(emisor_id: str, tipo: TipoComprobante, punto_venta: int, numero: int,
                          ctx: Context) -> dict[str, Any]:
        """Consulta en ARCA un comprobante ya emitido. Útil para verificar emisiones con estado incierto."""
        return await ejecutar(service.consultar, cliente_de(ctx), emisor_id, tipo, punto_venta, numero)

    @mcp.tool()
    async def get_last_invoice_number(emisor_id: str, tipo: TipoComprobante, punto_venta: int,
                                      ctx: Context) -> dict[str, int]:
        """Devuelve el último número autorizado en ARCA para un emisor, tipo y punto de venta."""
        numero = await ejecutar(service.ultimo_numero, cliente_de(ctx), emisor_id, tipo, punto_venta)
        return {"ultimo_numero": numero}

    @mcp.tool()
    async def list_receiver_vat_conditions(emisor_id: str, clase: str, ctx: Context) -> list[dict[str, Any]]:
        """Lista las condiciones frente al IVA del receptor válidas en ARCA para una clase de comprobante (A, B o C)."""
        return await ejecutar(service.condiciones_iva, cliente_de(ctx), emisor_id, clase.upper())

    return mcp


def _resumen_preview(p: Preview) -> dict[str, Any]:
    s = p.solicitud
    return {
        "estado": "pendiente_de_confirmacion",
        "preview_id": p.preview_id,
        "expira": p.expira.isoformat(),
        "resumen": {
            "emisor": f"{p.emisor_razon_social} (CUIT {p.emisor_cuit})",
            "comprobante": f"{s.tipo.value.replace('_', ' ').title()} PV {s.punto_venta:05d}",
            "numero_estimado": p.numero_estimado,
            "fecha": p.fecha.isoformat(),
            "receptor": f"{s.receptor.doc_tipo.value} {s.receptor.doc_nro} ({s.receptor.condicion_iva.value})",
            "neto_gravado": str(s.importes.neto_gravado),
            "iva": str(s.importes.iva),
            "total": str(s.importes.total),
            "referencia": f"{s.referencia.sistema}:{s.referencia.id}",
        },
        "siguiente_paso": "Mostrar este resumen al usuario y, solo si confirma, llamar emit_invoice.",
    }
