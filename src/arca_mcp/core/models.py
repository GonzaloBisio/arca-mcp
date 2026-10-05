"""Modelo de dominio fiscal. No conoce ARCA (SOAP) ni a los sistemas cliente."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Importe = Annotated[Decimal, Field(ge=0, max_digits=15, decimal_places=2)]


class TipoComprobante(str, Enum):
    FACTURA_A = "factura_a"
    FACTURA_B = "factura_b"
    FACTURA_C = "factura_c"

    @property
    def codigo(self) -> int:
        return _COD_TIPO[self]

    @property
    def clase(self) -> str:
        return self.value[-1].upper()


class Concepto(str, Enum):
    PRODUCTOS = "productos"
    SERVICIOS = "servicios"
    PRODUCTOS_Y_SERVICIOS = "productos_y_servicios"

    @property
    def codigo(self) -> int:
        return _COD_CONCEPTO[self]


class DocTipo(str, Enum):
    CUIT = "cuit"
    CUIL = "cuil"
    DNI = "dni"
    SIN_IDENTIFICAR = "sin_identificar"

    @property
    def codigo(self) -> int:
        return _COD_DOC[self]


class CondicionIvaReceptor(str, Enum):
    """Códigos de FEParamGetCondicionIvaReceptor (RG 5616).

    Verificalos contra el ambiente real con la tool list_receiver_vat_conditions.
    """
    RESPONSABLE_INSCRIPTO = "responsable_inscripto"
    EXENTO = "exento"
    CONSUMIDOR_FINAL = "consumidor_final"
    MONOTRIBUTO = "monotributo"
    NO_CATEGORIZADO = "no_categorizado"
    CLIENTE_EXTERIOR = "cliente_exterior"
    IVA_LIBERADO = "iva_liberado"
    MONOTRIBUTO_SOCIAL = "monotributo_social"
    IVA_NO_ALCANZADO = "iva_no_alcanzado"

    @property
    def codigo(self) -> int:
        return _COD_COND_IVA[self]


class Alicuota(str, Enum):
    CERO = "0"
    DOS_Y_MEDIO = "2.5"
    CINCO = "5"
    DIEZ_Y_MEDIO = "10.5"
    VEINTIUNO = "21"
    VEINTISIETE = "27"

    @property
    def codigo(self) -> int:
        return _COD_ALICUOTA[self]

    @property
    def tasa(self) -> Decimal:
        return Decimal(self.value) / Decimal(100)


_COD_TIPO = {TipoComprobante.FACTURA_A: 1, TipoComprobante.FACTURA_B: 6, TipoComprobante.FACTURA_C: 11}
_COD_CONCEPTO = {Concepto.PRODUCTOS: 1, Concepto.SERVICIOS: 2, Concepto.PRODUCTOS_Y_SERVICIOS: 3}
_COD_DOC = {DocTipo.CUIT: 80, DocTipo.CUIL: 86, DocTipo.DNI: 96, DocTipo.SIN_IDENTIFICAR: 99}
_COD_COND_IVA = {
    CondicionIvaReceptor.RESPONSABLE_INSCRIPTO: 1,
    CondicionIvaReceptor.EXENTO: 4,
    CondicionIvaReceptor.CONSUMIDOR_FINAL: 5,
    CondicionIvaReceptor.MONOTRIBUTO: 6,
    CondicionIvaReceptor.NO_CATEGORIZADO: 7,
    CondicionIvaReceptor.CLIENTE_EXTERIOR: 9,
    CondicionIvaReceptor.IVA_LIBERADO: 10,
    CondicionIvaReceptor.MONOTRIBUTO_SOCIAL: 13,
    CondicionIvaReceptor.IVA_NO_ALCANZADO: 15,
}
_COD_ALICUOTA = {
    Alicuota.CERO: 3, Alicuota.DOS_Y_MEDIO: 9, Alicuota.CINCO: 8,
    Alicuota.DIEZ_Y_MEDIO: 4, Alicuota.VEINTIUNO: 5, Alicuota.VEINTISIETE: 6,
}


class _Estricto(BaseModel):
    # extra="forbid": si el LLM inventa un campo, falla en vez de ignorarse en silencio
    model_config = ConfigDict(extra="forbid")


# ---------- Configuración de dominio ----------

class Emisor(_Estricto):
    id: str
    cuit: int
    razon_social: str
    condicion_iva: Literal["responsable_inscripto", "monotributo", "exento"]
    puntos_venta: list[int]
    certificado: Path
    clave_privada: Path


class Cliente(_Estricto):
    """Sistema que consume el MCP (axis, pulpix, personal...) y los emisores que puede usar."""
    nombre: str
    emisores: frozenset[str]


# ---------- Entrada: comprobante ya calculado por el sistema origen ----------

class Receptor(_Estricto):
    doc_tipo: DocTipo
    doc_nro: int = Field(0, ge=0, description="0 cuando doc_tipo es sin_identificar")
    condicion_iva: CondicionIvaReceptor


class AlicuotaIva(_Estricto):
    alicuota: Alicuota
    base_imponible: Importe
    importe: Importe


class Importes(_Estricto):
    neto_gravado: Importe = Field(description="En factura C: el total del comprobante")
    no_gravado: Importe = Decimal("0")
    exento: Importe = Decimal("0")
    iva: Importe = Decimal("0")
    total: Importe


class PeriodoServicio(_Estricto):
    desde: date
    hasta: date
    vencimiento_pago: date


class ReferenciaExterna(_Estricto):
    """Identifica la operación en el sistema origen. Garantiza idempotencia por emisor."""
    sistema: str = Field(min_length=1, max_length=40)
    id: str = Field(min_length=1, max_length=120)


class SolicitudComprobante(_Estricto):
    emisor_id: str
    tipo: TipoComprobante
    punto_venta: int = Field(ge=1, le=99998)
    concepto: Concepto
    receptor: Receptor
    importes: Importes
    alicuotas: list[AlicuotaIva] = Field(default_factory=list)
    fecha: date | None = Field(None, description="Por defecto, hoy (hora de Argentina)")
    servicio: PeriodoServicio | None = None
    referencia: ReferenciaExterna


# ---------- Salidas ----------

class EstadoPreview(str, Enum):
    PENDIENTE = "pendiente"
    EN_PROCESO = "en_proceso"
    EMITIDO = "emitido"
    RECHAZADO = "rechazado"
    INCIERTO = "incierto"


class Preview(_Estricto):
    preview_id: str
    cliente: str
    emisor_id: str
    emisor_cuit: int
    emisor_razon_social: str
    solicitud: SolicitudComprobante
    fecha: date
    numero_estimado: int
    payload_hash: str
    creado: datetime
    expira: datetime
    estado: EstadoPreview


class ResultadoEmision(_Estricto):
    estado: Literal["aprobado", "rechazado"]
    emisor_id: str
    tipo: TipoComprobante
    punto_venta: int
    numero: int | None
    fecha: date
    total: Decimal
    cae: str | None = None
    cae_vencimiento: date | None = None
    observaciones: list[str] = Field(default_factory=list)
    errores: list[str] = Field(default_factory=list)
    referencia: ReferenciaExterna
