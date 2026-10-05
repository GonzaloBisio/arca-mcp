from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from .core.models import Cliente, Emisor


class ClienteConfig(BaseModel):
    nombre: str
    api_key_env: str
    emisores: list[str]


class Settings(BaseModel):
    ambiente: Literal["homologacion", "produccion"] = "homologacion"
    db_path: Path = Path("/data/arca.db")
    preview_ttl_minutos: int = 15
    legacy_tls: bool = True
    timeout_segundos: int = 30
    emisores: list[Emisor]
    clientes: list[ClienteConfig]


def load_settings(path: str | Path) -> Settings:
    return Settings.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def resolver_clientes(settings: Settings) -> dict[str, Cliente]:
    """Devuelve {api_key: Cliente}. Falla al arrancar si falta una key o un emisor."""
    ids = {e.id for e in settings.emisores}
    clientes: dict[str, Cliente] = {}
    for c in settings.clientes:
        desconocidos = set(c.emisores) - ids
        if desconocidos:
            raise ValueError(f"Cliente '{c.nombre}' referencia emisores inexistentes: {desconocidos}")
        key = os.environ.get(c.api_key_env, "")
        if len(key) < 32:
            raise ValueError(f"Falta {c.api_key_env} o tiene menos de 32 caracteres (usá: openssl rand -hex 32)")
        clientes[key] = Cliente(nombre=c.nombre, emisores=frozenset(c.emisores))
    return clientes
