# arca-mcp

Servidor MCP multi-emisor para facturación electrónica con ARCA (ex AFIP), en Python.

Es **agnóstico de los sistemas que lo usan**: no sabe nada de Axis, Pulpix ni NexCourt. Recibe
comprobantes con importes ya calculados, valida su consistencia fiscal, numera, pide el CAE y
devuelve el resultado.

## Arquitectura

```
src/arca_mcp/
├── core/                 # dominio puro: modelos, validación, casos de uso, puertos
├── adapters/
│   ├── arca/             # WSAA (firma CMS + cache de TA) y WSFEv1 por SOAP (zeep)
│   └── persistence/      # SQLite: previews, comprobantes emitidos, tickets WSAA
├── interfaces/           # servidor MCP (streamable HTTP) + auth por API key
├── config.py
└── main.py
```

## Tools expuestas

| Tool | Qué hace |
|---|---|
| `list_issuers` | Emisores habilitados para el sistema que llama |
| `preview_invoice` | Valida y genera un preview. No emite nada |
| `emit_invoice` | Emite un preview confirmado y obtiene el CAE |
| `get_invoice` | Consulta un comprobante en ARCA (sirve para reconciliar) |
| `get_last_invoice_number` | Último número autorizado por tipo y punto de venta |
| `list_receiver_vat_conditions` | Condiciones IVA del receptor válidas (RG 5616) |

## Garantías

- **Preview obligatorio**: `emit_invoice` solo acepta un `preview_id` vigente, del mismo sistema, y usable una sola vez.
- **Idempotencia**: una `referencia` (sistema + id de la operación) se factura una sola vez por emisor.
- **Numeración serializada** por CUIT, punto de venta y tipo.
- **Estado incierto explícito**: si ARCA no responde después de enviar, el preview queda `incierto` y hay que verificar con `get_invoice` antes de reintentar.
- **Aislamiento por sistema**: cada API key solo ve sus emisores.

## Puesta en marcha en homologación

1. Generá clave privada y CSR (reemplazá el CUIT):

   ```bash
   openssl genrsa -out certs/gon-personal.key 2048
   openssl req -new -key certs/gon-personal.key \
     -subj "/C=AR/O=Gonzalo/CN=arcamcphomo/serialNumber=CUIT 20XXXXXXXXX" \
     -out certs/gon-personal.csr
   ```

2. En ARCA, con clave fiscal, adherí **WSASS – Autogestión Certificados Homologación** desde
   *Administrador de Relaciones de Clave Fiscal → Adherir servicio → ARCA → Servicios Interactivos*
   (no "WebServices"). Después, dentro de WSASS:
   - **Nuevo certificado**: el nombre simbólico del DN solo admite letras y números (usá el mismo
     valor que el `CN` del CSR, ej. `arcamcphomo`). Guardá el certificado devuelto en `certs/gon-personal.crt`.
   - **Crear autorización a servicio**: ese alias, tu CUIT como representado y el servicio `wsfe`.
     Sin este paso WSAA responde "Computador no autorizado a acceder al servicio".
3. Copiá `config/emisores.example.yaml` a `config/emisores.yaml` y completá CUIT, punto de venta y rutas.
   Para correr fuera de Docker usá rutas locales (`certs/...`, `db_path: data/arca.db`).
4. Copiá `.env.example` a `.env` y generá las keys con `openssl rand -hex 32`.
5. Local: `pip install -e ".[dev]"`, cargá el `.env` (el servidor no lo lee solo) y levantalo:

   ```bash
   set -a; source .env; set +a
   ARCA_CONFIG=config/emisores.yaml LOG_LEVEL=DEBUG arca-mcp   # DEBUG muestra el SOAP con ARCA
   ```

6. Probá desde otra terminal con `curl` (el transporte es stateless, no hace falta `initialize`):

   ```bash
   curl -s http://127.0.0.1:8000/mcp -H "Authorization: Bearer $ARCA_API_KEY_PERSONAL" \
     -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_last_invoice_number","arguments":{"emisor_id":"gon-personal","tipo":"factura_c","punto_venta":1}}}' | jq
   ```

   Los comprobantes emitidos en homologación no aparecen en las pantallas web de ARCA:
   se verifican con `get_invoice`.

## Despliegue en el droplet

Agregá el bloque de `deploy/compose.arca.yml` al `docker-compose.yml` donde ya corren el backend y
el frontend de Axis. **No publica puertos**: solo es accesible por la red interna de Docker en
`http://arca-mcp:8000/mcp`. Los certificados se montan solo lectura y la base en un volumen.

```bash
chmod 640 arca/certs/*.key   # legible por el usuario del contenedor (uid 10001)
docker compose up -d --build arca-mcp
docker compose exec arca-mcp python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health').read())"
```

## Tests

```bash
pytest
```

Los tests usan un gateway falso y no tocan ARCA.

## Pendiente (siguientes fases)

- Notas de crédito/débito (comprobantes asociados) y tributos.
- Moneda extranjera (cotización y `CanMisMonExt`).
- Postgres + advisory locks para correr varias réplicas.
- Generación de PDF con QR fiscal.
- Modelo de delegación (un certificado de proveedor representando muchos CUITs): ya funciona apuntando varios emisores al mismo certificado; falta el onboarding.
