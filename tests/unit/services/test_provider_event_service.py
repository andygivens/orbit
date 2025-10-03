from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import (
    Base,
    Event,
    Provider,
    ProviderMapping,
    ProviderType,
    ProviderTypeEnum,
    Sync,
    SyncDirectionEnum,
    SyncEndpoint,
    SyncEndpointRoleEnum,
)
from app.providers.base import ProviderAdapter
from app.providers.registry import ProviderRegistry
from app.services.provider_event_service import (
    EventNotFoundError,
    ProviderEventService,
)


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


def _seed_sync_environment(session) -> None:
    # Provider types
    apple_type = ProviderType(
        id=ProviderTypeEnum.APPLE_CALDAV.value,
        label="Apple",
        description="Apple CalDAV",
        config_schema={"fields": []},
    )
    skylight_type = ProviderType(
        id=ProviderTypeEnum.SKYLIGHT.value,
        label="Skylight",
        description="Skylight",
        config_schema={"fields": []},
    )
    session.add_all([apple_type, skylight_type])
    session.flush()

    # Providers
    apple_provider = Provider(
        id="prov_apple",
        type=ProviderTypeEnum.APPLE_CALDAV,
        name="Apple",
        config={},
        enabled=True,
    )
    skylight_provider = Provider(
        id="prov_skylight",
        type=ProviderTypeEnum.SKYLIGHT,
        name="Skylight",
        config={},
        enabled=True,
    )
    session.add_all([apple_provider, skylight_provider])
    session.flush()

    # Sync definition referencing both providers
    sync = Sync(
        id="sync_default",
        name="Default",
        direction=SyncDirectionEnum.BIDIRECTIONAL,
        interval_seconds=300,
        enabled=True,
    )
    session.add(sync)
    session.flush()

    session.add_all(
        [
            SyncEndpoint(
                sync_id=sync.id,
                provider_id=apple_provider.id,
                role=SyncEndpointRoleEnum.PRIMARY,
            ),
            SyncEndpoint(
                sync_id=sync.id,
                provider_id=skylight_provider.id,
                role=SyncEndpointRoleEnum.SECONDARY,
            ),
        ]
    )


class AdapterTracker:
    def __init__(self, kind: str, *, category_ids: Optional[List[str]] = None):
        self.kind = kind
        self.category_ids = category_ids or []
        self.instances: List[RecordingAdapter] = []

    def factory(self, provider_id: str, config: dict) -> "RecordingAdapter":
        adapter = RecordingAdapter(provider_id, config, tracker=self)
        self.instances.append(adapter)
        return adapter


class CategoryClient:
    def __init__(self, tracker: AdapterTracker):
        self.tracker = tracker

    async def get_category_ids_by_names(self, names: Sequence[str]) -> List[str]:
        return list(self.tracker.category_ids)


class RecordingAdapter(ProviderAdapter):
    def __init__(self, provider_id: str, config: dict, tracker: AdapterTracker):
        super().__init__(provider_id, config)
        self.tracker = tracker
        self.created_payloads: List[Dict[str, Any]] = []
        self.updated_payloads: List[Tuple[str, Dict[str, Any]]] = []
        self.deleted_uids: List[str] = []
        self.client = CategoryClient(tracker)

    async def initialize(self) -> None:  # pragma: no cover - trivial
        return

    async def list_events(self, start: str, end: str):  # pragma: no cover - not used
        return []

    async def create_event(self, payload: Dict[str, Any]):
        self.created_payloads.append(payload)
        return {
            "uid": f"{self.tracker.kind}-uid",
            "etag": f"{self.tracker.kind}-etag",
        }

    async def update_event(self, provider_uid: str, payload: Dict[str, Any]):
        self.updated_payloads.append((provider_uid, payload))
        return {
            "uid": provider_uid,
            "version": f"{self.tracker.kind}-version",
        }

    async def delete_event(self, provider_uid: str):
        self.deleted_uids.append(provider_uid)
        return None


