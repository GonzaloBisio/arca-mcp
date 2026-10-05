"""Casos de uso. Orquesta validación, numeración, idempotencia y estado de los previews."""
from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from .errors import ArcaError, EstadoIncierto, NoAutorizado, PreviewInvalido, ValidacionError
from .models import (Cliente, Emisor, EstadoPreview, Preview, ResultadoEmision,
                     SolicitudComprobante, TipoComprobante)
from .ports import ComprobanteStore, FiscalGateway
from .validation import validar

log = logging.getLogger(__name__)
TZ_AR = ZoneInfo("America/Argentina/Cordoba")


class InvoiceService:
    def __init__(
        self,
        emisores: dict[str, Emisor],
        gateway: FiscalGateway,
        store: ComprobanteStore,
        preview_ttl: timedelta = timedelta(minutes=15),
        now: Callable[[], datetime] | None = None,
    ):
        self._emisores = emisores
        self._gateway = gateway
        self._store = store
        self._ttl = preview_ttl
        self._now = now or (lambda: datetime.now(TZ_AR))
        self._locks: dict[tuple[int, int, int], threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ---------- consultas ----------

    def emisores_de(self, cliente: Cliente) -> list[Emisor]:
        return [e for i, e in self._emisores.items() if i in cliente.emisores]

    def ultimo_numero(self, cliente: Cliente, emisor_id: str, tipo: TipoComprobante, punto_venta: int) -> int:
        return self._gateway.ultimo_autorizado(self._emisor(cliente, emisor_id), punto_venta, tipo)

    def consultar(self, cliente: Cliente, emisor_id: str, tipo: TipoComprobante,
                  punto_venta: int, numero: int) -> dict[str, Any]:
        return self._gateway.consultar(self._emisor(cliente, emisor_id), tipo, punto_venta, numero)

    def condiciones_iva(self, cliente: Cliente, emisor_id: str, clase: str) -> list[dict[str, Any]]:
        return self._gateway.condiciones_iva_receptor(self._emisor(cliente, emisor_id), clase)

    # ---------- preview ----------

    def preview(self, cliente: Cliente, s: SolicitudComprobante) -> Preview | ResultadoEmision:
        """Valida y reserva un preview. Si la operación ya fue facturada, devuelve ese resultado."""
        emisor = self._emisor(cliente, s.emisor_id)
        ahora = self._now()
        errores = validar(s, emisor, ahora.date())
        if errores:
            raise ValidacionError(errores)

        previo = self._store.buscar_aprobado(emisor.id, s.referencia)
        if previo is not None:
            return previo

        ultimo = self._gateway.ultimo_autorizado(emisor, s.punto_venta, s.tipo)
        preview = Preview(
            preview_id=uuid4().hex,
            cliente=cliente.nombre,
            emisor_id=emisor.id,
            emisor_cuit=emisor.cuit,
            emisor_razon_social=emisor.razon_social,
            solicitud=s,
            fecha=s.fecha or ahora.date(),
            numero_estimado=ultimo + 1,
            payload_hash=hashlib.sha256(s.model_dump_json().encode()).hexdigest(),
            creado=ahora,
            expira=ahora + self._ttl,
            estado=EstadoPreview.PENDIENTE,
        )
        self._store.guardar_preview(preview)
        return preview

    # ---------- emisión ----------

    def emitir(self, cliente: Cliente, preview_id: str) -> ResultadoEmision:
        p = self._store.obtener_preview(preview_id)
        if p is None or p.cliente != cliente.nombre:
            raise PreviewInvalido("El preview no existe. Generá uno nuevo con preview_invoice.")
        emisor = self._emisor(cliente, p.emisor_id)
        s = p.solicitud

        previo = self._store.buscar_aprobado(emisor.id, s.referencia)
        if previo is not None:
            return previo
        if self._now() > p.expira:
            raise PreviewInvalido("El preview expiró. Generá uno nuevo con preview_invoice.")
        if not self._store.reclamar_preview(preview_id):
            raise PreviewInvalido(f"El preview ya fue usado (estado: {p.estado.value}).")

        enviado = False
        with self._lock(emisor.cuit, s.punto_venta, s.tipo):
            try:
                numero = self._gateway.ultimo_autorizado(emisor, s.punto_venta, s.tipo) + 1
                enviado = True
                resultado = self._gateway.solicitar_cae(emisor, s, numero, p.fecha)
            except Exception as exc:
                if not enviado:
                    # Nada llegó a ARCA: el preview se puede reintentar.
                    self._store.actualizar_estado_preview(preview_id, EstadoPreview.PENDIENTE)
                    if isinstance(exc, ArcaError):
                        raise
                    raise ArcaError(f"No se pudo consultar la numeración en ARCA: {exc}") from exc
                log.exception("Solicitud de CAE sin respuesta (preview %s)", preview_id)
                self._store.actualizar_estado_preview(preview_id, EstadoPreview.INCIERTO)
                raise EstadoIncierto(
                    f"Se envió la solicitud a ARCA pero no hubo respuesta. Verificá con get_invoice "
                    f"el comprobante {s.tipo.value} PV {s.punto_venta} N° {numero} antes de reintentar."
                ) from exc

        self._store.guardar_resultado(preview_id, resultado)
        self._store.actualizar_estado_preview(
            preview_id,
            EstadoPreview.EMITIDO if resultado.estado == "aprobado" else EstadoPreview.RECHAZADO,
        )
        return resultado

    # ---------- helpers ----------

    def _emisor(self, cliente: Cliente, emisor_id: str) -> Emisor:
        emisor = self._emisores.get(emisor_id)
        if emisor is None or emisor_id not in cliente.emisores:
            raise NoAutorizado(f"El emisor '{emisor_id}' no existe o no está habilitado para este sistema.")
        return emisor

    def _lock(self, cuit: int, punto_venta: int, tipo: TipoComprobante) -> threading.Lock:
        # Un solo proceso: lock en memoria. Con réplicas, pasar a advisory lock de Postgres.
        clave = (cuit, punto_venta, tipo.codigo)
        with self._locks_guard:
            return self._locks.setdefault(clave, threading.Lock())
