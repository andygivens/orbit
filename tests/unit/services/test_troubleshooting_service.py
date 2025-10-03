from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import selectinload

import app.services.troubleshooting_service as troubleshooting_module
from app.domain.mapping import EventMapper
from app.domain.models import Event, OperationRecord, ProviderMapping
from app.services.provider_event_service import ProviderEventServiceError
from app.services.troubleshooting_service import (
    TroubleshootingService,
    TroubleshootingServiceError,
)
from tests.unit.services.test_provider_event_service import _build_service


@pytest.mark.asyncio
async def test_list_duplicates_detects_groups():
    provider_service, session_factory, trackers = _build_service()

    now = datetime.utcnow().replace(microsecond=0)
    base = now.replace(second=0)
    start = base - timedelta(minutes=5)
    end = start + timedelta(hours=1)

    # Create two events with same normalized title/start minute so they appear as duplicates.
    await provider_service.create_event(
        {
            "title": "Coffee Time",
            "start": start,
            "end": end,
            "location": "Cafe",
            "notes": "",
        }
    )

    trackers["apple"].kind = "apple_second"
    trackers["skylight"].kind = "skylight_second"

    await provider_service.create_event(
        {
            "title": "coffee time",  # same title, different casing
            "start": start + timedelta(seconds=30),  # still within same minute
            "end": end + timedelta(minutes=1),
            "location": "Cafe",
            "notes": "",
        }
    )

    with session_factory() as session:
        assert session.query(Event).count() == 2
        mapper = EventMapper()
        events = (
            session.query(Event)
            .options(selectinload(Event.provider_mappings))
            .all()
        )
        keys = [mapper.create_dedup_key(event.title, event.start_at) for event in events]
        assert len(set(keys)) == 1
        assert all(event.provider_mappings for event in events)
        assert all(
            len([m for m in event.provider_mappings if not m.tombstoned]) == 2
            for event in events
        )
        dedupe_groups = {}
        for event in events:
            key = mapper.create_dedup_key(event.title, event.start_at)
            dedupe_groups.setdefault(key, []).append(event)
        assert any(len(items) > 1 for items in dedupe_groups.values())

    def _now_factory(tz):
        if now.tzinfo is None:
            return now.replace(tzinfo=tz)
        return now.astimezone(tz)

    service = TroubleshootingService(session_factory=session_factory, now_factory=_now_factory)
    groups, cursor, provider_only = await service.list_duplicates(
        window_key="7d",
        future_window_key="0d",
        limit=50,
        cursor=None,
        sync_id=None,
    )

    assert cursor is None
    assert groups, "Expected duplicate groups to be returned"
    group = groups[0]
    assert group["original"]["title"].lower() == "coffee time"
    assert len(group["duplicates"]) >= 1
    assert group["group_id"].startswith("dup:")


async def _prepare_duplicate_group():
    provider_service, session_factory, trackers = _build_service()

    now = datetime.utcnow().replace(microsecond=0)
    base = now.replace(second=0)
    start = base - timedelta(minutes=5)
    end = start + timedelta(hours=1)

    await provider_service.create_event(
        {
            "title": "Standup",
            "start": start,
            "end": end,
            "location": "Room 1",
            "notes": "",
        }
    )

    trackers["apple"].kind = "apple_dup"
    trackers["skylight"].kind = "skylight_dup"

    await provider_service.create_event(
        {
            "title": "standup",
            "start": start + timedelta(seconds=15),
            "end": end + timedelta(minutes=1),
            "location": "Room 1",
            "notes": "",
        }
    )

    def _now_factory(tz):
        if now.tzinfo is None:
            return now.replace(tzinfo=tz)
        return now.astimezone(tz)

    service = TroubleshootingService(session_factory=session_factory, now_factory=_now_factory)
    groups, _, provider_only = await service.list_duplicates(
        window_key="7d",
        future_window_key="0d",
        limit=50,
        cursor=None,
        sync_id=None,
    )
    assert groups, "Expected duplicate group to exist"
    return service, session_factory, groups[0]


@pytest.mark.asyncio
async def test_resolve_duplicate_group_tombstones_and_logs_operation():
    service, session_factory, group = await _prepare_duplicate_group()

    duplicate_mapping_ids = {
        mapping["mapping_id"]
        for duplicate in group["duplicates"]
        for mapping in duplicate.get("mappings", [])
    }
    original_mapping_ids = {
        mapping["mapping_id"]
        for mapping in group["original"].get("mappings", [])
    }

    result = service.resolve_duplicate_group(
        group_id=group["group_id"],
        action="tombstone",
    )

    assert result["status"] == "completed"
    assert result["operation_id"]

    with session_factory() as session:
        duplicates = (
            session.query(ProviderMapping)
            .filter(ProviderMapping.id.in_(duplicate_mapping_ids))
            .all()
        )
        originals = (
            session.query(ProviderMapping)
            .filter(ProviderMapping.id.in_(original_mapping_ids))
            .all()
        )

        assert duplicates, "Expected duplicate mappings in database"
        assert all(mapping.tombstoned for mapping in duplicates)
        assert originals, "Expected original mappings in database"
        assert all(not mapping.tombstoned for mapping in originals)

        operation = (
            session.query(OperationRecord)
            .filter(OperationRecord.id == result["operation_id"])
            .one()
        )
        operation = session.merge(operation)  # Ensure operation is attached to the session
        assert operation.kind == "troubleshoot_duplicate_resolve"
        assert operation.status == "succeeded"
        assert operation.payload.get("action") == "tombstone"
        assert operation.result.get("tombstoned_count") == len(duplicate_mapping_ids)


