"""CRUD operations for sync definitions."""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..core.logging import logger
from ..core.settings import settings
from ..domain.models import (
    Provider,
    Sync,
    SyncDirectionEnum,
    SyncEndpoint,
    SyncEndpointRoleEnum,
)
from .sync_definition_service import SyncDefinition, SyncDefinitionService


class SyncCrudError(Exception):
    pass


class SyncNotFoundError(SyncCrudError):
    pass


class SyncValidationError(SyncCrudError):
    pass


class SyncCrudService:
    def __init__(self, db: Session):
        self.db = db
        self.log = logger.bind(component="sync_crud")
        self.definition_service = SyncDefinitionService(db)

    def list_syncs(self) -> List[SyncDefinition]:
        return self.definition_service.list_syncs()

    def get_sync(self, sync_id: str) -> SyncDefinition:
        definition = self.definition_service.get_sync(sync_id)
        if not definition:
            raise SyncNotFoundError(f"Sync '{sync_id}' not found")
        return definition

    def create_sync(
        self,
        *,
        name: str,
        direction: str,
        interval_seconds: int,
        enabled: bool,
        endpoints: List[Dict[str, str]],
        window_days_past: Optional[int] = None,
        window_days_future: Optional[int] = None,
    ) -> SyncDefinition:
        if not endpoints:
            raise SyncValidationError("At least one endpoint is required")

        try:
            direction_enum = SyncDirectionEnum(direction)
        except ValueError as exc:
            raise SyncValidationError(str(exc))

        sync = Sync(
            name=name,
            direction=direction_enum,
            interval_seconds=max(30, interval_seconds),
            enabled=enabled,
            window_days_past=window_days_past if window_days_past is not None else settings.sync_window_days_past,
            window_days_future=window_days_future if window_days_future is not None else settings.sync_window_days_future,
        )
        self.db.add(sync)
        self.db.flush()

        self._replace_endpoints(sync, endpoints)

        self.db.flush()
        self.db.commit()
        self.log.info("Created sync", sync_id=sync.id)
        return self.get_sync(sync.id)

    def update_sync(
        self,
        sync_id: str,
        *,
        name: Optional[str] = None,
        direction: Optional[str] = None,
        interval_seconds: Optional[int] = None,
        enabled: Optional[bool] = None,
        endpoints: Optional[List[Dict[str, str]]] = None,
        window_days_past: Optional[int] = None,
        window_days_future: Optional[int] = None,
    ) -> SyncDefinition:
        sync = self.db.query(Sync).filter(Sync.id == sync_id).first()
        if not sync:
            raise SyncNotFoundError(f"Sync '{sync_id}' not found")

        if name is not None:
            sync.name = name
        if direction is not None:
            try:
                sync.direction = SyncDirectionEnum(direction)
            except ValueError as exc:
                raise SyncValidationError(str(exc))
        if interval_seconds is not None:
            sync.interval_seconds = max(30, interval_seconds)
        if enabled is not None:
            sync.enabled = enabled
        if window_days_past is not None:
            sync.window_days_past = max(0, window_days_past)
        if window_days_future is not None:
            sync.window_days_future = max(0, window_days_future)

        if endpoints is not None:
            if not endpoints:
                raise SyncValidationError("At least one endpoint is required")
            self._replace_endpoints(sync, endpoints)

        self.db.flush()
        self.db.commit()
        self.log.info("Updated sync", sync_id=sync_id)
        return self.get_sync(sync_id)

    def delete_sync(self, sync_id: str) -> None:
        sync = self.db.query(Sync).filter(Sync.id == sync_id).first()
        if not sync:
            raise SyncNotFoundError(f"Sync '{sync_id}' not found")

        self.db.delete(sync)
        self.db.flush()
        self.db.commit()
        self.log.info("Deleted sync", sync_id=sync_id)

    # ------------------------------------------------------------------

    def _replace_endpoints(self, sync: Sync, endpoints: List[Dict[str, str]]) -> None:
        sync.endpoints.clear()
        seen_providers = set()

        for endpoint in endpoints:
            provider_id = endpoint.get("provider_id")
            role = endpoint.get("role", SyncEndpointRoleEnum.PRIMARY.value)

            if not provider_id:
                raise SyncValidationError("Endpoint provider_id is required")

            provider = self.db.query(Provider).filter(Provider.id == provider_id).first()
            if not provider:
                raise SyncValidationError(f"Provider '{provider_id}' not found")

            if provider_id in seen_providers:
                raise SyncValidationError(f"Provider '{provider_id}' already added to sync")
            seen_providers.add(provider_id)

            try:
                role_enum = SyncEndpointRoleEnum(role)
            except ValueError as exc:
                raise SyncValidationError(str(exc))

            sync.endpoints.append(
                SyncEndpoint(
                    sync=sync,
                    provider=provider,
                    role=role_enum,
                )
            )
