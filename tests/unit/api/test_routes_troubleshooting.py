from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_troubleshooting


@pytest.fixture
def troubleshooting_client():
    app = FastAPI()
    app.include_router(routes_troubleshooting.router, prefix="/api/v1")
    client = TestClient(app)
    try:
        yield client
    finally:
        client.app.dependency_overrides.clear()


def test_list_mappings_returns_payload(troubleshooting_client):
    class StubService:
        def list_mappings(self, *, window_key, future_window_key, limit, cursor, sync_id):
            return (
                [
                    {
                        "orbit_event_id": "evt-1",
                        "title": "Board Meeting",
                        "start_at": "2025-09-27T12:00:00Z",
                        "end_at": "2025-09-27T13:00:00Z",
                        "sync_id": None,
                        "segments": [
                            {
                                "mapping_id": "map-1",
                                "provider_id": "prov-1",
                                "provider_type": "apple_caldav",
                                "provider_uid": "uid-1",
                                "provider_label": "Provider 1",
                                "role": "source",
                                "first_seen_at": None,
                                "last_seen_at": "2025-09-27T12:05:00Z",
                                "created_at": "2025-09-27T12:00:00Z",
                                "updated_at": "2025-09-27T12:05:00Z",
                                "tombstoned": False,
                                "extra": None,
                            }
                        ],
                        "last_merged_at": None,
                        "notes": None,
                    }
                ],
                None,
            )

    troubleshooting_client.app.dependency_overrides[
        routes_troubleshooting.get_troubleshooting_service
    ] = lambda: StubService()

    response = troubleshooting_client.get("/api/v1/troubleshooting/sync/mappings?window=7d")
    assert response.status_code == 200
    assert response.json()["mappings"][0]["orbit_event_id"] == "evt-1"


