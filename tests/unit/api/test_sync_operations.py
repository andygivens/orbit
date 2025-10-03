from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import routes_syncs
from app.core.scheduler import SyncScheduler
from app.services.operation_service import OperationService


class StubOperationService:
    def __init__(self):
        self.created = []
        self.updates = []

    def create_operation(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="op-123")

    def update(self, operation_id, **kwargs):
        payload = {"id": operation_id}
        payload.update(kwargs)
        self.updates.append(payload)
        return SimpleNamespace(id=operation_id, status=kwargs.get("status"))


@pytest.mark.asyncio
async def test_execute_sync_action_updates_operation_states(monkeypatch):
    stub_ops = StubOperationService()

    class FakeSyncService:
        async def run_sync(self, definition):
            return {"runs": [{"run_id": "run-42"}], "status": "success"}

    monkeypatch.setattr(routes_syncs, "SyncService", lambda: FakeSyncService())

    definition = SimpleNamespace(id="sync-1")
    result = await routes_syncs._execute_sync_action(
        sync_id="sync-1",
        mode="run",
        operations=stub_ops,
        definition=definition,
    )

    statuses = [update["status"] for update in stub_ops.updates]
    assert statuses == ["running", "succeeded"]
    assert stub_ops.updates[0]["started_at"] is not None
    assert stub_ops.updates[1]["finished_at"] is not None
    assert result.run_id == "run-42"
    assert result.status == "succeeded"


@pytest.mark.asyncio
async def test_execute_sync_action_marks_failure(monkeypatch):
    stub_ops = StubOperationService()

    class FakeSyncService:
        async def run_sync(self, definition):  # pragma: no cover - simulated failure
            raise RuntimeError("boom")

    monkeypatch.setattr(routes_syncs, "SyncService", lambda: FakeSyncService())

    definition = SimpleNamespace(id="sync-err")
    with pytest.raises(HTTPException) as excinfo:
        await routes_syncs._execute_sync_action(
            sync_id="sync-err",
            mode="run",
            operations=stub_ops,
            definition=definition,
        )

    statuses = [update["status"] for update in stub_ops.updates]
    assert statuses == ["running", "failed"]
    assert stub_ops.updates[1]["error"]["message"] == "boom"
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_scheduler_records_operation_lifecycle(monkeypatch):
    created = []
    updated = []

    def fake_create(cls, **kwargs):
        created.append(kwargs)
        return SimpleNamespace(id="op-sched")

    def fake_update(cls, operation_id, **kwargs):
        payload = {"id": operation_id}
        payload.update(kwargs)
        updated.append(payload)
        return SimpleNamespace(id=operation_id)

    monkeypatch.setattr(OperationService, "create", classmethod(fake_create))
    monkeypatch.setattr(OperationService, "update_status", classmethod(fake_update))

    class FakeSyncService:
        async def run_sync(self, definition, mode="run"):
            assert mode == "run"
            return {"runs": [], "status": "success"}

    scheduler = SyncScheduler(sync_service=FakeSyncService())
    scheduler.sync_definitions = [
        SimpleNamespace(id="sync-1", enabled=True, name="Test", interval_seconds=60, endpoints=[])
    ]

    result = await scheduler._run_dynamic_sync("sync-1")

    assert created[0]["status"] == "running"
    assert created[0]["payload"] == {"trigger": "scheduler"}
    assert "finished_at" in updated[0]
    assert updated[0]["status"] == "succeeded"
    assert result == {"runs": [], "status": "success"}
