"""Utility to load sync definitions from the database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from ..core.settings import settings
from ..domain.models import Provider, Sync


@dataclass
class SyncEndpointDefinition:
    id: str
    provider_id: str
    role: str
    provider_type: str
    enabled: bool
    config: dict
    provider_name: str
    provider_status: Optional[str]
    provider_status_detail: Optional[str]
    provider_type_label: Optional[str]


@dataclass
class SyncDefinition:
    id: str
    name: str
    direction: str
    interval_seconds: int
    enabled: bool
    window_days_past: int
    window_days_future: int
    endpoints: List[SyncEndpointDefinition]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SyncDefinitionService:
    def __init__(self, db: Session):
        self.db = db

    def list_syncs(self) -> List[SyncDefinition]:
        syncs = (
            self.db.query(Sync)
            .all()
        )
        definitions: List[SyncDefinition] = []
        for sync in syncs:
            endpoints = []
            for endpoint in sync.endpoints:
                provider: Provider = endpoint.provider
                endpoints.append(
                    SyncEndpointDefinition(
                        id=endpoint.id,
                        provider_id=provider.id,
                        role=endpoint.role.value,
                        provider_type=provider.type_id,
                        enabled=provider.enabled,
                        config=provider.config or {},
                        provider_name=provider.name,
                        provider_status=provider.status.value if provider.status else None,
                        provider_status_detail=provider.status_detail,
                        provider_type_label=provider.type_rel.label if provider.type_rel else None,
                    )
                )
            definitions.append(
                SyncDefinition(
                    id=sync.id,
                    name=sync.name,
                    direction=sync.direction.value,
                    interval_seconds=sync.interval_seconds,
                    enabled=sync.enabled,
                    window_days_past=sync.window_days_past or settings.sync_window_days_past,
                    window_days_future=sync.window_days_future or settings.sync_window_days_future,
                    endpoints=endpoints,
                    created_at=sync.created_at,
                    updated_at=sync.updated_at,
                )
            )
        return definitions

    def get_sync(self, sync_id: str) -> Optional[SyncDefinition]:
        sync = self.db.query(Sync).filter(Sync.id == sync_id).first()
        if not sync:
            return None

        endpoints = []
        for endpoint in sync.endpoints:
            provider: Provider = endpoint.provider
            endpoints.append(
                SyncEndpointDefinition(
                    id=endpoint.id,
                    provider_id=provider.id,
                    role=endpoint.role.value,
                    provider_type=provider.type_id,
                    enabled=provider.enabled,
                    config=provider.config or {},
                    provider_name=provider.name,
                    provider_status=provider.status.value if provider.status else None,
                    provider_status_detail=provider.status_detail,
                    provider_type_label=provider.type_rel.label if provider.type_rel else None,
                )
            )

        return SyncDefinition(
            id=sync.id,
            name=sync.name,
            direction=sync.direction.value,
            interval_seconds=sync.interval_seconds,
            enabled=sync.enabled,
            window_days_past=sync.window_days_past or settings.sync_window_days_past,
            window_days_future=sync.window_days_future or settings.sync_window_days_future,
            endpoints=endpoints,
            created_at=sync.created_at,
            updated_at=sync.updated_at,
        )