def test_list_provider_events_returns_payload(troubleshooting_client):
    class StubService:
        async def list_provider_events(self, *, provider_id, window_key, future_window_key, limit, cursor, sync_id):
            assert provider_id == "prov-1"
            assert window_key == "7d"
            return (
                [
                    {
                        "orbit_event_id": "evt-1",
                        "provider_event_id": "uid-1",
                        "provider_id": provider_id,
                        "provider_name": "Provider One",
                        "title": "Board Meeting",
                        "start_at": "2025-09-27T12:00:00Z",
                        "end_at": None,
                        "updated_at": "2025-09-27T12:05:00Z",
                        "provider_last_seen_at": "2025-09-27T12:05:00Z",
                        "tombstoned": False,
                    }
                ],
                "cursor-123",
                [],
            )

    troubleshooting_client.app.dependency_overrides[
        routes_troubleshooting.get_troubleshooting_service
    ] = lambda: StubService()

    response = troubleshooting_client.get(
        "/api/v1/troubleshooting/provider/prov-1/events?window=7d"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["events"][0]["provider_id"] == "prov-1"
    assert payload["events"][0]["provider_event_id"] == "uid-1"


def test_confirm_provider_returns_payload(troubleshooting_client):
    class StubService:
        def confirm_event(self, *, provider_id, provider_uid, mapping_id=None, sync_id=None):
            return {
                "status": "confirmed",
                "provider_id": provider_id,
                "provider_uid": provider_uid,
                "mapping_id": "map-1",
                "last_seen_at": "2025-09-27T12:06:00Z",
                "operation_id": None,
            }

    troubleshooting_client.app.dependency_overrides[
        routes_troubleshooting.get_troubleshooting_service
    ] = lambda: StubService()

    response = troubleshooting_client.post(
        "/api/v1/troubleshooting/provider/confirmations",
        json={
            "provider_id": "prov-1",
            "provider_uid": "uid-1",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


def test_recreate_mapping_returns_payload(troubleshooting_client):
    class StubService:
        async def recreate_event(self, *, mapping_id, target_provider_id, force, sync_id=None):
            return {
                "status": "recreated",
                "provider_id": target_provider_id,
                "provider_uid": "uid-123",
                "mapping_id": mapping_id,
                "created_at": "2025-09-27T12:05:00Z",
                "last_seen_at": "2025-09-27T12:06:00Z",
                "operation_id": None,
            }

    troubleshooting_client.app.dependency_overrides[
        routes_troubleshooting.get_troubleshooting_service
    ] = lambda: StubService()

    response = troubleshooting_client.post(
        "/api/v1/troubleshooting/provider/recreate",
        json={"mapping_id": "mapping-1", "target_provider_id": "prov-1"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "recreated"


def test_list_duplicates_returns_payload(troubleshooting_client):
    class StubService:
        async def list_duplicates(self, *, window_key, future_window_key, limit, cursor, sync_id):
            return (
                [
                    {
                        "group_id": "dup:abc",
                        "dedupe_key": "coffee|2025-09-27T12:00",
                        "original": {
                            "orbit_event_id": "evt-1",
                            "title": "Coffee",
                            "start_at": "2025-09-27T12:00:00Z",
                            "end_at": None,
                            "location": "Cafe",
                            "notes": None,
                            "provider_ids": ["prov_apple"],
                            "provider_uids": ["uid-apple"],
                            "mappings": [
                                {
                                    "mapping_id": "map-apple",
                                    "provider_id": "prov_apple",
                                    "provider_uid": "uid-apple",
                                    "provider_label": "Apple",
                                    "provider_type": "apple_caldav",
                                    "last_seen_at": None,
                                    "etag_or_version": None,
                                    "tombstoned": False,
                                    "created_at": "2025-09-27T12:00:00Z",
                                    "updated_at": "2025-09-27T12:00:00Z",
                                }
                            ],
                        },
                        "duplicates": [
                            {
                                "orbit_event_id": "evt-2",
                                "title": "Coffee",
                                "start_at": "2025-09-27T12:00:30Z",
                                "end_at": None,
                                "location": None,
                                "notes": None,
                                "provider_ids": ["prov_skylight"],
                                "provider_uids": ["uid-skylight"],
                                "mappings": [
                                    {
                                        "mapping_id": "map-skylight",
                                        "provider_id": "prov_skylight",
                                        "provider_uid": "uid-skylight",
                                        "provider_label": "Skylight",
                                        "provider_type": "skylight",
                                        "last_seen_at": None,
                                        "etag_or_version": None,
                                        "tombstoned": False,
                                        "created_at": "2025-09-27T12:00:30Z",
                                        "updated_at": "2025-09-27T12:00:30Z",
                                    }
                                ],
                            }
                        ],
                        "created_at": "2025-09-27T12:01:00Z",
                    }
                ],
                None,
                [
                    {
                        "group_id": "provdup:abc",
                        "dedupe_key": "coffee|2025-09-27T12:00",
                        "provider_id": "prov_skylight",
                        "provider_label": "Skylight",
                        "events": [
                            {
                                "provider_uid": "uid-skylight",
                                "title": "Coffee",
                                "start_at": "2025-09-27T12:00:00Z",
                                "end_at": "2025-09-27T13:00:00Z",
                                "timezone": "America/New_York",
                                "orbit_event_id": None,
                                "mapping_id": None,
                                "source": "from-app",
                            },
                            {
                                "provider_uid": "uid-skylight-2",
                                "title": "Coffee",
                                "start_at": "2025-09-27T12:00:30Z",
                                "end_at": "2025-09-27T13:00:30Z",
                                "timezone": "America/New_York",
                                "orbit_event_id": None,
                                "mapping_id": None,
                                "source": "from-app",
                            },
                        ],
                    }
                ],
            )

    troubleshooting_client.app.dependency_overrides[
        routes_troubleshooting.get_troubleshooting_service
    ] = lambda: StubService()

    response = troubleshooting_client.get(
        "/api/v1/troubleshooting/sync/duplicates"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["groups"][0]["group_id"] == "dup:abc"
    assert payload["groups"][0]["original"]["mappings"][0]["provider_id"] == "prov_apple"
    assert payload["provider_only_groups"][0]["provider_id"] == "prov_skylight"


def test_resolve_duplicate_calls_service(troubleshooting_client):
    called = {}

    class StubService:
        def resolve_duplicate_group(self, *, group_id, action):
            called["group_id"] = group_id
            called["action"] = action
            return {
                "status": "completed",
                "group_id": group_id,
                "operation_id": "op-123",
            }

    troubleshooting_client.app.dependency_overrides[
        routes_troubleshooting.get_troubleshooting_service
    ] = lambda: StubService()

    response = troubleshooting_client.post(
        "/api/v1/troubleshooting/sync/duplicates/group-1/resolve",
        json={"action": "delete"},
    )
    assert response.status_code == 200
    assert response.json()["operation_id"] == "op-123"
    assert called == {"group_id": "group-1", "action": "delete"}


def test_acknowledge_missing_returns_payload(troubleshooting_client):
    class StubService:
        def acknowledge_missing_counterpart(self, *, mapping_id, missing_provider_id, reason=None, sync_id=None):
            assert mapping_id == "map-1"
            assert missing_provider_id == "prov-2"
            return {
                "status": "acknowledged",
                "mapping_id": mapping_id,
                "missing_provider_id": missing_provider_id,
                "orbit_event_id": "evt-1",
                "operation_id": "op-ack",
            }

    troubleshooting_client.app.dependency_overrides[
        routes_troubleshooting.get_troubleshooting_service
    ] = lambda: StubService()

    response = troubleshooting_client.post(
        "/api/v1/troubleshooting/sync/mappings/map-1/missing/resolve",
        json={"missing_provider_id": "prov-2"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "acknowledged"
    assert payload["mapping_id"] == "map-1"
    assert payload["operation_id"] == "op-ack"


def test_pull_orphan_returns_payload(troubleshooting_client):
    class StubService:
        async def pull_orphan(self, *, provider_id, provider_uid, reason=None, sync_id=None):
            assert provider_id == "prov-apple"
            assert provider_uid == "uid-123"
            return {
                "status": "queued",
                "provider_id": provider_id,
                "provider_uid": provider_uid,
                "operation_id": "op-pull",
            }

    troubleshooting_client.app.dependency_overrides[
        routes_troubleshooting.get_troubleshooting_service
    ] = lambda: StubService()

    response = troubleshooting_client.post(
        "/api/v1/troubleshooting/provider/prov-apple/orphans/uid-123/pull",
        json={},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_id"] == "prov-apple"
    assert payload["status"] == "queued"


def test_delete_orphan_returns_payload(troubleshooting_client):
    class StubService:
        async def delete_orphan(self, *, provider_id, provider_uid, reason=None, sync_id=None):
            assert provider_id == "prov-apple"
            assert provider_uid == "uid-456"
            return {
                "status": "queued",
                "provider_id": provider_id,
                "provider_uid": provider_uid,
                "operation_id": "op-delete",
            }

    troubleshooting_client.app.dependency_overrides[
        routes_troubleshooting.get_troubleshooting_service
    ] = lambda: StubService()

    response = troubleshooting_client.post(
        "/api/v1/troubleshooting/provider/prov-apple/orphans/uid-456/delete",
        json={},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_uid"] == "uid-456"


def test_system_status_returns_501(troubleshooting_client):
    response = troubleshooting_client.get("/api/v1/troubleshooting/system/status")
    assert response.status_code == 501
    assert response.json()["detail"].startswith("Troubleshooting work")
