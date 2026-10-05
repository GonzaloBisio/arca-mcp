import pytest
from conftest import factura_c

from arca_mcp.core.errors import EstadoIncierto, NoAutorizado, PreviewInvalido, ValidacionError
from arca_mcp.core.models import Cliente, Preview, ResultadoEmision


def test_preview_y_emision(service, axis):
    p = service.preview(axis, factura_c())
    assert isinstance(p, Preview) and p.numero_estimado == 1
    r = service.emitir(axis, p.preview_id)
    assert r.estado == "aprobado" and r.numero == 1 and r.cae


def test_reemitir_preview_aprobado_devuelve_la_misma_factura(service, axis, gateway):
    p = service.preview(axis, factura_c())
    primera = service.emitir(axis, p.preview_id)
    reintento = service.emitir(axis, p.preview_id)
    assert reintento.cae == primera.cae and gateway.envios == 1


def test_preview_rechazado_no_se_reutiliza(service, axis, gateway):
    gateway.respuesta = "R"
    p = service.preview(axis, factura_c())
    service.emitir(axis, p.preview_id)
    with pytest.raises(PreviewInvalido, match="rechazado"):
        service.emitir(axis, p.preview_id)


def test_idempotencia_por_referencia(service, axis, gateway):
    p = service.preview(axis, factura_c())
    primera = service.emitir(axis, p.preview_id)
    repetida = service.preview(axis, factura_c())
    assert isinstance(repetida, ResultadoEmision) and repetida.cae == primera.cae
    assert gateway.envios == 1


def test_numeracion_correlativa(service, axis):
    for i in range(1, 4):
        p = service.preview(axis, factura_c(referencia={"sistema": "axis", "id": str(i)}))
        assert service.emitir(axis, p.preview_id).numero == i


def test_otro_sistema_no_usa_el_preview(service, axis):
    p = service.preview(axis, factura_c())
    pulpix = Cliente(nombre="pulpix", emisores=frozenset({"mono"}))
    with pytest.raises(PreviewInvalido):
        service.emitir(pulpix, p.preview_id)


def test_emisor_no_habilitado(service):
    personal = Cliente(nombre="personal", emisores=frozenset({"ri"}))
    with pytest.raises(NoAutorizado):
        service.preview(personal, factura_c())


def test_validacion_bloquea_preview(service, axis, gateway):
    with pytest.raises(ValidacionError):
        service.preview(axis, factura_c(punto_venta=9))


def test_rechazo_de_arca_no_cuenta_para_idempotencia(service, axis, gateway):
    gateway.respuesta = "R"
    p = service.preview(axis, factura_c())
    assert service.emitir(axis, p.preview_id).estado == "rechazado"
    gateway.respuesta = "A"
    p2 = service.preview(axis, factura_c())
    assert isinstance(p2, Preview)
    assert service.emitir(axis, p2.preview_id).estado == "aprobado"


def test_timeout_al_enviar_queda_incierto(service, axis, gateway):
    gateway.fallar_al_enviar = True
    p = service.preview(axis, factura_c())
    with pytest.raises(EstadoIncierto, match="get_invoice"):
        service.emitir(axis, p.preview_id)
    with pytest.raises(PreviewInvalido, match="incierto"):
        service.emitir(axis, p.preview_id)