class StubConverter:
    def canonical_to_apple(
        self,
        canonical: Dict[str, Any],
        existing_uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        uid = existing_uid or canonical.get("apple_uid", "apple-generated")
        return {
            "ical": "BEGIN:VEVENT\nSUMMARY:Event\nEND:VEVENT",
            "uid": uid,
        }

    def canonical_to_skylight(self, canonical: Dict[str, Any]) -> Dict[str, Any]:
        start = (
            canonical["start"].isoformat()
            if isinstance(canonical["start"], datetime)
            else canonical["start"]
        )
        end = (
            canonical["end"].isoformat()
            if isinstance(canonical["end"], datetime)
            else canonical["end"]
        )
        return {
            "summary": canonical.get("title", ""),
            "starts_at": start,
            "ends_at": end,
            "location": canonical.get("location", ""),
            "description": canonical.get("notes", ""),
        }


def _build_service():
    session_factory = _make_session_factory()
    with session_factory() as session:
        _seed_sync_environment(session)

    registry = ProviderRegistry(factories={})
    apple_tracker = AdapterTracker("apple")
    skylight_tracker = AdapterTracker("skylight")
    registry.register(
        ProviderTypeEnum.APPLE_CALDAV.value,
        lambda provider_id, config: apple_tracker.factory(provider_id, config),
    )
    registry.register(
        ProviderTypeEnum.SKYLIGHT.value,
        lambda provider_id, config: skylight_tracker.factory(provider_id, config),
    )

    service = ProviderEventService(
        session_factory=session_factory,
        registry=registry,
        converter=StubConverter(),
    )
    return service, session_factory, {
        "apple": apple_tracker,
        "skylight": skylight_tracker,
    }


@pytest.mark.asyncio
async def test_create_event_persists_event_and_mappings():
    service, session_factory, trackers = _build_service()
    trackers["skylight"].category_ids = ["cat-123"]

    start = datetime(2025, 1, 1, 10, 0, 0)
    end = start + timedelta(hours=1)

    result = await service.create_event(
        {
            "title": "Board Meeting",
            "start": start,
            "end": end,
            "location": "HQ",
            "notes": "Agenda",
        },
        category_names=["Family"],
    )

    assert result["title"] == "Board Meeting"
    assert set(result["providers"][0].keys()) >= {"provider_id", "provider_uid"}

    apple_adapter = trackers["apple"].instances[0]
    skylight_adapter = trackers["skylight"].instances[0]
    assert apple_adapter.created_payloads
    assert skylight_adapter.created_payloads
    assert skylight_adapter.created_payloads[0]["category_ids"] == ["cat-123"]

    with session_factory() as session:
        events = session.query(Event).all()
        mappings = session.query(ProviderMapping).all()
        assert len(events) == 1
        assert {m.provider_id for m in mappings} == {"prov_apple", "prov_skylight"}


@pytest.mark.asyncio
async def test_update_event_propagates_changes():
    service, session_factory, trackers = _build_service()

    start = datetime(2025, 1, 2, 9, 0, 0)
    end = start + timedelta(hours=1)
    create_result = await service.create_event(
        {
            "title": "Daily Standup",
            "start": start,
            "end": end,
            "location": "Zoom",
            "notes": "",
        }
    )
    event_id = create_result["id"]

    trackers["skylight"].category_ids = ["cat-updated"]

    new_start = start + timedelta(days=1)
    updates = {
        "title": "Updated Standup",
        "start_at": new_start.isoformat(),
        "end_at": (new_start + timedelta(hours=1)).isoformat(),
        "location": "Teams",
        "notes": "Bring updates",
    }

    result = await service.update_event(event_id, updates, category_names=["Updated"])

    assert result["title"] == "Updated Standup"

    skylight_adapter = trackers["skylight"].instances[-1]
    assert skylight_adapter.updated_payloads
    updated_payload = skylight_adapter.updated_payloads[0][1]
    assert updated_payload["category_ids"] == ["cat-updated"]

    with session_factory() as session:
        event = (
            session.query(Event)
            .filter(Event.id == event_id)
            .one()
        )
        assert event.title == "Updated Standup"
        mappings = (
            session.query(ProviderMapping)
            .filter(ProviderMapping.orbit_event_id == event_id)
            .all()
        )
        assert all(m.etag_or_version for m in mappings)


@pytest.mark.asyncio
async def test_delete_event_tombstones_records():
    service, session_factory, trackers = _build_service()

    start = datetime(2025, 1, 3, 14, 0, 0)
    end = start + timedelta(hours=2)
    create_result = await service.create_event(
        {
            "title": "Planning",
            "start": start,
            "end": end,
            "location": "Room 1",
            "notes": "Quarterly planning",
        }
    )
    event_id = create_result["id"]

    await service.delete_event(event_id)

    apple_adapter = trackers["apple"].instances[-1]
    skylight_adapter = trackers["skylight"].instances[-1]
    assert apple_adapter.deleted_uids == ["apple-uid"]
    assert skylight_adapter.deleted_uids == ["skylight-uid"]

    with session_factory() as session:
        event = (
            session.query(Event)
            .filter(Event.id == event_id)
            .one()
        )
        assert event.tombstoned is True
        mappings = (
            session.query(ProviderMapping)
            .filter(ProviderMapping.orbit_event_id == event_id)
            .all()
        )
        assert mappings and all(m.tombstoned for m in mappings)


@pytest.mark.asyncio
async def test_update_event_missing_event_raises():
    service, session_factory, _ = _build_service()

    with pytest.raises(EventNotFoundError):
        await service.update_event("missing", {})


@pytest.mark.asyncio
async def test_delete_event_missing_event_raises():
    service, session_factory, _ = _build_service()

    with pytest.raises(EventNotFoundError):
        await service.delete_event("missing")


@pytest.mark.asyncio
async def test_recreate_mapping_replays_provider_event():
    service, session_factory, trackers = _build_service()

    start = datetime(2025, 1, 4, 8, 0, 0)
    end = start + timedelta(hours=1)
    create_result = await service.create_event(
        {
            "title": "Coffee with Person A",
            "start": start,
            "end": end,
            "location": "Cafe",
            "notes": "Bring pastries",
        }
    )

    with session_factory() as session:
        mapping = (
            session.query(ProviderMapping)
            .filter(
                ProviderMapping.orbit_event_id == create_result["id"],
                ProviderMapping.provider_id == "prov_apple",
            )
            .one()
        )
        mapping.tombstoned = True
        session.add(mapping)
        mapping_id = mapping.id

    trackers["apple"].instances[-1].created_payloads.clear()

    result = await service.recreate_mapping(
        mapping_id=mapping_id,
        target_provider_id="prov_apple",
        force=True,
    )

    assert result["status"] == "recreated"
    assert result["provider_id"] == "prov_apple"
    assert result["mapping_id"] == mapping_id

    apple_adapter = trackers["apple"].instances[-1]
    assert apple_adapter.created_payloads, "Adapter should be invoked for recreation"

    with session_factory() as session:
        refreshed = session.query(ProviderMapping).filter(ProviderMapping.id == mapping_id).one()
        assert refreshed.tombstoned is False
        assert refreshed.last_seen_at is not None
