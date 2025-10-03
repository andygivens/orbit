from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import Base, ProviderTypeEnum, SyncRun
from app.providers.base import ProviderAdapter
from app.providers.registry import ProviderRegistry
from app.services.sync_definition_service import SyncDefinition, SyncEndpointDefinition
from app.services.sync_service import SyncService


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory_local = sessionmaker(bind=engine)

    @contextmanager
    def factory():
        session = session_factory_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return factory


class MockSourceAdapter(ProviderAdapter):
    def __init__(self, provider_id: str, config: dict):
        super().__init__(provider_id, config)
        self.events = config.get("events", [])

    async def initialize(self) -> None:  # pragma: no cover - trivial
        return

    async def list_events(self, start: str, end: str):
        return list(self.events)

    # pragma: no cover - not used in unit tests
    async def create_event(self, payload: dict):
        raise NotImplementedError

    # pragma: no cover - not used in unit tests
    async def update_event(self, provider_uid: str, payload: dict):
        raise NotImplementedError

    async def delete_event(self, provider_uid: str):  # pragma: no cover - not used
        return


class MockTargetAdapter(ProviderAdapter):
    def __init__(self, provider_id: str, config: dict, *, fail_on_create: bool = False):
        super().__init__(provider_id, config)
        self.fail_on_create = fail_on_create
        self.created_payloads: list[dict] = []

    async def initialize(self) -> None:  # pragma: no cover - trivial
        return

    async def list_events(self, start: str, end: str):
        return []

    async def create_event(self, payload: dict):
        if self.fail_on_create:
            raise RuntimeError("Target adapter failure")
        self.created_payloads.append(payload)
        # Mimic CalDAV response signature
        return {
            "uid": f"uid-{len(self.created_payloads)}",
            "etag": "etag",
        }

    async def update_event(  # pragma: no cover - not used
        self,
        provider_uid: str,
        payload: dict,
    ) -> dict:
        return {
            "uid": provider_uid,
            "etag": "etag",
        }

    async def delete_event(self, provider_uid: str):  # pragma: no cover - not used
        return


@pytest.mark.asyncio
async def test_run_sync_one_way_success():
    session_factory = _make_session_factory()

    # Prepare mock adapters
    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=1)
    source_events = [
        {
            "id": "evt-1",
            "attributes": {
                "summary": "Team sync",
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
                "timezone": "UTC",
                "location": "Conference Room",
                "description": "Agenda",
            },
        }
    ]

    registry = ProviderRegistry(factories={})
    registry.register(
        ProviderTypeEnum.SKYLIGHT.value,
        lambda provider_id, config: MockSourceAdapter(provider_id, config),
    )
    target_adapter = MockTargetAdapter("target", {})
    registry.register(
        ProviderTypeEnum.APPLE_CALDAV.value,
        lambda provider_id, config: target_adapter,
    )

    sync_service = SyncService(session_factory=session_factory, registry=registry)

    definition = SyncDefinition(
        id="sync_test",
        name="Test Sync",
        direction="one_way",
        interval_seconds=300,
        enabled=True,
        window_days_past=3,
        window_days_future=3,
        endpoints=[
            SyncEndpointDefinition(
                id="ep_source",
                provider_id="source",
                role="primary",
                provider_type=ProviderTypeEnum.SKYLIGHT.value,
                enabled=True,
                config={"events": source_events},
                provider_name="Skylight",
                provider_status=None,
                provider_status_detail=None,
                provider_type_label="Skylight",
            ),
            SyncEndpointDefinition(
                id="ep_target",
                provider_id="target",
                role="secondary",
                provider_type=ProviderTypeEnum.APPLE_CALDAV.value,
                enabled=True,
                config={},
                provider_name="Apple",
                provider_status=None,
                provider_status_detail=None,
                provider_type_label="Apple",
            ),
        ],
    )

    result = await sync_service.run_sync(definition)

    assert result["status"] == "success"
    assert target_adapter.created_payloads, (
        "Expected target adapter to receive create payload"
    )

    # Ensure a sync run record was created
    with session_factory() as session:
        runs = session.query(SyncRun).filter(SyncRun.sync_id == definition.id).all()
        assert len(runs) == 1
        assert runs[0].status == "success"
        assert runs[0].events_processed == 1


@pytest.mark.asyncio
async def test_run_sync_records_errors_when_target_fails():
    session_factory = _make_session_factory()

    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=1)
    source_events = [
        {
            "id": "evt-2",
            "attributes": {
                "summary": "Planning",
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
                "timezone": "UTC",
            },
        }
    ]

    registry = ProviderRegistry(factories={})
    registry.register(
        ProviderTypeEnum.SKYLIGHT.value,
        lambda provider_id, config: MockSourceAdapter(provider_id, config),
    )
    failing_target = MockTargetAdapter("target", {}, fail_on_create=True)
    registry.register(
        ProviderTypeEnum.APPLE_CALDAV.value,
        lambda provider_id, config: failing_target,
    )

    sync_service = SyncService(session_factory=session_factory, registry=registry)

    definition = SyncDefinition(
        id="sync_failure",
        name="Failing Sync",
        direction="one_way",
        interval_seconds=300,
        enabled=True,
        window_days_past=3,
        window_days_future=3,
        endpoints=[
            SyncEndpointDefinition(
                id="ep_source",
                provider_id="source",
                role="primary",
                provider_type=ProviderTypeEnum.SKYLIGHT.value,
                enabled=True,
                config={"events": source_events},
                provider_name="Skylight",
                provider_status=None,
                provider_status_detail=None,
                provider_type_label="Skylight",
            ),
            SyncEndpointDefinition(
                id="ep_target",
                provider_id="target",
                role="secondary",
                provider_type=ProviderTypeEnum.APPLE_CALDAV.value,
                enabled=True,
                config={},
                provider_name="Apple",
                provider_status=None,
                provider_status_detail=None,
                provider_type_label="Apple",
            ),
        ],
    )

    result = await sync_service.run_sync(definition)

    assert result["status"] == "warning"
    first_run = result["runs"][0]
    assert first_run["stats"]["errors"] >= 1

    with session_factory() as session:
        run = session.query(SyncRun).filter(SyncRun.sync_id == definition.id).first()
        assert run is not None
        assert run.status == "warning"
        assert run.errors >= 1
