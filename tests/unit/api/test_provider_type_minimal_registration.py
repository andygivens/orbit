from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes_providers
from app.core import settings as settings_module
from app.domain.models import Base


@pytest.fixture
def client(monkeypatch):
    # In-memory DB shared across sessions
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)

    def override_get_db():  # pragma: no cover - fixture plumbing
        session = session_local()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    # Force API key
    monkeypatch.setattr(
        settings_module,
        "settings",
        settings_module.Settings(orbit_api_key="testkey"),
    )

    app = FastAPI()
    app.dependency_overrides[routes_providers.get_db] = override_get_db
    app.include_router(routes_providers.router)

    return TestClient(app)


def test_minimal_provider_auto_registers_type(client):
    # Create minimal provider (adapter should auto-register type)
    r = client.post(
        "/providers",
        json={
            "type_id": "minimal",
            "name": "Minimal Demo",
            "config": {"api_key": "x"},
        },
        headers={
            "Idempotency-Key": "min-1",
            "X-API-Key": "testkey",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type_id"] == "minimal"
    assert body.get("config_fingerprint")

    # List provider types and assert minimal present
    r2 = client.get(
        "/providers/types",
        headers={"X-API-Key": "testkey"},
    )
    assert r2.status_code == 200, r2.text
    types = r2.json()
    ids = {t["id"] for t in types}
    assert "minimal" in ids, f"Expected 'minimal' in provider types, got {ids}"

    # Registry health endpoint includes dynamic type summary
    r3 = client.get(
        "/providers/health",
        headers={"X-API-Key": "testkey"},
    )
    assert r3.status_code == 200
    health = r3.json()
    assert health["dynamic_present"] is True
    assert any(t["id"] == "minimal" for t in health["types"])
