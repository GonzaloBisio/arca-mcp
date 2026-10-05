"""WSFEv1: implementación de FiscalGateway contra ARCA."""
from __future__ import annotations

import json
import threading
from datetime import date, datetime
from typing import Any

from zeep import Client
from zeep.helpers import serialize_object
from zeep.transports import Transport

from ...core.errors import ArcaError
from ...core.models import (Concepto, Emisor, ResultadoEmision, SolicitudComprobante,
                            TipoComprobante)
from .wsaa import WsaaClient


def _mensajes(obj: Any, contenedor: str, item: str) -> list[str]:
    cont = getattr(obj, contenedor, None) if obj is not None else None
    items = getattr(cont, item, None) if cont is not None else None
    return [f"{i.Code}: {i.Msg}" for i in (items or [])]


def _fecha(valor: str | None) -> date | None:
    return datetime.strptime(valor, "%Y%m%d").date() if valor else None


def _plano(obj: Any) -> Any:
    return json.loads(json.dumps(serialize_object(obj), default=str))


class WsfeGateway:
    def __init__(self, wsdl: str, wsaa: WsaaClient, transport: Transport):
        self._wsdl = wsdl
        self._wsaa = wsaa
        self._transport = transport
        self._client: Client | None = None
        self._lock = threading.Lock()

    def ultimo_autorizado(self, emisor: Emisor, punto_venta: int, tipo: TipoComprobante) -> int:
        r = self._svc().FECompUltimoAutorizado(Auth=self._auth(emisor), PtoVta=punto_venta, CbteTipo=tipo.codigo)
        errores = _mensajes(r, "Errors", "Err")
        if errores:
            raise ArcaError("ARCA: " + " | ".join(errores))
        return int(r.CbteNro)

    def solicitar_cae(self, emisor: Emisor, s: SolicitudComprobante, numero: int, fecha: date) -> ResultadoEmision:
        imp = s.importes
        det: dict[str, Any] = {
            "Concepto": s.concepto.codigo,
            "DocTipo": s.receptor.doc_tipo.codigo,
            "DocNro": s.receptor.doc_nro,
            "CbteDesde": numero,
            "CbteHasta": numero,
            "CbteFch": fecha.strftime("%Y%m%d"),
            "ImpTotal": float(imp.total),
            "ImpTotConc": float(imp.no_gravado),
            "ImpNeto": float(imp.neto_gravado),
            "ImpOpEx": float(imp.exento),
            "ImpTrib": 0.0,
            "ImpIVA": float(imp.iva),
            "MonId": "PES",
            "MonCotiz": 1,
            "CondicionIVAReceptorId": s.receptor.condicion_iva.codigo,
        }
        if s.concepto != Concepto.PRODUCTOS and s.servicio:
            det["FchServDesde"] = s.servicio.desde.strftime("%Y%m%d")
            det["FchServHasta"] = s.servicio.hasta.strftime("%Y%m%d")
            det["FchVtoPago"] = s.servicio.vencimiento_pago.strftime("%Y%m%d")
        if s.alicuotas:
            det["Iva"] = {"AlicIva": [
                {"Id": a.alicuota.codigo, "BaseImp": float(a.base_imponible), "Importe": float(a.importe)}
                for a in s.alicuotas
            ]}
        req = {
            "FeCabReq": {"CantReg": 1, "PtoVta": s.punto_venta, "CbteTipo": s.tipo.codigo},
            "FeDetReq": {"FECAEDetRequest": [det]},
        }
        r = self._svc().FECAESolicitar(Auth=self._auth(emisor), FeCAEReq=req)

        errores = _mensajes(r, "Errors", "Err")
        detalle = r.FeDetResp.FECAEDetResponse[0] if r.FeDetResp else None
        observaciones = _mensajes(detalle, "Observaciones", "Obs")
        aprobado = detalle is not None and detalle.Resultado == "A"
        return ResultadoEmision(
            estado="aprobado" if aprobado else "rechazado",
            emisor_id=emisor.id,
            tipo=s.tipo,
            punto_venta=s.punto_venta,
            numero=numero if aprobado else None,
            fecha=fecha,
            total=imp.total,
            cae=detalle.CAE if aprobado else None,
            cae_vencimiento=_fecha(detalle.CAEFchVto) if aprobado else None,
            observaciones=observaciones,
            errores=errores,
            referencia=s.referencia,
        )

    def consultar(self, emisor: Emisor, tipo: TipoComprobante, punto_venta: int, numero: int) -> dict[str, Any]:
        r = self._svc().FECompConsultar(
            Auth=self._auth(emisor),
            FeCompConsReq={"CbteTipo": tipo.codigo, "CbteNro": numero, "PtoVta": punto_venta},
        )
        errores = _mensajes(r, "Errors", "Err")
        if errores:
            return {"encontrado": False, "errores": errores}
        return {"encontrado": True, "comprobante": _plano(r.ResultGet)}

    def condiciones_iva_receptor(self, emisor: Emisor, clase: str) -> list[dict[str, Any]]:
        r = self._svc().FEParamGetCondicionIvaReceptor(Auth=self._auth(emisor), ClaseCmp=clase)
        errores = _mensajes(r, "Errors", "Err")
        if errores:
            raise ArcaError("ARCA: " + " | ".join(errores))
        return _plano(r.ResultGet.CondicionIvaReceptor) or []

    def _auth(self, emisor: Emisor) -> dict[str, Any]:
        t = self._wsaa.ticket(emisor.certificado, emisor.clave_privada, "wsfe")
        return {"Token": t.token, "Sign": t.sign, "Cuit": emisor.cuit}

    def _svc(self):
        with self._lock:
            if self._client is None:
                self._client = Client(self._wsdl, transport=self._transport)
        return self._client.service
