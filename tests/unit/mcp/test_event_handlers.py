from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest

from app.mcp.handlers import event_handlers
from app.services.provider_event_service import (
    EventNotFoundError,
    ProviderEventServiceError,
)


class StubProviderEventService:
    create_calls = []
    update_calls = []
    delete_calls = []
    create_result = {
        "id": "evt-1",
        "title": "Created",
        "start_at": datetime(2025, 1, 4, 12, 0, 0).isoformat(),
        "end_at": datetime(2025, 1, 4, 13, 0, 0).isoformat(),
        "updated_at": datetime(2025, 1, 4, 11, 0, 0).isoformat(),
        "providers": [],
    }
    update_result = {
        "id": "evt-1",
        "title": "Updated",
        "start_at": datetime(2025, 1, 5, 12, 0, 0).isoformat(),
        "end_at": datetime(2025, 1, 5, 13, 0, 0).isoformat(),
        "updated_at": datetime(2025, 1, 5, 11, 0, 0).isoformat(),
        "providers": [],
    }
    raise_on_update: Optional[str] = None
    raise_on_delete: Optional[str] = None

    def __init__(self, *args, **kwargs):  # pragma: no cover - trivial
        pass

    async def create_event(self, canonical, *, category_names=None, sync_id=None):
        self.__class__.create_calls.append((canonical, tuple(category_names or [])))
        return self.create_result

    async def update_event(self, event_id, updates, *, category_names=None):
        self.__class__.update_calls.append((event_id, updates))
        if self.raise_on_update == "not_found":
            raise EventNotFoundError("missing")
        if self.raise_on_update == "error":
            raise ProviderEventServiceError("update failed")
        return self.update_result

    async def delete_event(self, event_id):
        self.__class__.delete_calls.append(event_id)
        if self.raise_on_delete == "not_found":
            raise EventNotFoundError("missing")
        if self.raise_on_delete == "error":
            raise ProviderEventServiceError("delete failed")
        return {"status": "deleted"}

    @classmethod
    def reset(cls):
        cls.create_calls.clear()
        cls.update_calls.clear()
        cls.delete_calls.clear()
        cls.raise_on_update = None
        cls.raise_on_delete = None


@pytest.fixture(autouse=True)
def _patch_provider_event_service(monkeypatch):
    monkeypatch.setattr(event_handlers, "ProviderEventService", StubProviderEventService)
    yield
    StubProviderEventService.reset()


@pytest.mark.asyncio
async def test_handle_create_event_success():
    payload = {
        "title": "Created",
        "start_at": datetime(2025, 1, 4, 12, 0, 0).isoformat(),
        "end_at": datetime(2025, 1, 4, 13, 0, 0).isoformat(),
        "location": "HQ",
        "notes": "",
        "categories": ["Family"],
    }

    result = await event_handlers.handle_create_event(payload)

    assert result["success"] is True
    assert StubProviderEventService.create_calls


@pytest.mark.asyncio
async def test_handle_update_event_not_found():
    StubProviderEventService.raise_on_update = "not_found"

    result = await event_handlers.handle_update_event(
        {"event_id": "evt-missing", "updates": {"title": "Updated"}}
    )

    assert result == {"error": "Event with id evt-missing not found"}


@pytest.mark.asyncio
async def test_handle_delete_event_error():
    StubProviderEventService.raise_on_delete = "error"

    result = await event_handlers.handle_delete_event({"event_id": "evt-1"})

    assert result["error"].startswith("Failed to delete event")
