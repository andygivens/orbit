"""Lightweight adapter registry (lean phase).

Currently supports auto-registration of the built-in 'minimal' adapter.
Future expansion: dynamic discovery, entry points, version gating.
"""
from __future__ import annotations

import hashlib
import json
from importlib import import_module
from typing import Any

from sqlalchemy.orm import Session

from ..domain.models import ProviderType


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def load_adapter_by_type(type_id: str):
    """Return adapter instance for supported internal types or raise ImportError.

    For now only 'minimal' is supported via adapters.minimal.adapter:MinimalProvider.
    """
    if type_id == "minimal":
        mod = import_module("adapters.minimal.adapter")
        return getattr(mod, "MinimalProvider")()
    raise ImportError(f"No dynamic adapter loader for type_id '{type_id}'")


def register_adapter_if_missing(db: Session, type_id: str):
    """Idempotently register adapter metadata when provider_type row missing.

    Safe to call on every create/update path for lean phase.
    """
    existing = db.query(ProviderType).filter(ProviderType.id == type_id).first()
    if existing:
        return existing
    try:
        adapter = load_adapter_by_type(type_id)
    except ImportError:
        return None  # silently ignore for unknown types; upstream logic will raise

    schema = adapter.config_schema()
    caps = list(adapter.capabilities())
    schema_hash = hashlib.sha256(_canonical_json(schema).encode()).hexdigest()
    provider_type = ProviderType(
        id=adapter.type_id,
        label=adapter.type_id.replace("_", " ").title(),
        description=f"Auto-registered adapter '{adapter.type_id}'",
        config_schema=schema,
        capabilities=caps,
        adapter_locator="adapters.minimal.adapter:MinimalProvider" if type_id == "minimal" else None,
        adapter_version=getattr(adapter, "version", "0.1.0"),
        config_schema_hash=schema_hash,
    )
    db.add(provider_type)
    db.flush()  # ensure PK assigned
    return provider_type
