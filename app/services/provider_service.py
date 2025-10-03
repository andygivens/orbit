"""Service layer for provider CRUD and type management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from sqlalchemy.orm import Session, joinedload

from ..core.logging import logger
from ..domain.models import (
    Provider,
    ProviderStatusEnum,
    ProviderType,
    ProviderTypeEnum,
    SyncEndpoint,
    SyncRun,
    serialize_datetime,
)
from ..providers.registry import provider_registry
from .provider_config_validator import ProviderConfigValidator
from .provider_registry import register_adapter_if_missing


class ProviderServiceError(Exception):
    """Domain-specific errors for provider operations."""


class ProviderNotFoundError(ProviderServiceError):
    pass


class ProviderTypeNotFoundError(ProviderServiceError):
    pass


class ProviderValidationError(ProviderServiceError):
    pass


class ProviderService:
    """Service encapsulating provider CRUD and schema-aware validation."""

    def __init__(self, db: Session):
        self.db = db
        self.log = logger.bind(component="provider_service")

    # ------------------------------------------------------------------
    # Provider type helpers

    @staticmethod
    def _schema_fields(schema: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize provider config schema into a list of field descriptors."""

        if not isinstance(schema, dict):
            return []

        raw_fields = schema.get("fields")
        if isinstance(raw_fields, list) and raw_fields:
            normalized: List[Dict[str, Any]] = []
            for item in raw_fields:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if not isinstance(name, str) or not name:
                    continue
                required_flag = item.get("required")
                if required_flag is None:
                    required_flag = not bool(item.get("optional", False))
                normalized.append(
                    {
                        "name": name,
                        "type": item.get("type", "string"),
                        "secret": bool(item.get("secret")),
                        "required": bool(required_flag),
                        "optional": not bool(required_flag),
                        "label": item.get("label"),
                    }
                )
            if normalized:
                return normalized

        properties = schema.get("properties")
        if isinstance(properties, dict) and properties:
            required_raw = schema.get("required")
            required: Set[str] = set()
            if isinstance(required_raw, list):
                required = {name for name in required_raw if isinstance(name, str)}

            normalized = []
            for name, definition in properties.items():
                if not isinstance(name, str) or not isinstance(definition, dict):
                    continue
                raw_type = definition.get("type")
                if isinstance(raw_type, list):
                    primary_type = next(
                        (t for t in raw_type if isinstance(t, str) and t != "null"),
                        raw_type[0] if raw_type else "string",
                    )
                elif isinstance(raw_type, str):
                    primary_type = raw_type
                else:
                    primary_type = "string"

                secret = bool(
                    definition.get("secret")
                    or definition.get("writeOnly")
                    or definition.get("x-secret")
                    or definition.get("x_secret")
                )

                is_required = name in required
                normalized.append(
                    {
                        "name": name,
                        "type": primary_type,
                        "secret": secret,
                        "required": is_required,
                        "optional": not is_required,
                        "label": definition.get("title"),
                    }
                )
            return normalized

        return []

    def list_provider_types(self) -> List[dict]:
        types = (
            self.db.query(ProviderType)
            .order_by(ProviderType.label.asc())
            .all()
        )
        return [provider_type.to_dict() for provider_type in types]

    def get_provider_type(self, type_id: str) -> ProviderType:
        provider_type = self.db.query(ProviderType).filter(ProviderType.id == type_id).first()
        if not provider_type:
            raise ProviderTypeNotFoundError(f"Provider type '{type_id}' not found")
        return provider_type

    # ------------------------------------------------------------------
    # Provider CRUD

    def list_providers(self) -> List[dict]:
        providers = (
            self.db.query(Provider)
            .options(
                joinedload(Provider.sync_endpoints).joinedload(SyncEndpoint.sync)
            )
            .order_by(Provider.created_at.asc())
            .all()
        )
        return [self._serialize_provider(provider) for provider in providers]

    def get_provider(self, provider_id: str) -> dict:
        provider = (
            self.db.query(Provider)
            .options(
                joinedload(Provider.sync_endpoints).joinedload(SyncEndpoint.sync)
            )
            .filter(Provider.id == provider_id)
            .first()
        )
        if not provider:
            raise ProviderNotFoundError(f"Provider '{provider_id}' not found")
        return self._serialize_provider(provider)

    def create_provider(
        self,
        *,
        type_id: str,
        name: str,
        config: Dict[str, Any],
        enabled: bool = True,
    ) -> dict:
        # Auto-register adapter-backed provider types (lean path)
        provider_type = self.db.query(ProviderType).filter(ProviderType.id == type_id).first()
        if not provider_type:
            register_adapter_if_missing(self.db, type_id)
            provider_type = self.db.query(ProviderType).filter(ProviderType.id == type_id).first()
        if not provider_type:
            raise ProviderTypeNotFoundError(f"Provider type '{type_id}' not found")
        # Legacy validation retained until full secret refactor; Phase 2 validation adds fingerprint
        prepared_config = self._validate_and_prepare_config(provider_type, config)
        validator = ProviderConfigValidator(self.db)
        try:
            vr = validator.validate(type_id, prepared_config)
        except ValueError as e:
            raise ProviderValidationError(str(e))

        provider = Provider(
            type=provider_type.id,  # retained enum usage
            name=name,
            config=vr.sanitized_config,
            enabled=enabled,
            status=ProviderStatusEnum.UNKNOWN,
            config_schema_version=vr.schema_version,
            config_fingerprint=vr.fingerprint,
        )
        self.db.add(provider)
        self.db.flush()
        self.log.info("Created provider", provider_id=provider.id, type=provider_type.id)
        return self._serialize_provider(provider)

    def update_provider(
        self,
        provider_id: str,
        *,
        name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        enabled: Optional[bool] = None,
        status: Optional[ProviderStatusEnum] = None,
        status_detail: Optional[str] = None,
    ) -> dict:
        provider = self._get_provider_model(provider_id)
        provider_type = self.get_provider_type(provider.type_id)

        if name is not None:
            provider.name = name
        if enabled is not None:
            provider.enabled = enabled
        if status is not None:
            provider.status = status
        if status_detail is not None:
            provider.status_detail = status_detail

        if config is not None:
            prepared_config = self._validate_and_prepare_config(
                provider_type,
                config,
                existing_config=provider.config,
            )
            validator = ProviderConfigValidator(self.db)
            try:
                vr = validator.validate(provider.type_id, prepared_config)
            except ValueError as e:
                raise ProviderValidationError(str(e))
            provider.config = vr.sanitized_config
            provider.config_schema_version = vr.schema_version
            provider.config_fingerprint = vr.fingerprint

        self.db.add(provider)
        self.db.flush()
        self.log.info("Updated provider", provider_id=provider_id)
        return self._serialize_provider(provider)

    async def test_provider_connection(self, provider_id: str) -> dict:
        provider = self._get_provider_model(provider_id)

        status_enum = ProviderStatusEnum.DEGRADED
        detail: Optional[str] = None
        checked_at = datetime.now(timezone.utc)
        adapter = None

        try:
            adapter = provider_registry.create(
                provider.type_id,
                provider.id,
                provider.config or {},
            )
        except Exception as exc:
            status_enum = ProviderStatusEnum.ERROR
            detail = f"Adapter load failed: {exc}"
            self.log.warning(
                "Failed to create adapter during provider test",
                provider_id=provider_id,
                error=str(exc),
            )
        else:
            try:
                await adapter.initialize()
            except Exception as exc:  # pragma: no cover - adapter runtime failures
                status_enum = ProviderStatusEnum.ERROR
                detail = self._format_connection_error(exc)
                self.log.warning(
                    "Provider connection test failed",
                    provider_id=provider_id,
                    error=str(exc),
                    detail=detail,
                )
            else:
                status_enum = ProviderStatusEnum.ACTIVE
                detail = "Connection verified successfully"
            finally:
                if adapter is not None:
                    try:
                        await adapter.close()
                    except Exception:  # pragma: no cover - best effort cleanup
                        pass

        provider.status = status_enum
        provider.status_detail = detail
        provider.last_checked_at = checked_at

        self.db.add(provider)
        self.db.flush()

        self.log.info(
            "Provider connection test completed",
            provider_id=provider_id,
            status=status_enum.value,
        )

        return self._serialize_provider(provider)

    def delete_provider(self, provider_id: str) -> None:
        provider = self._get_provider_model(provider_id)
        self.db.delete(provider)
        self.db.flush()
        self.log.info("Deleted provider", provider_id=provider_id)

    # ------------------------------------------------------------------
    # Internal helpers

    @staticmethod
    def _format_connection_error(exc: Exception) -> str:
        """Normalize adapter exceptions into an informative status detail."""

        segments: List[str] = []
        seen: Set[int] = set()
        current: Optional[BaseException] = exc
        depth = 0

        # Traverse chained exceptions (cause/context) up to a reasonable depth
        while current and id(current) not in seen and depth < 5:
            seen.add(id(current))

            message: str
            if isinstance(current, httpx.HTTPStatusError):
                status_code = current.response.status_code
                reason = current.response.reason_phrase or current.response.text
                request = getattr(current, "request", None)
                detail = f"HTTP {status_code} {reason}".strip()
                if request is not None:
                    detail = f"{detail} while calling {request.method} {request.url}".strip()
                message = detail
            elif isinstance(current, httpx.RequestError):
                request = getattr(current, "request", None)
                base = str(current).strip()
                if not base:
                    base = current.__class__.__name__
                if request is not None:
                    message = f"{base} during {request.method} {request.url}"
                else:
                    message = base
            else:
                message = str(current).strip()

            if not message:
                message = current.__class__.__name__

            segments.append(message)
            current = current.__cause__ or current.__context__
            depth += 1

        summary = " -> ".join(segments) if segments else type(exc).__name__
        return f"Connection failed: {summary}"

    def _provider_sync_summaries(
        self, provider: Provider
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        summaries: List[Dict[str, Any]] = []
        last_sync_dt: Optional[datetime] = None
        seen_syncs: Set[str] = set()

        for endpoint in provider.sync_endpoints or []:
            sync = endpoint.sync
            if not sync:
                continue
            if sync.id in seen_syncs:
                continue
            seen_syncs.add(sync.id)

            last_run_row = (
                self.db.query(SyncRun)
                .filter(SyncRun.sync_id == sync.id)
                .order_by(SyncRun.started_at.desc())
                .limit(1)
                .first()
            )

            last_run_at: Optional[str] = None
            last_run_status: Optional[str] = None
            if last_run_row:
                if last_run_row.started_at is not None:
                    if last_sync_dt is None or last_run_row.started_at > last_sync_dt:
                        last_sync_dt = last_run_row.started_at
                last_run_at_dt = (
                    last_run_row.completed_at or last_run_row.started_at
                )
                last_run_at = serialize_datetime(last_run_at_dt)
                last_run_status = last_run_row.status

            summaries.append(
                {
                    "id": sync.id,
                    "name": sync.name,
                    "direction": sync.direction.value if sync.direction else None,
                    "enabled": sync.enabled,
                    "role": endpoint.role.value if endpoint.role else None,
                    "last_run_status": last_run_status,
                    "last_run_at": last_run_at,
                }
            )

        return summaries, serialize_datetime(last_sync_dt)

    def _get_provider_model(self, provider_id: str) -> Provider:
        provider = self.db.query(Provider).filter(Provider.id == provider_id).first()
        if not provider:
            raise ProviderNotFoundError(f"Provider '{provider_id}' not found")
        return provider

    def _serialize_provider(self, provider: Provider) -> dict:
        provider_type = self.get_provider_type(provider.type_id)
        schema_fields = self._schema_fields(provider_type.config_schema)
        secret_fields = {field["name"] for field in schema_fields if field.get("secret")}
        config_copy: Dict[str, Any] = {}
        for key, value in (provider.config or {}).items():
            if key in secret_fields and value is not None:
                config_copy[key] = "********"
            else:
                config_copy[key] = value

        payload = provider.to_dict(include_config=False)
        payload["type_id"] = provider.type_id
        payload["status"] = self._map_status(provider)
        payload["config"] = config_copy
        sync_summaries, last_sync_at = self._provider_sync_summaries(provider)
        payload["syncs"] = sync_summaries
        payload["last_sync_at"] = last_sync_at

        if provider.type_id == ProviderTypeEnum.APPLE_CALDAV.value:
            payload["config"].pop("caldav_url", None)

        return payload

    def _map_status(self, provider: Provider) -> str:
        if not provider.enabled:
            return "disabled"

        status = provider.status or ProviderStatusEnum.UNKNOWN
        mapping = {
            ProviderStatusEnum.ACTIVE: "active",
            ProviderStatusEnum.DEGRADED: "degraded",
            ProviderStatusEnum.ERROR: "error",
            ProviderStatusEnum.UNKNOWN: "degraded",
        }
        return mapping.get(status, "degraded")

    def _validate_and_prepare_config(
        self,
        provider_type: ProviderType,
        config: Dict[str, Any],
        *,
        existing_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        schema_fields = self._schema_fields(provider_type.config_schema)
        required_fields = {
            field["name"]
            for field in schema_fields
            if field.get("required", True)
        }
        secret_fields = {
            field["name"]
            for field in schema_fields
            if field.get("secret")
        }
        allowed_fields = {field["name"] for field in schema_fields}

        prepared: Dict[str, Any] = dict(existing_config or {})

        if provider_type.id == ProviderTypeEnum.APPLE_CALDAV.value:
            prepared.pop("caldav_url", None)

        if allowed_fields:
            prepared = {
                key: value
                for key, value in prepared.items()
                if key in allowed_fields
            }

        if allowed_fields:
            for key in config:
                if key not in allowed_fields:
                    raise ProviderValidationError(
                        f"Unknown configuration field '{key}' for provider type {provider_type.id}"
                    )
        elif config:
            raise ProviderValidationError(
                f"Provider type {provider_type.id} does not define editable configuration fields"
            )

        for field_name in required_fields:
            if (field_name not in prepared or prepared[field_name] in (None, "")) and (
                field_name not in config or config.get(field_name) in (None, "")
            ):
                raise ProviderValidationError(
                    f"Configuration field '{field_name}' is required for provider type {provider_type.id}"
                )

        for key, value in config.items():
            if value == "********" and existing_config and key in secret_fields:
                continue  # keep existing secret value
            prepared[key] = value

        return prepared
