from conftest import AHORA, emisor, factura_b, factura_c

from arca_mcp.core.validation import cuit_valido, validar

HOY = AHORA.date()
MONO = emisor()
RI = emisor("ri", "responsable_inscripto", 30711111112)


def test_cuit_digito_verificador():
    assert cuit_valido(20123456786)
    assert not cuit_valido(20123456787)
    assert not cuit_valido(123)


def test_factura_c_valida():
    assert validar(factura_c(), MONO, HOY) == []


def test_factura_c_no_discrimina_iva():
    s = factura_c(importes={"neto_gravado": "1000.00", "iva": "210.00", "total": "1210.00"})
    assert any("no discrimina IVA" in e for e in validar(s, MONO, HOY))


def test_monotributo_no_emite_b():
    assert any("solo puede emitir comprobantes clase C" in e for e in validar(factura_b(emisor_id="mono"), MONO, HOY))


def test_factura_b_valida():
    assert validar(factura_b(), RI, HOY) == []


def test_iva_mal_calculado():
    s = factura_b(importes={"neto_gravado": "1000.00", "iva": "200.00", "total": "1200.00"},
                  alicuotas=[{"alicuota": "21", "base_imponible": "1000.00", "importe": "200.00"}])
    assert any("se esperaba 210.00" in e for e in validar(s, RI, HOY))


def test_total_inconsistente():
    s = factura_b(importes={"neto_gravado": "1000.00", "iva": "210.00", "total": "1300.00"})
    assert any("no coincide con neto" in e for e in validar(s, RI, HOY))


def test_factura_a_requiere_cuit():
    s = factura_b(tipo="factura_a")
    errores = validar(s, RI, HOY)
    assert any("requiere identificar al receptor por CUIT" in e for e in errores)
    assert any("consumidor final" in e for e in errores)


def test_servicios_requieren_periodo():
    assert any("período" in e for e in validar(factura_c(concepto="servicios"), MONO, HOY))


def test_fecha_fuera_de_rango():
    assert any("fuera del rango" in e for e in validar(factura_c(fecha="2026-09-01"), MONO, HOY))


def test_punto_de_venta_no_habilitado():
    assert any("punto de venta 9" in e for e in validar(factura_c(punto_venta=9), MONO, HOY))