@pytest.mark.asyncio
async def test_resolve_duplicate_group_delete_marks_operation_queued():
    service, session_factory, group = await _prepare_duplicate_group()

    result = service.resolve_duplicate_group(
        group_id=group["group_id"],
        action="delete",
    )

    assert result["status"] == "completed"
    assert result["operation_id"]

    with session_factory() as session:
        operation = (
            session.query(OperationRecord)
            .filter(OperationRecord.id == result["operation_id"])
            .one()
        )
        assert operation.status == "queued"
        assert operation.payload.get("action") == "delete"


@pytest.mark.asyncio
async def test_recreate_event_logs_operations(monkeypatch):
    _, session_factory, _ = _build_service()

    now = datetime.utcnow().replace(microsecond=0)

    def _now_factory(tz):
        if now.tzinfo is None:
            return now.replace(tzinfo=tz)
        return now.astimezone(tz)

    service = TroubleshootingService(session_factory=session_factory, now_factory=_now_factory)

    class StubProviderService:
        async def recreate_mapping(self, mapping_id, target_provider_id, force):
            return {
                "status": "recreated",
                "provider_id": target_provider_id,
                "provider_uid": "uid-xyz",
                "mapping_id": mapping_id,
                "created_at": "2025-09-27T12:05:00Z",
                "last_seen_at": "2025-09-27T12:06:00Z",
                "operation_id": None,
            }

    monkeypatch.setattr(
        troubleshooting_module,
        "ProviderEventService",
        lambda: StubProviderService(),
    )

    result = await service.recreate_event(
        mapping_id="map-123",
        target_provider_id="prov-1",
        force=False,
    )

    assert result["operation_id"] is not None

    with session_factory() as session:
        operation = (
            session.query(OperationRecord)
            .filter(OperationRecord.id == result["operation_id"])
            .one()
        )
        assert operation.kind == "troubleshoot_mapping_recreate"
        assert operation.status == "succeeded"
        assert operation.payload.get("target_provider_id") == "prov-1"


@pytest.mark.asyncio
async def test_recreate_event_failure_updates_operation(monkeypatch):
    _, session_factory, _ = _build_service()

    now = datetime.utcnow().replace(microsecond=0)

    def _now_factory(tz):
        if now.tzinfo is None:
            return now.replace(tzinfo=tz)
        return now.astimezone(tz)

    service = TroubleshootingService(session_factory=session_factory, now_factory=_now_factory)

    class FailingProviderService:
        async def recreate_mapping(self, mapping_id, target_provider_id, force):
            raise ProviderEventServiceError("adapter failure")

    monkeypatch.setattr(
        troubleshooting_module,
        "ProviderEventService",
        lambda: FailingProviderService(),
    )

    with pytest.raises(TroubleshootingServiceError):
        await service.recreate_event(
            mapping_id="map-err",
            target_provider_id="prov-err",
            force=False,
        )

    with session_factory() as session:
        operation = session.query(OperationRecord).first()
        assert operation is not None
        assert operation.status == "failed"
        assert operation.error.get("message") == "adapter failure"


@pytest.mark.asyncio
async def test_acknowledge_missing_counterpart_creates_operation():
    provider_service, session_factory, _ = _build_service()

    start = datetime(2025, 1, 3, 9, 0, 0)
    end = start + timedelta(hours=1)
    await provider_service.create_event(
        {
            "title": "Planning",
            "start": start,
            "end": end,
            "location": "Room 2",
            "notes": "",
        }
    )

    with session_factory() as session:
        mapping = session.query(ProviderMapping).first()
        assert mapping is not None
        mapping_id = mapping.id
        orbit_event_id = mapping.orbit_event_id

    service = TroubleshootingService(session_factory=session_factory)
    result = service.acknowledge_missing_counterpart(
        mapping_id=mapping_id,
        missing_provider_id="prov_missing",
        reason="Legacy sync",
        sync_id=None,
    )

    assert result["status"] == "acknowledged"
    assert result["mapping_id"] == mapping_id
    assert result["orbit_event_id"] == orbit_event_id

    with session_factory() as session:
        operation = (
            session.query(OperationRecord)
            .filter(OperationRecord.id == result["operation_id"])
            .one()
        )
        assert operation.kind == "troubleshoot_missing_resolve"
        assert operation.status == "succeeded"
        assert operation.payload.get("missing_provider_id") == "prov_missing"


@pytest.mark.asyncio
async def test_pull_orphan_creates_operation():
    _, session_factory, _ = _build_service()

    service = TroubleshootingService(session_factory=session_factory)
    result = await service.pull_orphan(
        provider_id="prov_apple",
        provider_uid="orphan-1",
        reason="Manual import",
        sync_id=None,
    )

    assert result["status"] == "queued"
    assert result["provider_uid"] == "orphan-1"

    with session_factory() as session:
        operation = (
            session.query(OperationRecord)
            .filter(OperationRecord.id == result["operation_id"])
            .one()
        )
        assert operation.kind == "troubleshoot_orphan_pull"
        assert operation.status == "queued"
        assert operation.payload.get("provider_uid") == "orphan-1"


@pytest.mark.asyncio
async def test_delete_orphan_creates_operation():
    _, session_factory, _ = _build_service()

    service = TroubleshootingService(session_factory=session_factory)
    result = await service.delete_orphan(
        provider_id="prov_skylight",
        provider_uid="orphan-2",
        reason=None,
        sync_id="sync-123",
    )

    assert result["status"] == "queued"
    assert result["provider_id"] == "prov_skylight"

    with session_factory() as session:
        operation = (
            session.query(OperationRecord)
            .filter(OperationRecord.id == result["operation_id"])
            .one()
        )
        assert operation.kind == "troubleshoot_orphan_delete"
        assert operation.status == "queued"
        assert operation.payload.get("sync_id") == "sync-123"
