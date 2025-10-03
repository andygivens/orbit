"""Provider configuration validation and fingerprinting (Phase 2)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict

from jsonschema import Draft202012Validator, ValidationError
from sqlalchemy.orm import Session

from ..domain.models import ProviderType


@dataclass
class ValidationResult:
    sanitized_config: Dict[str, Any]
    schema_version: str
    fingerprint: str


class ProviderConfigValidator:
    """Validate and sanitize provider configuration against stored JSON Schema.

    Responsibilities:
    - Load provider type schema.
    - Validate provided config (reject unknowns if schema is object with properties/additionalProperties false).
    - Apply defaults (jsonschema validator capability used manually if needed later).
    - Produce stable fingerprint (canonical JSON sorted keys, no whitespace).
    - Return schema_version (current adapter_version or schema hash fallback).
    """

    def __init__(self, db: Session):
        self.db = db

    def validate(self, type_id: str, config: Dict[str, Any]) -> ValidationResult:
        provider_type: ProviderType | None = self.db.query(ProviderType).filter(ProviderType.id == type_id).first()
        if not provider_type:
            raise ValueError(f"Provider type '{type_id}' not found")

        schema = self._build_schema(provider_type)

        try:
            Draft202012Validator(schema).validate(config)
        except ValidationError as e:
            raise ValueError(f"Invalid provider config: {e.message}") from e

        # Canonical JSON => fingerprint
        canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()

        schema_version = provider_type.adapter_version or (provider_type.config_schema_hash or "unknown")
        return ValidationResult(sanitized_config=config, schema_version=schema_version, fingerprint=fingerprint)

    @staticmethod
    def _build_schema(provider_type: ProviderType) -> Dict[str, Any]:
        # Current stored provider_type.config_schema is legacy list format; adapt to basic object schema.
        raw = provider_type.config_schema or {}
        # If already proper JSON Schema (has $schema or properties), pass through.
        if any(k in raw for k in ("$schema", "properties")):
            return raw
        fields = raw.get("fields", [])
        properties: Dict[str, Any] = {}
        required = []
        for field in fields:
            name = field.get("name")
            ftype = field.get("type", "string")
            secret = field.get("secret", False)
            schema_entry: Dict[str, Any] = {"type": "string" if ftype in ("string", "secret") else ftype}
            if secret:
                # Mark writeOnly to signal later secret processing (Phase 3)
                schema_entry["writeOnly"] = True
            properties[name] = schema_entry
            # Legacy assumption: all non-secret fields required except explicit optional future support
            if not field.get("optional", False):
                required.append(name)
        json_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
        return json_schema
