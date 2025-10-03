from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes_syncs
from app.domain.models import (
    Base,
    Event,
    Provider,
    ProviderMapping,
    ProviderStatusEnum,
    ProviderType,
    ProviderTypeEnum,
    Sync,
    SyncDirectionEnum,
    SyncEndpoint,
    SyncEndpointRoleEnum,
)


@pytest.fixture
def syncs_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():  # pragma: no cover - fixture plumbing
        session = session_factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    api_router = APIRouter(prefix="/api/v1")
    api_router.include_router(routes_syncs.router)

    app = FastAPI()
    app.include_router(api_router)
    app.dependency_overrides[routes_syncs.get_db] = override_get_db
    app.dependency_overrides[routes_syncs.verify_hybrid_auth] = lambda: "token"

    client = TestClient(app)
    return client, session_factory


def _seed_core_entities(session):
    provider_type = ProviderType(
        id=ProviderTypeEnum.APPLE_CALDAV.value,
        label="Apple",
        description="",
        config_schema={"fields": []},
    )
    session.add(provider_type)
    session.flush()

    provider = Provider(
        id="prov-1",
        type=ProviderTypeEnum.APPLE_CALDAV,
        type_id=ProviderTypeEnum.APPLE_CALDAV.value,
        name="Apple",
        config={"username": "alice"},
        status=ProviderStatusEnum.ACTIVE,
    )
    session.add(provider)

    sync = Sync(
        id="sync-1",
        name="Calendar",
        direction=SyncDirectionEnum.BIDIRECTIONAL,
        interval_seconds=300,
        enabled=True,
    )
    session.add(sync)
    session.flush()

    session.add(
        SyncEndpoint(
            sync_id=sync.id,
            provider_id=provider.id,
            role=SyncEndpointRoleEnum.PRIMARY,
        )
    )
    session.flush()

    return sync, provider


def _create_event(session, provider, title, start_offset_minutes, provider_uid, *, create_mapping: bool = True):
    start = datetime(2025, 1, 5, 9, 0, tzinfo=timezone.utc) + timedelta(minutes=start_offset_minutes)
    event = Event(
        title=title,
        start_at=start,
        end_at=start + timedelta(hours=1),
        location="Cafe",
        notes="",
        content_hash="",
    )
    event.update_content_hash()
    session.add(event)
    session.flush()

    mapping = None
    if create_mapping:
        mapping = ProviderMapping(
            event=event,
            provider=provider,
            provider_type=ProviderTypeEnum.APPLE_CALDAV,
            provider_uid=provider_uid,
            tombstoned=False,
            last_seen_at=start,
        )
        session.add(mapping)
        session.flush()

    return event, mapping


def test_sync_events_endpoint_returns_recent_history(syncs_client):
    client, session_factory = syncs_client
    with session_factory() as session:
        sync, provider = _seed_core_entities(session)
        event, _ = _create_event(session, provider, "Coffee", 0, "uid-1")
        session.commit()

    response = client.get(f"/api/v1/syncs/{sync.id}/events", params={"limit": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["events"], payload
    first = payload["events"][0]
    assert first["id"] == event.id
    assert first["title"] == "Coffee"
    assert first["start_at"].startswith("2025-01-05")


def test_sync_provider_events_endpoint_supports_cursor(syncs_client):
    client, session_factory = syncs_client
    with session_factory() as session:
        sync, provider = _seed_core_entities(session)
        _create_event(session, provider, "Breakfast", 0, "uid-1")
        event_latest, _ = _create_event(session, provider, "Lunch", 90, "uid-2")
        session.commit()

    response = client.get(
        f"/api/v1/syncs/{sync.id}/providers/{provider.id}/events",
        params={"limit": 1},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Next-Cursor")
    body = response.json()
    assert len(body["events"]) == 1
    record = body["events"][0]
    assert record["provider_event_id"] == "uid-2"
    assert record["orbit_event_id"], body
    assert record["updated_at"].startswith(event_latest.updated_at.strftime("%Y-%m-%d"))


def test_link_and_unlink_provider_event(syncs_client):
    client, session_factory = syncs_client
    with session_factory() as session:
        sync, provider = _seed_core_entities(session)
        event_original, mapping = _create_event(session, provider, "Coffee", 0, "uid-1")
        event_new, _ = _create_event(
            session,
            provider,
            "Dinner",
            120,
            "uid-1",
            create_mapping=False,
        )
        session.commit()

    link_response = client.post(
        f"/api/v1/syncs/{sync.id}/providers/{provider.id}/events/{mapping.provider_uid}/link",
        json={"orbit_event_id": event_new.id},
    )
    assert link_response.status_code == 200, link_response.text
    body = link_response.json()
    assert body["orbit_event_id"] == event_new.id
    assert body["provider_event_id"] == mapping.provider_uid

    with session_factory() as check_session:
        refreshed = (
            check_session.query(ProviderMapping)
            .filter(ProviderMapping.provider_id == provider.id, ProviderMapping.provider_uid == mapping.provider_uid)
            .one()
        )
        assert refreshed.orbit_event_id == event_new.id
        # Original event should be tombstoned because it lost its only mapping
        original = check_session.query(Event).filter(Event.id == event_original.id).one()
        assert original.tombstoned is True

    delete_response = client.delete(
        f"/api/v1/syncs/{sync.id}/providers/{provider.id}/events/{mapping.provider_uid}"
    )
    assert delete_response.status_code == 204

    with session_factory() as post_delete:
        remaining = (
            post_delete.query(ProviderMapping)
            .filter(ProviderMapping.provider_id == provider.id, ProviderMapping.provider_uid == mapping.provider_uid)
            .all()
        )
        assert remaining == []
        new_event = post_delete.query(Event).filter(Event.id == event_new.id).one()
        assert new_event.tombstoned is True

