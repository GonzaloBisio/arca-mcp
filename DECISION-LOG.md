# Decision log

## 2026-10-04 — MCP fiscal agnóstico de los sistemas
El MCP de ARCA solo expone operaciones fiscales sobre un schema canónico. Cada sistema expone sus datos con su propio MCP y el agente orquesta. Permite reutilizarlo en Axis, Pulpix, NexCourt y uso personal.

## 2026-10-04 — Importes calculados afuera, validados adentro
El sistema origen calcula; el MCP valida consistencia (totales, alícuotas, clase vs condición) sin recalcular precios. Evita duplicar lógica comercial y que el LLM toque números.

## 2026-10-04 — Preview + confirmación + emisión por `preview_id`
`emit_invoice` no recibe importes, solo un `preview_id` generado por el propio MCP. Lo que el usuario confirma es exactamente lo que se emite.

## 2026-10-04 — Reemitir un preview aprobado devuelve la misma factura
Por idempotencia, un reintento tras un corte de red devuelve el resultado existente en vez de error.

## 2026-10-04 — SDK mcp 2.x (`MCPServer`), streamable HTTP stateless
Se usa la API actual del SDK. Stateless + JSON response simplifica el despliegue detrás de Docker. Protección DNS rebinding con `ARCA_ALLOWED_HOSTS`.

## 2026-10-04 — SQLite en fase 1
Un contenedor menos en el droplet. El store está detrás de un puerto: migrar a Postgres es reescribir un adaptador.

## 2026-10-04 — Python para este servicio
El ecosistema principal es Java/Spring, pero el MCP en Python aprovecha el SDK oficial y suma diversidad al portfolio. El contrato es HTTP/MCP, así que los servicios Java lo consumen sin acoplarse.

## 2026-10-04 — Notas de crédito/débito con `comprobantes_asociados`
Las notas (ARCA tipos 2-3, 7-8, 12-13) referencian comprobantes originales a través de `CbtesAsoc` en WSFEv1. El modelo exige:
- `comprobantes_asociados` es obligatorio en notas, prohibido en facturas.
- La clase de la nota (A/B/C) debe coincider con la del comprobante asociado.
- Numeración, idempotencia, estado `incierto` funcionan igual que en facturas (son comprobantes, con tipos separados).
- Axis usa notas de crédito para cancelaciones: "factura emitida + nota crédito (100%) = nulo fiscal".
