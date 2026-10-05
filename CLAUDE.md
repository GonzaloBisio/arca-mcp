# CLAUDE.md — arca-mcp

Servidor MCP multi-emisor para facturación electrónica con ARCA (ex AFIP). Python 3.12, SDK `mcp` 2.x (`MCPServer`), SOAP con `zeep`, firma CMS con `cryptography`. Parte del ecosistema One Core Labs: lo consumen Axis, Pulpix, NexCourt y uso personal.

## Regla de oro
El MCP **no conoce a ningún sistema cliente**. No importa, referencia ni modela nada de Axis/Pulpix/NexCourt. Recibe un `SolicitudComprobante` con importes ya calculados, valida consistencia fiscal y emite. La lógica de "buscar la venta" vive en el MCP de cada sistema; el agente orquesta.

## Arquitectura (hexagonal)
- `src/arca_mcp/core/` — dominio puro. Sin imports de zeep, sqlite, starlette ni mcp.
  - `models.py` modelos Pydantic con `extra="forbid"` · `validation.py` reglas fiscales · `service.py` casos de uso · `ports.py` protocolos · `errors.py`
- `src/arca_mcp/adapters/arca/` — WSAA (TRA + CMS + cache de TA) y WSFEv1. Implementa `FiscalGateway`.
- `src/arca_mcp/adapters/persistence/` — SQLite. Implementa `ComprobanteStore` y `TokenCache`.
- `src/arca_mcp/interfaces/` — tools MCP y auth por API key. Sin lógica fiscal.
- Dependencias siempre hacia adentro: interfaces/adapters → core, nunca al revés.

## Invariantes que no se rompen
1. Nunca emitir sin `preview_id` vigente, del mismo cliente, en estado `pendiente`.
2. Idempotencia: `(emisor_id, referencia.sistema, referencia.id)` aprobado una sola vez (índice único parcial).
3. Numeración bajo lock por `(cuit, punto_venta, tipo)`; con réplicas pasar a advisory lock de Postgres.
4. Si la solicitud de CAE se envió y no hubo respuesta → estado `incierto`, nunca reintentar a ciegas.
5. El LLM nunca calcula importes; el core valida, no recalcula precios.
6. `CondicionIVAReceptorId` siempre se envía (RG 5616, rechazo automático desde 01/12/2026).
7. Cada API key solo accede a sus emisores.

## Comandos
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # suite completa, sin red (gateway falso)
ARCA_CONFIG=config/emisores.yaml arca-mcp  # servidor local en :8000 (/mcp, /health)
docker compose -f deploy/compose.arca.yml config   # validar compose
```

## Convenciones
- Dominio fiscal en español (`neto_gravado`, `punto_venta`); nombres de tools MCP en inglés (`preview_invoice`).
- Mensajes de error en español rioplatense y accionables: el agente se los lee al usuario.
- Importes como `Decimal` con 2 decimales; a zeep se pasan como `float` recién en el adaptador.
- Todo cambio de comportamiento lleva test. Integración MCP en `tests/test_mcp_http.py`.
- Decisiones de diseño relevantes se registran en `DECISION-LOG.md`.

## Ambientes
- Homologación: `wsaahomo.afip.gov.ar` / `wswhomo.afip.gov.ar`. Certificado vía WSASS.
- Producción: `wsaa.afip.gov.ar` / `servicios1.afip.gov.ar`.
- `legacy_tls: true` por endpoints de ARCA con DH débil bajo OpenSSL 3.

## Estado y próximos pasos
- [x] Fase 1: core, WSAA, WSFEv1 (facturas A/B/C), MCP HTTP, SQLite, Docker, 29 tests.
- [x] Probar emisión real en homologación (Factura C monotributo): PV 1 N° 1 aprobada con CAE el 2026-10-04.
- [x] Notas de crédito/débito (A/B/C, `CbtesAsoc`).
- [ ] Tributos adicionales (RG 4127, RG 5631).
- [ ] Moneda extranjera (`MonCotiz`, `CanMisMonExt`).
- [ ] Postgres + advisory locks.
- [ ] PDF con QR fiscal.
- [ ] Onboarding de delegación de wsfe para comercios.
