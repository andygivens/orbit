from __future__ import annotations

import pytest

from app.services.operation_processor import OperationProcessor
from app.services.operation_service import OperationService
from tests.unit.services.test_provider_event_service import _build_service


def _create_operation(session_factory, **kwargs):
    with session_factory() as session:
        operations = OperationService(session)
        record = operations.create_operation(**kwargs)
        session.commit()
        return record.id


def _get_operation(session_factory, operation_id: str):
    with session_factory() as session:
        operations = OperationService(session)
        return operations.get(operation_id)


@pytest.mark.asyncio
async def test_operation_processor_handles_orphan_delete():
    provider_service, session_factory, trackers = _build_service()

    operation_id = _create_operation(
        session_factory,
        kind="troubleshoot_orphan_delete",
        status="queued",
        resource_type="provider_orphan",
        resource_id="prov_apple:uid-1",
        payload={"provider_id": "prov_apple", "provider_uid": "uid-1"},
    )

    processor = OperationProcessor(
        session_factory=session_factory,
        registry=provider_service.registry,
        interval=0.05,
    )

    await processor.process_batch(limit=5)

    record = _get_operation(session_factory, operation_id)
    assert record["status"] == "succeeded"
    # Adapter tracker records the delete call
    deleted = trackers["apple"].instances[0].deleted_uids
    assert deleted == ["uid-1"]


@pytest.mark.asyncio
async def test_operation_processor_handles_duplicate_delete():
    provider_service, session_factory, trackers = _build_service()

    operation_id = _create_operation(
        session_factory,
        kind="troubleshoot_duplicate_resolve",
        status="queued",
        resource_type="troubleshoot_duplicate_group",
        resource_id="dup-key",
        payload={
            "action": "delete",
            "targets": [
                {"provider_id": "prov_apple", "provider_uid": "dup-1"},
                {"provider_id": "prov_skylight", "provider_uid": "dup-2"},
            ],
        },
    )

    processor = OperationProcessor(
        session_factory=session_factory,
        registry=provider_service.registry,
        interval=0.05,
    )

    await processor.process_batch(limit=5)

    record = _get_operation(session_factory, operation_id)
    assert record["status"] == "succeeded"
    apple_deleted = trackers["apple"].instances[0].deleted_uids
    skylight_deleted = trackers["skylight"].instances[0].deleted_uids
    assert apple_deleted == ["dup-1"]
    assert skylight_deleted == ["dup-2"]


@pytest.mark.asyncio
async def test_operation_processor_marks_orphan_pull_failed():
    provider_service, session_factory, _ = _build_service()

    operation_id = _create_operation(
        session_factory,
        kind="troubleshoot_orphan_pull",
        status="queued",
        resource_type="provider_orphan",
        resource_id="prov_apple:uid-new",
        payload={"provider_id": "prov_apple", "provider_uid": "uid-new"},
    )

    processor = OperationProcessor(
        session_factory=session_factory,
        registry=provider_service.registry,
        interval=0.05,
    )

    await processor.process_batch(limit=5)

    record = _get_operation(session_factory, operation_id)
    assert record["status"] == "failed"
    assert "not yet implemented" in record["error"].get("message", "")
