from __future__ import annotations

import hashlib
import json
from typing import Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes_providers
from app.core import settings as settings_module
from app.domain.models import Base, ProviderType, ProviderTypeEnum
from app.providers.base import ProviderAdapter
from app.providers.registry import provider_registry


def _fingerprint(config: Dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SuccessfulAdapter(ProviderAdapter):
    async def initialize(self) -> None:  # pragma: no cover - trivial
        return None

    async def list_events(self, start: str, end: str):  # pragma: no cover - unused
        return []

    async def create_event(self, payload):  # pragma: no cover - unused
        return {"id": "event"}

    async def update_event(self, provider_uid: str, payload):  # pragma: no cover - unused
        return {}

    async def delete_event(self, provider_uid: str) -> None:  # pragma: no cover - unused
        return None


class FailingAdapter(SuccessfulAdapter):
    async def initialize(self) -> None:
        raise RuntimeError("boom")


@pytest.fixture
def app_client(monkeypatch):
    # Create in-memory DB and session dependency override
    # Use a single in-memory SQLite database across all sessions for the test case
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)

    def override_get_db():  # pragma: no cover - fixture infra
        session = session_local()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    # Seed provider type
    with session_local() as session:
        session.add(
            ProviderType(
                id=ProviderTypeEnum.APPLE_CALDAV.value,
                label="Apple CalDAV",
                description="Test",
                adapter_version="1.0.0",
                config_schema={
                    "fields": [
                        {"name": "username", "type": "string"},
                        {"name": "password", "type": "secret", "secret": True},
                    ]
                },
            )
        )
        session.commit()

    # Stub provider registry with test adapters
    monkeypatch.setattr(provider_registry, "factories", {})
    provider_registry.register(
        ProviderTypeEnum.APPLE_CALDAV.value,
        lambda provider_id, config: SuccessfulAdapter(provider_id, config),
    )

    # Force known API key so tests can send it
    monkeypatch.setattr(settings_module, "settings", settings_module.Settings(orbit_api_key="testkey"))

    app = FastAPI()
    app.dependency_overrides[routes_providers.get_db] = override_get_db
    app.include_router(routes_providers.router)

    client = TestClient(app)
    return client


def test_update_provider_if_match_success(app_client):
    client = app_client
    # Create provider
    r = client.post(
        "/providers",
        json={
            "type_id": ProviderTypeEnum.APPLE_CALDAV.value,
            "name": "One",
            "config": {"username": "alice", "password": "pw1"},
        },
        headers={
            "Idempotency-Key": "abc",
            "X-API-Key": "testkey",
        },
    )
    assert r.status_code == 201
    body = r.json()
    provider_id = body["id"]
    fp = body["config_fingerprint"]
    assert fp
    assert body["syncs"] == []
    assert body["last_sync_at"] is None
    # Update with matching If-Match
    r2 = client.put(
        f"/providers/{provider_id}",
        json={"config": {"username": "alice", "password": "pw1"}},
        headers={
            "If-Match": f'W/"{fp}"',
            "X-API-Key": "testkey",
        },
    )
    assert r2.status_code == 200
    assert r2.headers.get("ETag") == f'W/"{fp}"'


def test_update_provider_if_match_mismatch(app_client):
    client = app_client
    # Create provider
    r = client.post(
        "/providers",
        json={
            "type_id": ProviderTypeEnum.APPLE_CALDAV.value,
            "name": "Two",
            "config": {"username": "alice", "password": "pw1"},
        },
        headers={
            "Idempotency-Key": "xyz",
            "X-API-Key": "testkey",
        },
    )
    assert r.status_code == 201
    body = r.json()
    provider_id = body["id"]
    fp = body["config_fingerprint"]
    assert fp
    # Use stale fingerprint (alter one char)
    stale = ("0" if fp[0] != "0" else "1") + fp[1:]
    r2 = client.put(
        f"/providers/{provider_id}",
        json={"config": {"username": "alice", "password": "pw1"}},
        headers={
            "If-Match": f'W/"{stale}"',
            "X-API-Key": "testkey",
        },
    )
    assert r2.status_code == 412, r2.text
    assert r2.json()["detail"].startswith("Fingerprint mismatch")


def test_test_provider_connection_success(app_client):
    client = app_client
    create = client.post(
        "/providers",
        json={
            "type_id": ProviderTypeEnum.APPLE_CALDAV.value,
            "name": "Check",
            "config": {"username": "alice", "password": "pw1"},
        },
        headers={
            "Idempotency-Key": "test-success",
            "X-API-Key": "testkey",
        },
    )
    provider_id = create.json()["id"]

    response = client.post(
        f"/providers/{provider_id}/test",
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["status_detail"] == "Connection verified successfully"
    assert data["last_checked_at"] is not None
    assert data["last_sync_at"] is None
    assert data["syncs"] == []


def test_test_provider_connection_failure(app_client):
    client = app_client

    provider_registry.register(
        ProviderTypeEnum.APPLE_CALDAV.value,
        lambda provider_id, config: FailingAdapter(provider_id, config),
    )

    create = client.post(
        "/providers",
        json={
            "type_id": ProviderTypeEnum.APPLE_CALDAV.value,
            "name": "Broken",
            "config": {"username": "alice", "password": "pw1"},
        },
        headers={
            "Idempotency-Key": "test-failure",
            "X-API-Key": "testkey",
        },
    )
    provider_id = create.json()["id"]

    response = client.post(
        f"/providers/{provider_id}/test",
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert data["status_detail"]
    assert "Connection failed" in data["status_detail"]
    assert data["syncs"] == []

    provider_registry.register(
        ProviderTypeEnum.APPLE_CALDAV.value,
        lambda provider_id, config: SuccessfulAdapter(provider_id, config),
    )
