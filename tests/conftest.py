from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from arca_mcp.adapters.persistence.sqlite_store import SqliteStore
from arca_mcp.core.models import Cliente, Emisor, ResultadoEmision, SolicitudComprobante
from arca_mcp.core.service import TZ_AR, InvoiceService

AHORA = datetime(2026, 10, 4, 12, 0, tzinfo=TZ_AR)


class FakeGateway:
    def __init__(self):
        self.ultimos: dict = {}
        self.respuesta = "A"
        self.fallar_al_enviar = False
        self.envios = 0
        self.solicitudes: list = []  # Track all solicitar_cae calls for verification

    def ultimo_autorizado(self, emisor, punto_venta, tipo):
        return self.ultimos.get((emisor.cuit, punto_venta, tipo), 0)

    def solicitar_cae(self, emisor, s, numero, fecha):
        self.envios += 1
        self.solicitudes.append({"emisor": emisor, "solicitud": s, "numero": numero, "fecha": fecha})
        if self.fallar_al_enviar:
            raise TimeoutError("ARCA no respondió")
        aprobado = self.respuesta == "A"
        if aprobado:
            self.ultimos[(emisor.cuit, s.punto_venta, s.tipo)] = numero
        return ResultadoEmision(
            estado="aprobado" if aprobado else "rechazado", emisor_id=emisor.id, tipo=s.tipo,
            punto_venta=s.punto_venta, numero=numero if aprobado else None, fecha=fecha,
            total=s.importes.total, cae="76123456789012" if aprobado else None,
            cae_vencimiento=fecha + timedelta(days=10) if aprobado else None,
            errores=[] if aprobado else ["10016: rechazo simulado"], referencia=s.referencia,
        )

    def consultar(self, emisor, tipo, punto_venta, numero):
        return {"encontrado": True}

    def condiciones_iva_receptor(self, emisor, clase):
        return []


def emisor(id="mono", condicion="monotributo", cuit=20123456786):
    return Emisor(id=id, cuit=cuit, razon_social=f"Emisor {id}", condicion_iva=condicion,
                  puntos_venta=[1, 2], certificado=Path("x.crt"), clave_privada=Path("x.key"))


@pytest.fixture
def emisores():
    return {"mono": emisor(), "ri": emisor("ri", "responsable_inscripto", 30711111112)}


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def service(emisores, gateway, tmp_path):
    return InvoiceService(emisores, gateway, SqliteStore(tmp_path / "t.db"), now=lambda: AHORA)


@pytest.fixture
def axis():
    return Cliente(nombre="axis", emisores=frozenset({"mono", "ri"}))


def factura_c(**over) -> SolicitudComprobante:
    datos = {
        "emisor_id": "mono", "tipo": "factura_c", "punto_venta": 1, "concepto": "productos",
        "receptor": {"doc_tipo": "sin_identificar", "doc_nro": 0, "condicion_iva": "consumidor_final"},
        "importes": {"neto_gravado": "1500.00", "total": "1500.00"},
        "referencia": {"sistema": "axis", "id": "venta-1234"},
    }
    datos.update(over)
    return SolicitudComprobante.model_validate(datos)


def factura_b(**over) -> SolicitudComprobante:
    datos = {
        "emisor_id": "ri", "tipo": "factura_b", "punto_venta": 1, "concepto": "productos",
        "receptor": {"doc_tipo": "sin_identificar", "doc_nro": 0, "condicion_iva": "consumidor_final"},
        "importes": {"neto_gravado": "1000.00", "iva": "210.00", "total": "1210.00"},
        "alicuotas": [{"alicuota": "21", "base_imponible": "1000.00", "importe": "210.00"}],
        "referencia": {"sistema": "axis", "id": "venta-5678"},
    }
    datos.update(over)
    return SolicitudComprobante.model_validate(datos)


def nota_credito_c(**over) -> SolicitudComprobante:
    datos = {
        "emisor_id": "mono", "tipo": "nota_credito_c", "punto_venta": 1, "concepto": "productos",
        "receptor": {"doc_tipo": "sin_identificar", "doc_nro": 0, "condicion_iva": "consumidor_final"},
        "importes": {"neto_gravado": "1500.00", "total": "1500.00"},
        "comprobantes_asociados": [{"tipo": "factura_c", "punto_venta": 1, "numero": 1}],
        "referencia": {"sistema": "axis", "id": "nc-1234"},
    }
    datos.update(over)
    return SolicitudComprobante.model_validate(datos)


def nota_credito_b(**over) -> SolicitudComprobante:
    datos = {
        "emisor_id": "ri", "tipo": "nota_credito_b", "punto_venta": 1, "concepto": "productos",
        "receptor": {"doc_tipo": "sin_identificar", "doc_nro": 0, "condicion_iva": "consumidor_final"},
        "importes": {"neto_gravado": "1000.00", "iva": "210.00", "total": "1210.00"},
        "alicuotas": [{"alicuota": "21", "base_imponible": "1000.00", "importe": "210.00"}],
        "comprobantes_asociados": [{"tipo": "factura_b", "punto_venta": 1, "numero": 1}],
        "referencia": {"sistema": "axis", "id": "nc-5678"},
    }
    datos.update(over)
    return SolicitudComprobante.model_validate(datos)
