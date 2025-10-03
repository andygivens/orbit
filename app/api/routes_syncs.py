"""Sync definition management API."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..api.auth import verify_hybrid_auth
from ..core.logging import logger
from ..core.settings import settings
from ..data.sync_mapping import EventMappingService
from ..domain.models import (
    Event,
    Provider,
    ProviderMapping,
    Sync,
    SyncDirectionEnum,
    SyncEventFlow,
    SyncRun,
    serialize_datetime,
)
from ..infra.db import get_db
from ..services.event_service import EventInspectionService
from ..services.operation_service import OperationService
from ..services.sync_crud_service import (
    SyncCrudService,
    SyncNotFoundError,
    SyncValidationError,
)
from ..services.sync_definition_service import SyncDefinition, SyncEndpointDefinition
from ..services.sync_service import SyncService

router = APIRouter(
    prefix="/syncs",
    tags=["syncs"],
    dependencies=[Depends(verify_hybrid_auth)],
)

sync_runs_router = APIRouter(
    prefix="/sync-runs",
    tags=["sync-runs"],
    dependencies=[Depends(verify_hybrid_auth)],
)


class SyncEndpointPayload(BaseModel):
    provider_id: str
    role: str = Field(default="primary")


class SyncCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    direction: str = Field(default="bidirectional")
    interval_seconds: int = Field(default=180, ge=30)
    enabled: bool = True
    endpoints: List[SyncEndpointPayload]
    window_days_back: int = Field(default=settings.sync_window_days_past, ge=0)
    window_days_forward: int = Field(default=settings.sync_window_days_future, ge=0)


class SyncUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = None
    direction: Optional[str] = None
    interval_seconds: Optional[int] = Field(default=None, ge=30)
    enabled: Optional[bool] = None
    endpoints: Optional[List[SyncEndpointPayload]] = None
    window_days_back: Optional[int] = Field(default=None, ge=0)
    window_days_forward: Optional[int] = Field(default=None, ge=0)


class SyncEndpointResponse(BaseModel):
    provider_id: str
    provider_name: Optional[str] = None
    provider_type: Optional[str] = None
    provider_type_label: Optional[str] = None
    role: str
    status: str
    status_detail: Optional[str] = None


class SyncRunMetrics(BaseModel):
    events_processed: int
    events_created: int
    events_updated: int
    events_deleted: int
    errors: int


class SyncRunSummary(BaseModel):
    id: str
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    source_provider_id: Optional[str]
    target_provider_id: Optional[str]
    stats: SyncRunMetrics
    error: Optional[str] = None
    direction: Optional[str] = None


class SyncEventSummary(BaseModel):
    id: str
    title: str
    start_at: Optional[str]
    provider_badges: List[str]
    source_provider_id: Optional[str] = None
    target_provider_id: Optional[str] = None
    direction: Optional[str] = None
    occurred_at: Optional[str] = None


class SyncEventsResponse(BaseModel):
    events: List[SyncEventSummary]


class ProviderEventRecord(BaseModel):
    orbit_event_id: Optional[str]
    provider_event_id: str
    provider_id: str
    provider_name: str
    title: str
    start_at: Optional[str]
    end_at: Optional[str]
    updated_at: Optional[str]
    provider_last_seen_at: Optional[str]
    tombstoned: bool


class ProviderEventsResponse(BaseModel):
    events: List[ProviderEventRecord]


class LinkProviderEventRequest(BaseModel):
    orbit_event_id: str


class SyncResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    direction: str
    interval_seconds: int
    window_days_back: int
    window_days_forward: int
    enabled: bool
    status: str
    last_synced_at: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    endpoints: List[SyncEndpointResponse]
    runs: List[SyncRunSummary] = []


class SyncRunAccepted(BaseModel):
    run_id: str
    status: str = "queued"


class SyncRunMetricsResponse(BaseModel):
    events_processed: int = 0
    events_created: int = 0
    events_updated: int = 0
    events_deleted: int = 0
    errors: int = 0


class SyncRunResponse(BaseModel):
    id: str
    sync_id: str
    status: str
    direction: str
    started_at: str
    finished_at: Optional[str] = None
    stats: SyncRunMetricsResponse
    error: Optional[str] = None
    source_provider_id: Optional[str] = None
    target_provider_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class SyncRunStatsPayload(BaseModel):
    events_processed: int = 0
    events_created: int = 0
    events_updated: int = 0
    events_deleted: int = 0
    errors: int = 0


class SyncRunCreateRequest(BaseModel):
    run_id: Optional[str] = None
    sync_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    direction: Literal["one_way", "bi_directional"] = "one_way"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    source_provider_id: Optional[str] = None
    target_provider_id: Optional[str] = None
    stats: Optional[SyncRunStatsPayload] = None
    error: Optional[str] = None
    operation_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    mode: Optional[Literal["run", "reconcile"]] = None


class SyncRunAggregateResponse(BaseModel):
    total_runs: int
    status_counts: Dict[str, int]
    direction_counts: Dict[str, int]
    mode_counts: Dict[str, int]
    stats_totals: SyncRunMetricsResponse
    first_started_at: Optional[str] = None
    last_started_at: Optional[str] = None


def _service(db: Session) -> SyncCrudService:
    return SyncCrudService(db)


def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
    return serialize_datetime(dt)


def _map_endpoint_status(endpoint: SyncEndpointDefinition) -> str:
    status = endpoint.provider_status or "unknown"
    if not endpoint.enabled:
        return "disabled"
    mapping = {
        "healthy": "active",
        "warning": "degraded",
        "error": "error",
        "active": "active",
        "degraded": "degraded",
        "disabled": "disabled",
        "unknown": "degraded",
    }
    return mapping.get(status, "degraded")


def _build_endpoint_response(endpoint: SyncEndpointDefinition) -> SyncEndpointResponse:
    role_map = {
        "primary": "primary",
        "secondary": "secondary",
        "both": "both",
        "outbound_only": "source",
    }
    return SyncEndpointResponse(
        provider_id=endpoint.provider_id,
        provider_name=endpoint.provider_name,
        provider_type=endpoint.provider_type,
        provider_type_label=endpoint.provider_type_label,
        role=role_map.get(endpoint.role, endpoint.role),
        status=_map_endpoint_status(endpoint),
        status_detail=endpoint.provider_status_detail,
    )


def _direction_to_api_value(value: Optional[Any]) -> str:
    if isinstance(value, SyncDirectionEnum):
        raw = value.value
    else:
        raw = value or "one_way"
    if raw in {"bidirectional", "bi_directional"}:
        return "bi_directional"
    return "one_way"


def _metric_value(primary: Optional[int], fallback: Dict[str, Any], key: str) -> int:
    candidate = primary if isinstance(primary, int) else fallback.get(key)
    try:
        return int(candidate)
    except (TypeError, ValueError):
        return 0


def _extract_run_metrics(run: SyncRun) -> SyncRunMetricsResponse:
    details = run.details if isinstance(run.details, dict) else {}
    raw_stats = (
        details.get("stats", {}) if isinstance(details.get("stats"), dict) else {}
    )
    return SyncRunMetricsResponse(
        events_processed=_metric_value(
            run.events_processed, raw_stats, "events_processed"
        ),
        events_created=_metric_value(
            run.events_created, raw_stats, "events_created"
        ),
        events_updated=_metric_value(
            run.events_updated, raw_stats, "events_updated"
        ),
        events_deleted=_metric_value(run.events_deleted, raw_stats, "events_deleted"),
        errors=_metric_value(run.errors, raw_stats, "errors"),
    )


# Connectivity checks can block while adapters retry. Keep API responses snappy by
# enforcing a short timeout and degrading gracefully when providers are offline.
async def _safe_check_connectivity(timeout: float = 5.0) -> Tuple[str, Optional[str]]:
    try:
        return await asyncio.wait_for(_check_connectivity(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Connectivity check timed out", timeout_seconds=timeout)
        return "degraded", "Provider connectivity check timed out"
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Connectivity check failed", error=str(exc))
        return "degraded", f"Connectivity check failed: {exc}"


_CONNECTIVITY_CACHE_TTL_SECONDS = 30.0
_connectivity_cache: Optional[Tuple[str, Optional[str], float]] = None
_connectivity_task: Optional[asyncio.Task[Tuple[str, Optional[str]]]] = None
_connectivity_lock = asyncio.Lock()


def _connectivity_cache_hit(now: float) -> Optional[Tuple[str, Optional[str]]]:
    cached = _connectivity_cache
    if cached and cached[2] > now:
        return cached[0], cached[1]
    return None


def _handle_connectivity_task_result(task: asyncio.Task[Tuple[str, Optional[str]]]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:  # pragma: no cover - benign
        pass
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Connectivity refresh task failed", error=str(exc))


async def _refresh_connectivity_cache() -> Tuple[str, Optional[str]]:
    global _connectivity_cache
    async with _connectivity_lock:
        status, detail = await _safe_check_connectivity()
        expires_at = time.monotonic() + _CONNECTIVITY_CACHE_TTL_SECONDS
        _connectivity_cache = (status, detail, expires_at)
        return status, detail


def _schedule_connectivity_refresh(force: bool = False) -> Optional[asyncio.Task[Tuple[str, Optional[str]]]]:
    global _connectivity_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - occurs outside event loop
        return None

    if _connectivity_task and not _connectivity_task.done():
        if not force:
            return _connectivity_task
        _connectivity_task.cancel()

    _connectivity_task = loop.create_task(_refresh_connectivity_cache())
    _connectivity_task.add_done_callback(_handle_connectivity_task_result)
    return _connectivity_task


async def _connectivity_snapshot(max_wait: float = 0.05, force_refresh: bool = False) -> Tuple[str, Optional[str]]:
    now = time.monotonic()
    if not force_refresh:
        cached = _connectivity_cache_hit(now)
        if cached:
            return cached

    task = _schedule_connectivity_refresh(force=force_refresh)
    if task and max_wait > 0:
        try:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=max_wait)
            return result
        except asyncio.TimeoutError:
            logger.debug("Connectivity refresh still running; using cached status")
        except asyncio.CancelledError:  # pragma: no cover - defensive
            pass
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Connectivity refresh failed during await", error=str(exc))

    cached = _connectivity_cache_hit(time.monotonic())
    if cached:
        return cached

    return "unknown", "Checking provider connectivity"


def _normalize_input_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _serialize_sync_run(*, run: SyncRun, direction: str) -> SyncRunResponse:
    details = dict(run.details or {})
    details.pop("stats", None)
    stats = _extract_run_metrics(run)

    started_at = _format_datetime(run.started_at or datetime.utcnow())

    finished_at = _format_datetime(run.completed_at)

    direction_hint = details.get("direction")
    direction_value = (
        _direction_to_api_value(direction_hint)
        if direction_hint
        else _direction_to_api_value(direction)
    )

    return SyncRunResponse(
        id=run.id,
        sync_id=run.sync_id,
        status=_map_run_status(run.status),
        direction=direction_value,
        started_at=started_at,
        finished_at=finished_at,
        stats=stats,
        error=run.error_message,
        source_provider_id=details.get("source_provider_id"),
        target_provider_id=details.get("target_provider_id"),
        details=details,
    )


def _encode_cursor(run: SyncRun) -> str:
    started_at = _format_datetime(run.started_at or datetime.utcnow())
    return f"{started_at}::{run.id}"


def _decode_cursor(cursor: Optional[str]) -> Optional[Tuple[datetime, str]]:
    if not cursor:
        return None
    try:
        timestamp, run_id = cursor.split("::", 1)
        parsed = datetime.fromisoformat(timestamp.replace("Z", ""))
        return parsed, run_id
    except Exception:
        return None


def _load_sync_directions(db: Session, sync_ids: Set[str]) -> Dict[str, str]:
    if not sync_ids:
        return {}
    rows = (
        db.query(Sync.id, Sync.direction)
        .filter(Sync.id.in_(sync_ids))
        .all()
    )
    return {sync_id: _direction_to_api_value(direction) for sync_id, direction in rows}


def _map_run_status(status: Optional[str]) -> str:
    mapping = {
        "success": "succeeded",
        "warning": "succeeded",
        "error": "failed",
    }
    return mapping.get(status or "queued", status or "queued")


def _compute_sync_status(
    definition: SyncDefinition,
    endpoints: List[SyncEndpointResponse],
    runs: List[SyncRun],
) -> Tuple[str, List[str], Optional[datetime]]:
    status = "active"
    notes: List[str] = []
    last_completed: Optional[datetime] = None

    if not definition.enabled:
        status = "disabled"
        notes.append("Sync disabled.")

    error_endpoints = [
        endpoint.provider_name or endpoint.provider_id
        for endpoint in endpoints
        if endpoint.status == "error"
    ]
    warning_endpoints = [
        endpoint.provider_name or endpoint.provider_id
        for endpoint in endpoints
        if endpoint.status == "degraded"
    ]
    disabled_endpoints = [
        endpoint.provider_name or endpoint.provider_id
        for endpoint in endpoints
        if endpoint.status == "disabled"
    ]

    if error_endpoints:
        status = "error"
        notes.append("Provider error: " + ", ".join(error_endpoints))
    elif warning_endpoints and status == "active":
        status = "degraded"
        notes.append("Provider warning: " + ", ".join(warning_endpoints))
    if disabled_endpoints:
        if status == "active":
            status = "degraded"
        notes.append("Provider disabled: " + ", ".join(disabled_endpoints))

    if not runs:
        if status == "active":
            status = "degraded"
        notes.append("No sync runs recorded yet.")
        return status, notes, last_completed

    for run in runs:
        mapped_status = _map_run_status(run.status)
        if mapped_status == "failed":
            status = "error"
            if run.error_message:
                notes.append(run.error_message)
            break
        if mapped_status not in {"succeeded", "failed"} and status != "error":
            status = "degraded"
            if run.error_message:
                notes.append(run.error_message)
        if run.completed_at and mapped_status in {"succeeded"}:
            if not last_completed or run.completed_at > last_completed:
                last_completed = run.completed_at

    return status, notes, last_completed


def _serialize_run_summary(run: SyncRun, definition_direction: str) -> SyncRunSummary:
    stats_payload = _extract_run_metrics(run)
    metrics = SyncRunMetrics(**stats_payload.model_dump())
    details = run.details or {}

    direction = definition_direction
    if direction == "bidirectional":
        direction = "bi_directional"

    return SyncRunSummary(
        id=run.id,
        status=_map_run_status(run.status),
        started_at=_format_datetime(run.started_at),
        completed_at=_format_datetime(run.completed_at),
        source_provider_id=details.get("source_provider_id"),
        target_provider_id=details.get("target_provider_id"),
        stats=metrics,
        error=run.error_message,
        direction=direction,
    )


def _build_sync_response(
    *,
    definition: SyncDefinition,
    runs: List[SyncRun],
    connectivity_status: str,
    connectivity_detail: Optional[str],
) -> SyncResponse:
    endpoints = [
        _build_endpoint_response(endpoint) for endpoint in definition.endpoints
    ]
    status, status_notes, last_completed = _compute_sync_status(
        definition, endpoints, runs
    )

    include_detail = False
    if connectivity_status == "error":
        status = "error"
        include_detail = True
    elif connectivity_status == "warning":
        if status == "active":
            status = "degraded"
        include_detail = True
    elif connectivity_status == "unknown":
        include_detail = True

    if connectivity_detail and include_detail:
        status_notes.append(connectivity_detail)

    notes_text = " | ".join(status_notes) if status_notes else None

    direction = definition.direction
    direction_display = "bi_directional" if direction == "bidirectional" else direction

    return SyncResponse(
        id=definition.id,
        name=definition.name,
        direction=direction_display,
        interval_seconds=definition.interval_seconds,
        window_days_back=definition.window_days_past,
        window_days_forward=definition.window_days_future,
        enabled=definition.enabled,
        status=status,
        last_synced_at=_format_datetime(last_completed),
        notes=notes_text,
        created_at=_format_datetime(definition.created_at),
        updated_at=_format_datetime(definition.updated_at),
        endpoints=endpoints,
        runs=[_serialize_run_summary(run, direction) for run in runs],
    )


async def _refresh_scheduler(request: Request) -> None:
    scheduler = getattr(request.app.state, "sync_scheduler", None)
    if scheduler:
        await scheduler.refresh_jobs()


def _normalize_direction(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value == "bi_directional":
        return "bidirectional"
    return value


@router.get("", response_model=List[SyncResponse])
async def list_syncs(db: Session = Depends(get_db)):
    connectivity_status, connectivity_detail = await _connectivity_snapshot()
    service = _service(db)
    definitions = service.list_syncs()
    responses: List[SyncResponse] = []

    for definition in definitions:
        runs = (
            db.query(SyncRun)
            .filter(SyncRun.sync_id == definition.id)
            .order_by(SyncRun.started_at.desc())
            .limit(10)
            .all()
        )
        responses.append(
            _build_sync_response(
                definition=definition,
                runs=runs,
                connectivity_status=connectivity_status,
                connectivity_detail=connectivity_detail,
            )
        )

    return responses


@router.get("/{sync_id}", response_model=SyncResponse)
async def get_sync(sync_id: str, db: Session = Depends(get_db)):
    service = _service(db)
    try:
        definition = service.get_sync(sync_id)
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    connectivity_status, connectivity_detail = await _connectivity_snapshot()
    runs = (
        db.query(SyncRun)
        .filter(SyncRun.sync_id == sync_id)
        .order_by(SyncRun.started_at.desc())
        .limit(10)
        .all()
    )
    return _build_sync_response(
        definition=definition,
        runs=runs,
        connectivity_status=connectivity_status,
        connectivity_detail=connectivity_detail,
    )


@router.post("", response_model=SyncResponse, status_code=status.HTTP_201_CREATED)
async def create_sync(
    request_payload: SyncCreateRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    service = _service(db)
    try:
        definition = service.create_sync(
            name=request_payload.name,
            direction=
                _normalize_direction(request_payload.direction) or "bidirectional",
            interval_seconds=request_payload.interval_seconds,
            enabled=request_payload.enabled,
            endpoints=[endpoint.dict() for endpoint in request_payload.endpoints],
            window_days_past=request_payload.window_days_back,
            window_days_future=request_payload.window_days_forward,
        )
        await _refresh_scheduler(request)
        response.headers["Location"] = f"/api/v1/syncs/{definition.id}"
        connectivity_status, connectivity_detail = await _connectivity_snapshot(force_refresh=True)
        runs: List[SyncRun] = []
        return _build_sync_response(
            definition=definition,
            runs=runs,
            connectivity_status=connectivity_status,
            connectivity_detail=connectivity_detail,
        )
    except SyncValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.put("/{sync_id}", response_model=SyncResponse)
async def update_sync(
    sync_id: str,
    request_payload: SyncUpdateRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    service = _service(db)
    try:
        endpoints_payload = None
        if request_payload.endpoints is not None:
            endpoints_payload = [
                endpoint.dict()
                for endpoint in request_payload.endpoints
            ]

        interval_seconds = None
        if request_payload.interval_seconds is not None:
            interval_seconds = request_payload.interval_seconds

        definition = service.update_sync(
            sync_id,
            name=request_payload.name,
            direction=_normalize_direction(request_payload.direction),
            interval_seconds=interval_seconds,
            enabled=request_payload.enabled,
            endpoints=endpoints_payload,
            window_days_past=request_payload.window_days_back,
            window_days_future=request_payload.window_days_forward,
        )
        await _refresh_scheduler(request)
        connectivity_status, connectivity_detail = await _connectivity_snapshot(force_refresh=True)
        runs = (
            db.query(SyncRun)
            .filter(SyncRun.sync_id == sync_id)
            .order_by(SyncRun.started_at.desc())
            .limit(10)
            .all()
        )
        serialized = _build_sync_response(
            definition=definition,
            runs=runs,
            connectivity_status=connectivity_status,
            connectivity_detail=connectivity_detail,
        )
        if serialized.updated_at:
            response.headers["ETag"] = f'W/"{serialized.updated_at}"'
        return serialized
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except SyncValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{sync_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sync(sync_id: str, request: Request, db: Session = Depends(get_db)):
    service = _service(db)
    try:
        service.delete_sync(sync_id)
        await _refresh_scheduler(request)
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return None


@sync_runs_router.post(
    "", response_model=SyncRunResponse, status_code=status.HTTP_201_CREATED
)
def create_or_update_sync_run(
    payload: SyncRunCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    sync_exists = db.query(Sync.id).filter(Sync.id == payload.sync_id).first()
    if not sync_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sync '{payload.sync_id}' not found",
        )

    run: Optional[SyncRun] = None
    if payload.run_id:
        run = db.query(SyncRun).filter(SyncRun.id == payload.run_id).first()

    created = run is None
    if created:
        run = SyncRun(
            sync_id=payload.sync_id,
            direction=payload.direction,
            status=payload.status,
        )
        if payload.run_id:
            run.id = payload.run_id
    else:
        run.sync_id = payload.sync_id
        if "direction" in payload.model_fields_set:
            run.direction = payload.direction or run.direction

    run.status = payload.status

    fields_set = payload.model_fields_set

    if "started_at" in fields_set:
        normalized_start = _normalize_input_datetime(payload.started_at)
        if normalized_start is not None:
            run.started_at = normalized_start
    elif not run.started_at:
        run.started_at = datetime.utcnow()

    if "finished_at" in fields_set:
        normalized_finish = _normalize_input_datetime(payload.finished_at)
        run.completed_at = normalized_finish
    elif payload.status in {"succeeded", "failed"}:
        run.completed_at = run.completed_at or datetime.utcnow()

    if payload.stats is not None:
        run.events_processed = payload.stats.events_processed
        run.events_created = payload.stats.events_created
        run.events_updated = payload.stats.events_updated
        run.events_deleted = payload.stats.events_deleted
        run.errors = payload.stats.errors
    elif created:
        run.events_processed = run.events_processed or 0
        run.events_created = run.events_created or 0
        run.events_updated = run.events_updated or 0
        run.events_deleted = run.events_deleted or 0
        run.errors = run.errors or 0

    if "error" in fields_set:
        run.error_message = payload.error

    details = dict(run.details or {})
    if "details" in fields_set and payload.details:
        details.update(payload.details)

    if "source_provider_id" in fields_set:
        details["source_provider_id"] = payload.source_provider_id
    if "target_provider_id" in fields_set:
        details["target_provider_id"] = payload.target_provider_id
    if payload.operation_id is not None or "operation_id" in fields_set:
        details["operation_id"] = payload.operation_id
    if created or "direction" in fields_set:
        details["direction"] = payload.direction
    run_mode = payload.mode or details.get("mode")
    if run_mode not in {"run", "reconcile"}:
        run_mode = "run"
    details["mode"] = run_mode
    run.details = details

    db.add(run)
    db.flush()
    db.commit()
    db.refresh(run)

    direction_map = _load_sync_directions(db, {run.sync_id} if run.sync_id else set())
    direction_value = direction_map.get(run.sync_id) if run.sync_id else None
    if direction_value is None:
        direction_value = payload.direction

    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    if created:
        response.headers["Location"] = f"/api/v1/sync-runs/{run.id}"

    return _serialize_sync_run(
        run=run,
        direction=_direction_to_api_value(direction_value),
    )


@sync_runs_router.get("/summary", response_model=SyncRunAggregateResponse)
def get_sync_run_summary(
    sync_id: Optional[str] = Query(default=None),
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to_: Optional[datetime] = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
):
    query = db.query(SyncRun)
    if sync_id:
        query = query.filter(SyncRun.sync_id == sync_id)

    start_bound = _normalize_input_datetime(from_)
    end_bound = _normalize_input_datetime(to_)

    if start_bound:
        query = query.filter(SyncRun.started_at >= start_bound)
    if end_bound:
        query = query.filter(SyncRun.started_at <= end_bound)

    runs = query.order_by(SyncRun.started_at.asc()).all()

    status_counts: Dict[str, int] = defaultdict(int)
    direction_counts: Dict[str, int] = defaultdict(int)
    mode_counts: Dict[str, int] = defaultdict(int)

    totals = {
        "events_processed": 0,
        "events_created": 0,
        "events_updated": 0,
        "events_deleted": 0,
        "errors": 0,
    }

    sync_ids = {run.sync_id for run in runs if run.sync_id}
    direction_map = _load_sync_directions(db, sync_ids)

    first_started: Optional[datetime] = None
    last_started: Optional[datetime] = None

    for run in runs:
        status_counts[_map_run_status(run.status)] += 1

        direction_key = direction_map.get(run.sync_id, _direction_to_api_value(None))
        direction_counts[direction_key] += 1

        metrics = _extract_run_metrics(run)
        totals["events_processed"] += metrics.events_processed
        totals["events_created"] += metrics.events_created
        totals["events_updated"] += metrics.events_updated
        totals["events_deleted"] += metrics.events_deleted
        totals["errors"] += metrics.errors

        details = run.details if isinstance(run.details, dict) else {}
        raw_mode = str(details.get("mode") or "run")
        mode_key = "reconcile" if raw_mode == "reconcile" else "run"
        mode_counts[mode_key] += 1

        if run.started_at:
            if first_started is None or run.started_at < first_started:
                first_started = run.started_at
            if last_started is None or run.started_at > last_started:
                last_started = run.started_at

    stats_totals = SyncRunMetricsResponse(**totals)

    summary = SyncRunAggregateResponse(
        total_runs=len(runs),
        status_counts=dict(status_counts),
        direction_counts=dict(direction_counts),
        mode_counts=dict(mode_counts),
        stats_totals=stats_totals,
        first_started_at=_format_datetime(first_started),
        last_started_at=_format_datetime(last_started),
    )

    return summary


@sync_runs_router.get("", response_model=List[SyncRunResponse])
def list_sync_runs(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    sync_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
    if sync_id:
        query = query.filter(SyncRun.sync_id == sync_id)

    cursor_payload = _decode_cursor(cursor)
    if cursor_payload:
        started_at, cursor_id = cursor_payload
        query = query.filter(
            (SyncRun.started_at < started_at)
            | ((SyncRun.started_at == started_at) & (SyncRun.id < cursor_id))
        )

    records = query.limit(limit + 1).all()
    sliced = records[:limit]
    next_cursor = None
    if len(records) > limit and sliced:
        next_cursor = _encode_cursor(sliced[-1])

    sync_ids = {run.sync_id for run in sliced if run.sync_id}
    direction_map = _load_sync_directions(db, sync_ids)

    runs = [
        _serialize_sync_run(
            run=run,
            direction=direction_map.get(run.sync_id, _direction_to_api_value(None)),
        )
        for run in sliced
    ]

    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor

    return runs


@sync_runs_router.get("/{run_id}", response_model=SyncRunResponse)
def get_sync_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(SyncRun).filter(SyncRun.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sync run '{run_id}' not found",
        )

    direction_map = _load_sync_directions(db, {run.sync_id} if run.sync_id else set())
    direction = direction_map.get(run.sync_id, _direction_to_api_value(None))

    return _serialize_sync_run(run=run, direction=direction)


async def _execute_sync_action(
    *,
    sync_id: str,
    mode: str,
    operations: OperationService,
    definition: SyncDefinition,
) -> SyncRunAccepted:
    record = operations.create_operation(
        kind=f"sync_{mode}",
        status="queued",
        resource_type="sync",
        resource_id=sync_id,
        payload={"mode": mode},
    )
    operations.update(
        record.id,
        status="running",
        started_at=datetime.utcnow(),
    )
    sync_service = SyncService()
    try:
        result = await sync_service.run_sync(definition)
        run_ids = [
            run.get("run_id") for run in result.get("runs", []) if run.get("run_id")
        ]
        final_record = operations.update(
            record.id,
            status="succeeded",
            result=result,
            finished_at=datetime.utcnow(),
        )
        run_id = run_ids[0] if run_ids else final_record.id
        return SyncRunAccepted(run_id=run_id, status=final_record.status)
    except Exception as exc:  # pragma: no cover - defensive
        operations.update(
            record.id,
            status="failed",
            error={"message": str(exc)},
            finished_at=datetime.utcnow(),
        )
        raise HTTPException(status_code=500, detail=f"{mode.title()} failed")


@router.post(
    "/{sync_id}:run",
    response_model=SyncRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_sync_run(
    sync_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    service = _service(db)
    try:
        definition = service.get_sync(sync_id)
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    operations = OperationService(db)
    try:
        result = await _execute_sync_action(
            sync_id=sync_id,
            mode="run",
            operations=operations,
            definition=definition,
        )
        db.commit()
        return result
    except HTTPException:
        db.commit()
        raise


@router.post(
    "/{sync_id}:reconcile",
    response_model=SyncRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_sync_reconcile(
    sync_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    service = _service(db)
    try:
        definition = service.get_sync(sync_id)
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    operations = OperationService(db)
    try:
        result = await _execute_sync_action(
            sync_id=sync_id,
            mode="reconcile",
            operations=operations,
            definition=definition,
        )
        db.commit()
        return result
    except HTTPException:
        db.commit()
        raise


@router.get("/{sync_id}/events", response_model=SyncEventsResponse)
async def list_sync_events(
    sync_id: str,
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    service = _service(db)
    try:
        definition = service.get_sync(sync_id)
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    provider_ids = [endpoint.provider_id for endpoint in definition.endpoints]
    events = _events_for_sync(
        db,
        provider_ids,
        limit=limit,
        sync_id=definition.id,
    )

    return SyncEventsResponse(events=events)


@router.get(
    "/{sync_id}/providers/{provider_id}/events",
    response_model=ProviderEventsResponse,
)
async def list_sync_provider_events(
    sync_id: str,
    provider_id: str,
    response: Response,
    limit: int = Query(100, ge=1, le=200),
    since: Optional[str] = Query(default=None, description="ISO8601 start time"),
    until: Optional[str] = Query(default=None, description="ISO8601 end time"),
    cursor: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    service = _service(db)
    try:
        definition = service.get_sync(sync_id)
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    endpoint_ids = {endpoint.provider_id for endpoint in definition.endpoints}
    if provider_id not in endpoint_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider not attached to this sync",
        )

    since_dt = _parse_iso_datetime(since) if since else None
    until_dt = _parse_iso_datetime(until) if until else None

    inspection = EventInspectionService(db)
    records, next_cursor = inspection.list_provider_events(
        provider_ids=[provider_id],
        since=since_dt,
        until=until_dt,
        limit=limit,
        cursor=cursor,
    )

    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor

    return ProviderEventsResponse(
        events=[ProviderEventRecord(**record) for record in records]
    )


@router.post(
    "/{sync_id}/providers/{provider_id}/events/{provider_event_id}/link",
    response_model=ProviderEventRecord,
)
async def link_sync_provider_event(
    sync_id: str,
    provider_id: str,
    provider_event_id: str,
    payload: LinkProviderEventRequest,
    db: Session = Depends(get_db),
):
    service = _service(db)
    try:
        definition = service.get_sync(sync_id)
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    endpoint_ids = {endpoint.provider_id for endpoint in definition.endpoints}
    if provider_id not in endpoint_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider not attached to this sync",
        )

    orbit_event = (
        db.query(Event)
        .filter(Event.id == payload.orbit_event_id)
        .first()
    )
    if not orbit_event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orbit event not found")

    provider = db.query(Provider).filter(Provider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    mapping_service = EventMappingService(db)
    mapping = mapping_service.get_mapping(provider_id, provider_event_id)
    if not mapping:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider event mapping not found",
        )

    previous_orbit_id = mapping.orbit_event_id

    existing_target = (
        db.query(ProviderMapping)
        .filter(
            ProviderMapping.provider_id == provider_id,
            ProviderMapping.orbit_event_id == orbit_event.id,
            ProviderMapping.provider_uid != provider_event_id,
        )
        .first()
    )

    try:
        if existing_target:
            db.delete(existing_target)

        mapping.orbit_event_id = orbit_event.id
        mapping.last_seen_at = datetime.utcnow()
        mapping.tombstoned = False

        db.flush()

        if previous_orbit_id and previous_orbit_id != orbit_event.id:
            remaining_previous = (
                db.query(ProviderMapping)
                .filter(ProviderMapping.orbit_event_id == previous_orbit_id)
                .count()
            )
            if remaining_previous == 0:
                previous_event = (
                    db.query(Event)
                    .filter(Event.id == previous_orbit_id)
                    .first()
                )
                if previous_event:
                    previous_event.tombstoned = True

        db.commit()
    except Exception:
        db.rollback()
        raise

    return _serialize_provider_event(mapping, provider, orbit_event)


@router.delete(
    "/{sync_id}/providers/{provider_id}/events/{provider_event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_sync_provider_event(
    sync_id: str,
    provider_id: str,
    provider_event_id: str,
    db: Session = Depends(get_db),
):
    service = _service(db)
    try:
        definition = service.get_sync(sync_id)
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    endpoint_ids = {endpoint.provider_id for endpoint in definition.endpoints}
    if provider_id not in endpoint_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider not attached to this sync",
        )

    mapping = (
        db.query(ProviderMapping)
        .filter(
            ProviderMapping.provider_id == provider_id,
            ProviderMapping.provider_uid == provider_event_id,
        )
        .first()
    )
    if not mapping:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider event mapping not found",
        )

    orbit_event_id = mapping.orbit_event_id

    try:
        db.delete(mapping)
        db.flush()

        remaining = (
            db.query(ProviderMapping)
            .filter(ProviderMapping.orbit_event_id == orbit_event_id)
            .count()
        )
        if remaining == 0 and orbit_event_id:
            orbit_event = (
                db.query(Event)
                .filter(Event.id == orbit_event_id)
                .first()
            )
            if orbit_event:
                orbit_event.tombstoned = True

        db.commit()
    except Exception:
        db.rollback()
        raise

    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _check_connectivity() -> Tuple[
    Literal["active", "degraded", "error", "disabled"],
    Optional[str],
]:
    """Perform lightweight connectivity checks via provider adapters."""

    service = SyncService()
    readiness = await service.check_readiness()

    if readiness.get("status") == "ready":
        return "active", "All providers responded successfully"

    providers = readiness.get("providers", [])
    failures = [
        (
            f"{provider.get('name') or provider.get('id')} unreachable "
            f"({provider.get('detail') or 'unknown error'})"
        )
        for provider in providers
        if provider.get("status") != "connected"
    ]

    reason = readiness.get("reason")
    if reason == "no_enabled_providers":
        return "disabled", "No enabled providers configured"

    if failures:
        return "error", "; ".join(failures)

    if reason:
        return "degraded", reason

    return "degraded", "Provider readiness degraded"


def _parse_iso_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid datetime value: {value}",
        ) from exc


def _events_for_sync(
    session: Session,
    provider_ids: List[str],
    *,
    limit: int = 4,
    sync_id: Optional[str] = None,
) -> List[SyncEventSummary]:
    if not provider_ids:
        return []

    events = (
        session.query(Event)
        .join(ProviderMapping, Event.id == ProviderMapping.orbit_event_id)
        .filter(ProviderMapping.provider_id.in_(provider_ids))
        .order_by(Event.updated_at.desc())
        .limit(limit)
        .all()
    )

    flow_map: Dict[str, SyncEventFlow] = {}
    orbit_ids = [event.id for event in events]
    if sync_id and orbit_ids:
        flow_rows = (
            session.query(SyncEventFlow)
            .filter(
                SyncEventFlow.sync_id == sync_id,
                SyncEventFlow.orbit_event_id.in_(orbit_ids),
            )
            .order_by(
                SyncEventFlow.orbit_event_id.asc(),
                SyncEventFlow.occurred_at.desc(),
            )
            .all()
        )
        for flow in flow_rows:
            if flow.orbit_event_id not in flow_map:
                flow_map[flow.orbit_event_id] = flow

    summaries: List[SyncEventSummary] = []
    for event in events:
        provider_badges: List[str] = []
        for mapping in event.provider_mappings:
            if mapping.provider_id not in provider_ids:
                continue
            if mapping.provider and mapping.provider.name:
                provider_badges.append(mapping.provider.name)
            elif mapping.provider_type:
                provider_badges.append(mapping.provider_type.value)
            else:
                provider_badges.append(mapping.provider_id)

        flow = flow_map.get(event.id)
        summaries.append(
            SyncEventSummary(
                id=event.id,
                title=event.title,
                start_at=serialize_datetime(event.start_at),
                provider_badges=provider_badges,
                source_provider_id=getattr(flow, "source_provider_id", None),
                target_provider_id=getattr(flow, "target_provider_id", None),
                direction=getattr(flow, "direction", None),
                occurred_at=_format_datetime(flow.occurred_at) if flow else None,
            )
        )

    return summaries


def _serialize_provider_event(
    mapping: ProviderMapping,
    provider: Provider,
    event: Event,
) -> ProviderEventRecord:
    return ProviderEventRecord(
        orbit_event_id=mapping.orbit_event_id,
        provider_event_id=mapping.provider_uid,
        provider_id=mapping.provider_id,
        provider_name=provider.name or mapping.provider_id,
        title=event.title,
        start_at=serialize_datetime(event.start_at),
        end_at=serialize_datetime(event.end_at),
        updated_at=serialize_datetime(event.updated_at),
        provider_last_seen_at=serialize_datetime(mapping.last_seen_at),
        tombstoned=bool(mapping.tombstoned),
    )
