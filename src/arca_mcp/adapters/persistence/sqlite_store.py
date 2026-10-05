"""Persistencia en SQLite (fase 1). Implementa ComprobanteStore y TokenCache.
Migrar a Postgres implica solo reescribir este adaptador."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from ...core.models import EstadoPreview, Preview, ReferenciaExterna, ResultadoEmision
from ..arca.wsaa import Ticket

ESQUEMA = """
CREATE TABLE IF NOT EXISTS previews (
    preview_id TEXT PRIMARY KEY,
    cliente    TEXT NOT NULL,
    emisor_id  TEXT NOT NULL,
    estado     TEXT NOT NULL,
    datos      TEXT NOT NULL,
    creado     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comprobantes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    preview_id   TEXT NOT NULL,
    emisor_id    TEXT NOT NULL,
    tipo         TEXT NOT NULL,
    punto_venta  INTEGER NOT NULL,
    numero       INTEGER,
    cae          TEXT,
    estado       TEXT NOT NULL,
    ref_sistema  TEXT NOT NULL,
    ref_id       TEXT NOT NULL,
    datos        TEXT NOT NULL,
    creado       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_aprobado_por_referencia
    ON comprobantes (emisor_id, ref_sistema, ref_id) WHERE estado = 'aprobado';
CREATE TABLE IF NOT EXISTS tokens (
    clave  TEXT PRIMARY KEY,
    token  TEXT NOT NULL,
    sign   TEXT NOT NULL,
    expira TEXT NOT NULL
);
"""


class SqliteStore:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(ESQUEMA)
        self._lock = threading.Lock()

    # ---- previews ----
    def guardar_preview(self, p: Preview) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO previews (preview_id, cliente, emisor_id, estado, datos, creado) VALUES (?,?,?,?,?,?)",
                (p.preview_id, p.cliente, p.emisor_id, p.estado.value, p.model_dump_json(), p.creado.isoformat()),
            )

    def obtener_preview(self, preview_id: str) -> Preview | None:
        with self._lock:
            fila = self._conn.execute(
                "SELECT datos, estado FROM previews WHERE preview_id = ?", (preview_id,)
            ).fetchone()
        if not fila:
            return None
        return Preview.model_validate_json(fila[0]).model_copy(update={"estado": EstadoPreview(fila[1])})

    def reclamar_preview(self, preview_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE previews SET estado = ? WHERE preview_id = ? AND estado = ?",
                (EstadoPreview.EN_PROCESO.value, preview_id, EstadoPreview.PENDIENTE.value),
            )
            return cur.rowcount == 1

    def actualizar_estado_preview(self, preview_id: str, estado: EstadoPreview) -> None:
        with self._lock:
            self._conn.execute("UPDATE previews SET estado = ? WHERE preview_id = ?", (estado.value, preview_id))

    # ---- comprobantes ----
    def buscar_aprobado(self, emisor_id: str, ref: ReferenciaExterna) -> ResultadoEmision | None:
        with self._lock:
            fila = self._conn.execute(
                "SELECT datos FROM comprobantes WHERE emisor_id=? AND ref_sistema=? AND ref_id=? AND estado='aprobado'",
                (emisor_id, ref.sistema, ref.id),
            ).fetchone()
        return ResultadoEmision.model_validate_json(fila[0]) if fila else None

    def guardar_resultado(self, preview_id: str, r: ResultadoEmision) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO comprobantes (preview_id, emisor_id, tipo, punto_venta, numero, cae, estado,"
                " ref_sistema, ref_id, datos, creado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (preview_id, r.emisor_id, r.tipo.value, r.punto_venta, r.numero, r.cae, r.estado,
                 r.referencia.sistema, r.referencia.id, r.model_dump_json(), datetime.now().isoformat()),
            )

    # ---- TokenCache ----
    def obtener_token(self, clave: str) -> Ticket | None:
        with self._lock:
            fila = self._conn.execute("SELECT token, sign, expira FROM tokens WHERE clave = ?", (clave,)).fetchone()
        return Ticket(fila[0], fila[1], datetime.fromisoformat(fila[2])) if fila else None

    def guardar_token(self, clave: str, t: Ticket) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO tokens (clave, token, sign, expira) VALUES (?,?,?,?) "
                "ON CONFLICT(clave) DO UPDATE SET token=excluded.token, sign=excluded.sign, expira=excluded.expira",
                (clave, t.token, t.sign, t.expira.isoformat()),
            )
