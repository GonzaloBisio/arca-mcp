"""Validación de consistencia fiscal. No recalcula precios: verifica que lo recibido cierre."""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .models import Concepto, CondicionIvaReceptor, DocTipo, Emisor, SolicitudComprobante

CENTAVO = Decimal("0.01")
TOLERANCIA = Decimal("0.01")
_PESOS_CUIT = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def cuit_valido(numero: int) -> bool:
    s = str(numero)
    if len(s) != 11 or not s.isdigit():
        return False
    resto = sum(int(d) * p for d, p in zip(s[:10], _PESOS_CUIT)) % 11
    dv = 11 - resto
    dv = 0 if dv == 11 else dv
    return dv != 10 and dv == int(s[10])


def validar(s: SolicitudComprobante, emisor: Emisor, hoy: date) -> list[str]:
    errores: list[str] = []
    clase = s.tipo.clase
    r, imp = s.receptor, s.importes

    # Emisor y punto de venta
    if s.punto_venta not in emisor.puntos_venta:
        errores.append(f"El punto de venta {s.punto_venta} no está habilitado para el emisor {emisor.id}.")
    if emisor.condicion_iva in ("monotributo", "exento") and clase != "C":
        errores.append(f"Un emisor {emisor.condicion_iva} solo puede emitir comprobantes clase C.")
    if emisor.condicion_iva == "responsable_inscripto" and clase == "C":
        errores.append("Un responsable inscripto emite comprobantes A o B, no C.")

    # Receptor
    if r.doc_tipo == DocTipo.SIN_IDENTIFICAR:
        if r.doc_nro != 0:
            errores.append("Con doc_tipo sin_identificar, doc_nro debe ser 0.")
        if r.condicion_iva != CondicionIvaReceptor.CONSUMIDOR_FINAL:
            errores.append("Un receptor sin identificar solo puede ser consumidor final.")
    elif r.doc_tipo in (DocTipo.CUIT, DocTipo.CUIL) and not cuit_valido(r.doc_nro):
        errores.append(f"El {r.doc_tipo.value.upper()} {r.doc_nro} no es válido (dígito verificador).")
    elif r.doc_tipo == DocTipo.DNI and not 1 <= r.doc_nro <= 99_999_999:
        errores.append(f"El DNI {r.doc_nro} no es válido.")
    if clase == "A":
        if r.doc_tipo != DocTipo.CUIT:
            errores.append("La factura A requiere identificar al receptor por CUIT.")
        if r.condicion_iva == CondicionIvaReceptor.CONSUMIDOR_FINAL:
            errores.append("No se emite factura A a un consumidor final.")

    # Importes
    if imp.total <= 0:
        errores.append("El total debe ser mayor a 0.")
    suma = imp.neto_gravado + imp.no_gravado + imp.exento + imp.iva
    if abs(suma - imp.total) > TOLERANCIA:
        errores.append(f"El total ({imp.total}) no coincide con neto + no gravado + exento + IVA ({suma}).")

    if clase == "C":
        if imp.iva != 0 or s.alicuotas:
            errores.append("La factura C no discrimina IVA: iva debe ser 0 y alicuotas vacío.")
        if imp.no_gravado != 0 or imp.exento != 0:
            errores.append("En factura C, no_gravado y exento deben ser 0: el total va en neto_gravado.")
    else:
        if imp.neto_gravado > 0 and not s.alicuotas:
            errores.append("Hay neto gravado pero no se informaron alícuotas de IVA.")
        codigos = [a.alicuota for a in s.alicuotas]
        if len(codigos) != len(set(codigos)):
            errores.append("Hay alícuotas repetidas: agrupá las bases por alícuota.")
        suma_bases = sum((a.base_imponible for a in s.alicuotas), Decimal("0"))
        suma_iva = sum((a.importe for a in s.alicuotas), Decimal("0"))
        if abs(suma_bases - imp.neto_gravado) > TOLERANCIA:
            errores.append(f"La suma de bases imponibles ({suma_bases}) no coincide con el neto gravado ({imp.neto_gravado}).")
        if abs(suma_iva - imp.iva) > TOLERANCIA:
            errores.append(f"La suma de IVA por alícuota ({suma_iva}) no coincide con el IVA total ({imp.iva}).")
        for a in s.alicuotas:
            esperado = (a.base_imponible * a.alicuota.tasa).quantize(CENTAVO, rounding=ROUND_HALF_UP)
            if abs(esperado - a.importe) > TOLERANCIA:
                errores.append(f"IVA {a.alicuota.value}%: sobre {a.base_imponible} se esperaba {esperado}, llegó {a.importe}.")

    # Fecha y período de servicio
    fecha = s.fecha or hoy
    margen = 5 if s.concepto == Concepto.PRODUCTOS else 10
    if abs((fecha - hoy).days) > margen:
        errores.append(f"La fecha {fecha} está fuera del rango permitido (±{margen} días desde hoy).")
    if s.concepto != Concepto.PRODUCTOS:
        if s.servicio is None:
            errores.append("Para servicios hay que informar el período (desde, hasta, vencimiento_pago).")
        elif s.servicio.desde > s.servicio.hasta:
            errores.append("El período de servicio tiene 'desde' posterior a 'hasta'.")
    elif s.servicio is not None:
        errores.append("El período de servicio solo corresponde a conceptos de servicios.")

    return errores
