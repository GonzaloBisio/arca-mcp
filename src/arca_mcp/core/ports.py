from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from .models import (Emisor, EstadoPreview, Preview, ReferenciaExterna, ResultadoEmision,
                     SolicitudComprobante, TipoComprobante)


class FiscalGateway(Protocol):
    def ultimo_autorizado(self, emisor: Emisor, punto_venta: int, tipo: TipoComprobante) -> int: ...

    def solicitar_cae(self, emisor: Emisor, solicitud: SolicitudComprobante,
                      numero: int, fecha: date) -> ResultadoEmision: ...

    def consultar(self, emisor: Emisor, tipo: TipoComprobante, punto_venta: int,
                  numero: int) -> dict[str, Any]: ...

    def condiciones_iva_receptor(self, emisor: Emisor, clase: str) -> list[dict[str, Any]]: ...


class ComprobanteStore(Protocol):
    def guardar_preview(self, preview: Preview) -> None: ...

    def obtener_preview(self, preview_id: str) -> Preview | None: ...

    def reclamar_preview(self, preview_id: str) -> bool:
        """Pasa de pendiente a en_proceso de forma atómica. False si ya no estaba pendiente."""
        ...

    def actualizar_estado_preview(self, preview_id: str, estado: EstadoPreview) -> None: ...

    def buscar_aprobado(self, emisor_id: str, referencia: ReferenciaExterna) -> ResultadoEmision | None: ...

    def guardar_resultado(self, preview_id: str, resultado: ResultadoEmision) -> None: ...
