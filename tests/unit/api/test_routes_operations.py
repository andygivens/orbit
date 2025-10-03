import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_operations


@pytest.fixture
def operations_app_factory(monkeypatch):
    def _create(service_cls):
        app = FastAPI()
        app.include_router(routes_operations.router)

        async def allow_scope():
            return "scope-ok"

        @contextmanager
        def fake_get_db():
            yield SimpleNamespace()

        app.dependency_overrides[routes_operations.get_db] = fake_get_db

        for route in app.router.routes:
            dependant = getattr(route, "dependant", None)
            if not dependant:
                continue
            for dep in dependant.dependencies:
                if dep.call is None:
                    continue
                if dep.call.__module__ == "app.api.auth":
                    app.dependency_overrides[dep.call] = allow_scope

        monkeypatch.setattr(routes_operations, "OperationService", service_cls)
        return app

    return _create


def test_list_operations_sets_cursor_header(monkeypatch, operations_app_factory):
    class StubOperationService:
        def __init__(self, db):
            self.db = db

        def list(self, **kwargs):
            assert kwargs["resource_type"] == "sync"
            assert kwargs["resource_id"] == "sync-123"
            return (
                [
                    {
                        "id": "op-1",
                        "kind": "sync_run",
                        "status": "queued",
                        "resource_type": "sync",
                        "resource_id": "sync-123",
                        "payload": {},
                        "result": {},
                        "error": {},
                        "created_at": "2025-09-27T12:00:00Z",
                        "started_at": None,
                        "finished_at": None,
                    }
                ],
                "cursor-1",
            )

    app = operations_app_factory(StubOperationService)
    client = TestClient(app)

    response = client.get(
        "/operations",
        params={"resource_type": "sync", "resource_id": "sync-123"},
    )
    assert response.status_code == 200
    assert response.headers["x-next-cursor"] == "cursor-1"
    payload = response.json()
    assert payload[0]["id"] == "op-1"
    assert payload[0]["status"] == "queued"


def test_get_operation_not_found(monkeypatch, operations_app_factory):
    class StubOperationService:
        def __init__(self, db):
            self.db = db

        def get(self, operation_id):
            return None

    app = operations_app_factory(StubOperationService)
    client = TestClient(app)

    response = client.get("/operations/op-missing")
    assert response.status_code == 404
    assert response.json()["detail"] == "Operation not found"


def _collect_sse_events(stream_response, max_events=2):
    buffer = ""
    events = []
    for chunk in stream_response.iter_text():
        buffer += chunk
        while "\n\n" in buffer:
            raw, buffer = buffer.split("\n\n", 1)
            if not raw.strip():
                continue
            event_type = None
            data = None
            for line in raw.split("\n"):
                if line.startswith("event: "):
                    event_type = line[len("event: "):].strip()
                elif line.startswith("data: "):
                    data = json.loads(line[len("data: "):])
            if event_type:
                events.append((event_type, data))
                if len(events) >= max_events:
                    return events
    return events


def test_operations_stream_emits_updates(monkeypatch, operations_app_factory):
    class StreamingStubOperationService:
        def __init__(self, db):
            self.db = db
            self.calls = 0

        def list(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                status = "queued"
                started = None
                finished = None
            elif self.calls == 2:
                status = "running"
                started = "2025-09-27T12:01:00Z"
                finished = None
            else:
                status = "running"
                started = "2025-09-27T12:01:00Z"
                finished = None

            return (
                [
                    {
                        "id": "op-1",
                        "kind": "sync_run",
                        "status": status,
                        "resource_type": "sync",
                        "resource_id": "sync-123",
                        "payload": {},
                        "result": {},
                        "error": {},
                        "created_at": "2025-09-27T12:00:00Z",
                        "started_at": started,
                        "finished_at": finished,
                    }
                ],
                None,
            )

    async def fast_sleep(_duration):
        return None

    monkeypatch.setattr("app.api.routes_operations.asyncio.sleep", fast_sleep)

    app = operations_app_factory(StreamingStubOperationService)
    client = TestClient(app)

    with client.stream(
        "GET",
        "/operations/stream",
        params={"poll_interval": 0},
        headers={"Accept": "text/event-stream"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["x-orbit-mode"] == "sse"
        events = _collect_sse_events(response, max_events=2)

    assert len(events) == 2
    snapshot_event, update_event = events

    assert snapshot_event[0] == "snapshot"
    assert snapshot_event[1]["operations"][0]["status"] == "queued"

    assert update_event[0] == "operation"
    assert update_event[1]["status"] == "running"
    assert update_event[1]["started_at"] == "2025-09-27T12:01:00Z"
