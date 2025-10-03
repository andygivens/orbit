from datetime import datetime, timezone

from fastapi import Response

from app.api.routes_syncs import (
    SyncRunCreateRequest,
    SyncRunStatsPayload,
    create_or_update_sync_run,
    get_sync_run_summary,
)
from app.domain.models import Sync, SyncDirectionEnum, SyncRun
from app.infra.db import SessionLocal, create_tables


def _ensure_sync(session, sync_id: str = "sync_manual") -> None:
    existing = session.query(Sync).filter(Sync.id == sync_id).first()
    if existing:
        return
    session.add(
        Sync(
            id=sync_id,
            name="Manual Backfill",
            direction=SyncDirectionEnum.BIDIRECTIONAL,
            interval_seconds=300,
            window_days_past=7,
            window_days_future=7,
            enabled=True,
        )
    )
    session.commit()


def _clear_runs(session, sync_id: str) -> None:
    session.query(SyncRun).filter(SyncRun.sync_id == sync_id).delete()
    session.commit()


def test_create_sync_run_backfill_record():
    create_tables()
    session = SessionLocal()
    _ensure_sync(session)
    _clear_runs(session, "sync_manual")

    payload = SyncRunCreateRequest(
        run_id="sync_manual_run",
        sync_id="sync_manual",
        status="queued",
        direction="bi_directional",
        started_at=datetime(2025, 9, 27, 12, 0, 0, tzinfo=timezone.utc),
        source_provider_id="prov_primary",
        target_provider_id="prov_secondary",
        stats=SyncRunStatsPayload(
            events_processed=42,
            events_created=5,
            events_updated=30,
            events_deleted=7,
            errors=0,
        ),
        operation_id="op_backfill",
        details={"notes": "historical backfill"},
    )

    response = Response()
    result = create_or_update_sync_run(payload, response, session)

    assert response.status_code == 201
    assert response.headers["Location"].endswith("/sync_manual_run")
    assert result.id == "sync_manual_run"
    assert result.status == "queued"
    assert result.direction == "bi_directional"
    assert result.stats.events_processed == 42
    assert result.source_provider_id == "prov_primary"
    assert result.target_provider_id == "prov_secondary"
    assert result.details["notes"] == "historical backfill"
    assert result.details["operation_id"] == "op_backfill"

    stored = session.query(Sync).filter(Sync.id == "sync_manual").one()
    run_row = stored.runs[-1]
    assert run_row.status == "queued"
    assert run_row.details["operation_id"] == "op_backfill"

    session.close()


def test_update_sync_run_backfill_record():
    create_tables()
    session = SessionLocal()
    _ensure_sync(session)
    _clear_runs(session, "sync_manual")

    # Ensure there is an initial record to update
    initial_payload = SyncRunCreateRequest(
        run_id="sync_manual_run_update",
        sync_id="sync_manual",
        status="queued",
    )
    create_or_update_sync_run(initial_payload, Response(), session)

    payload = SyncRunCreateRequest(
        run_id="sync_manual_run_update",
        sync_id="sync_manual",
        status="running",
        stats=SyncRunStatsPayload(
            events_processed=10,
            events_created=2,
            events_updated=5,
            events_deleted=1,
            errors=2,
        ),
    )

    response = Response()
    result = create_or_update_sync_run(payload, response, session)

    assert response.status_code == 200
    assert "Location" not in response.headers
    assert result.status == "running"
    assert result.stats.events_processed == 10
    assert result.stats.errors == 2

    stored = session.query(Sync).filter(Sync.id == "sync_manual").one()
    run_row = next(run for run in stored.runs if run.id == "sync_manual_run_update")
    assert run_row.status == "running"
    assert run_row.events_processed == 10
    assert run_row.errors == 2

    session.close()


def test_sync_run_summary_aggregation():
    create_tables()
    session = SessionLocal()
    _ensure_sync(session)
    _clear_runs(session, "sync_manual")

    base_start = datetime(2025, 9, 27, 12, 0, 0, tzinfo=timezone.utc)

    create_or_update_sync_run(
        SyncRunCreateRequest(
            run_id="sync_manual_run_summary_1",
            sync_id="sync_manual",
            status="succeeded",
            direction="bi_directional",
            started_at=base_start,
            stats=SyncRunStatsPayload(
                events_processed=20,
                events_created=5,
                events_updated=10,
                events_deleted=3,
                errors=2,
            ),
            mode="run",
        ),
        Response(),
        session,
    )

    create_or_update_sync_run(
        SyncRunCreateRequest(
            run_id="sync_manual_run_summary_2",
            sync_id="sync_manual",
            status="failed",
            direction="bi_directional",
            started_at=base_start.replace(hour=13),
            stats=SyncRunStatsPayload(
                events_processed=15,
                events_created=2,
                events_updated=7,
                events_deleted=1,
                errors=6,
            ),
            mode="reconcile",
        ),
        Response(),
        session,
    )

    summary = get_sync_run_summary(sync_id="sync_manual", from_=None, to_=None, db=session)

    assert summary.total_runs == 2
    assert summary.mode_counts.get("run", 0) == 1
    assert summary.mode_counts.get("reconcile", 0) == 1
    assert summary.direction_counts.get("bi_directional", 0) == 2
    assert summary.status_counts.get("succeeded", 0) == 1
    assert summary.status_counts.get("failed", 0) == 1
    assert summary.stats_totals.events_processed == 35
    assert summary.stats_totals.errors == 8
    assert summary.first_started_at == "2025-09-27T12:00:00Z"
    assert summary.last_started_at == "2025-09-27T13:00:00Z"

    session.close()
