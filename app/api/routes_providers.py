"""Provider management API endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, joinedload

from ..api.auth import require_scope
from ..domain.models import Event, ProviderMapping, serialize_datetime
from ..infra.db import get_db
from ..services.operation_service import OperationService
from ..services.provider_event_service import (
    EventNotFoundError,
    ProviderEventService,
    ProviderEventServiceError,
)
from ..services.provider_service import (
    ProviderNotFoundError,
    ProviderService,
    ProviderTypeNotFoundError,
    ProviderValidationError,
)

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderTypeResponse(BaseModel):
    id: str
    label: str
    description: Optional[str]
    config_schema: Dict[str, Any]
    created_at: Optional[str]
    adapter_version: Optional[str] = Field(
        default=None,
        description="Semantic version string of the backing adapter if known",
    )
    config_schema_hash: Optional[str] = Field(
        default=None,
        description=(
            "SHA-256 hash of the canonical adapter config schema for drift "
            "detection"
        ),
    )


class ProviderSyncSummary(BaseModel):
    id: str
    name: str
    role: Optional[str] = None
    direction: Optional[str] = None
    enabled: bool
    last_run_status: Optional[str] = None
    last_run_at: Optional[str] = None


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type_id: str
    name: str
    enabled: bool
    status: str
    status_detail: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_checked_at: Optional[str] = None
    last_sync_at: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    config_schema_version: Optional[str] = None
    config_fingerprint: Optional[str] = Field(
        default=None,
        description=(
            "Stable fingerprint (SHA-256 hex) of sanitized provider config "
            "used for optimistic concurrency"
        ),
    )
    syncs: List[ProviderSyncSummary] = Field(default_factory=list)


class ProviderCreateRequest(BaseModel):
    type_id: str = Field(..., description="Provider type identifier")
    name: str = Field(..., description="Human-friendly provider name")
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ProviderUpdateRequest(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    status: Optional[str] = None
    status_detail: Optional[str] = None


def _service(db: Session) -> ProviderService:
    return ProviderService(db)


class ProviderEventResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    provider_event_id: Optional[str] = None
    title: str
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    tombstoned: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProviderEventCreateRequest(BaseModel):
    title: str
    start_at: str
    end_at: str
    location: Optional[str] = None
    notes: Optional[str] = None


class ProviderEventUpdateRequest(BaseModel):
    title: Optional[str] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class OperationAcceptedResponse(BaseModel):
    operation_id: str
    status: str = "queued"


def _to_provider_response(payload: Dict[str, Any]) -> ProviderResponse:
    data = {
        "id": payload.get("id"),
        "type_id": payload.get("type_id") or payload.get("type") or "",
        "name": payload.get("name"),
        "enabled": payload.get("enabled", True),
        "status": payload.get("status", "degraded"),
        "status_detail": payload.get("status_detail"),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
        "last_checked_at": payload.get("last_checked_at"),
        "last_sync_at": payload.get("last_sync_at"),
        "config": payload.get("config") or {},
        "config_schema_version": payload.get("config_schema_version"),
        "config_fingerprint": payload.get("config_fingerprint"),
        "syncs": payload.get("syncs") or [],
    }
    return ProviderResponse(**data)


@router.get(
    "/types",
    response_model=List[ProviderTypeResponse],
    dependencies=[Depends(require_scope("read:events"))],
)
def list_provider_types(db: Session = Depends(get_db)):
    service = _service(db)
    return service.list_provider_types()


@router.get(
    "/health",
    dependencies=[Depends(require_scope("read:events"))],
)
def provider_registry_health(db: Session = Depends(get_db)):
    """Lightweight registry health: counts and dynamic adapter presence.

    Returns a list of provider types (id + adapter_version + schema hash) and a
    summary object for quick UI diagnostics.
    """
    service = _service(db)
    rows = service.list_provider_types()
    minimal = [r for r in rows if r.get("id") == "minimal"]
    return {
        "status": "ok",
        "type_count": len(rows),
        "dynamic_present": bool(minimal),
        "types": [
            {
                "id": r.get("id"),
                "adapter_version": r.get("adapter_version"),
                "config_schema_hash": r.get("config_schema_hash"),
            }
            for r in rows
        ],
    }


@router.get(
    "",
    response_model=List[ProviderResponse],
    dependencies=[Depends(require_scope("read:events"))],
)
def list_providers(db: Session = Depends(get_db)):
    service = _service(db)
    providers = service.list_providers()
    return [_to_provider_response(provider) for provider in providers]


@router.get(
    "/{provider_id}",
    response_model=ProviderResponse,
    dependencies=[Depends(require_scope("read:events"))],
)
def get_provider(provider_id: str, db: Session = Depends(get_db)):
    service = _service(db)
    try:
        provider = service.get_provider(provider_id)
        return _to_provider_response(provider)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.head(
    "/{provider_id}",
    dependencies=[Depends(require_scope("read:events"))],
)
def head_provider(provider_id: str, response: Response, db: Session = Depends(get_db)):
    """Lightweight header-only endpoint for fingerprint polling.

    Returns 200 with ETag header (fingerprint) if provider exists, 404 otherwise.
    No JSON body is returned (empty response body by FastAPI HEAD semantics).
    """
    service = _service(db)
    try:
        provider = service.get_provider(provider_id)
        if fp := provider.get("config_fingerprint"):
            response.headers["ETag"] = f'W/"{fp}"'
        elif updated_at := provider.get("updated_at"):
            response.headers["ETag"] = f'W/"{updated_at}"'
        return Response(status_code=status.HTTP_200_OK)
    except ProviderNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found"
        )


@router.post(
    "",
    response_model=ProviderResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("write:events"))],
)
def create_provider(
    request: ProviderCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
    _idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    service = _service(db)
    try:
        provider = service.create_provider(
            type_id=request.type_id,
            name=request.name,
            config=request.config,
            enabled=request.enabled,
        )
        response.headers["Location"] = f"/api/v1/providers/{provider['id']}"
        if fp := provider.get("config_fingerprint"):
            response.headers["ETag"] = f'W/"{fp}"'
        # Persist the newly created provider (and any auto-registered provider_type)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        return _to_provider_response(provider)
    except ProviderTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProviderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.put(
    "/{provider_id}",
    response_model=ProviderResponse,
    dependencies=[Depends(require_scope("write:events"))],
)
def update_provider(
    provider_id: str,
    request: ProviderUpdateRequest,
    response: Response,
    db: Session = Depends(get_db),
    _if_match: Optional[str] = Header(None, alias="If-Match"),
):
    service = _service(db)
    try:
        # Concurrency check: If-Match (fingerprint)
        if _if_match:
            # Accept formats: W/"<fp>" or "<fp>" or raw <fp>
            token = _if_match.strip()
            if token.startswith("W/"):
                token = token[2:].strip()
            if token.startswith("\"") and token.endswith("\""):
                token = token[1:-1]
            try:
                current = service.get_provider(provider_id)
                current_fp = current.get("config_fingerprint") or ""
                if current_fp and token and current_fp != token:
                    raise HTTPException(
                        status_code=status.HTTP_412_PRECONDITION_FAILED,
                        detail="Fingerprint mismatch (precondition failed)",
                    )
            except ProviderNotFoundError:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found"
                )

        status_enum = None
        if request.status is not None:
            from ..domain.models import ProviderStatusEnum

            try:
                status_enum = ProviderStatusEnum(request.status)
            except ValueError as exc:  # invalid enum
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                )

        provider = service.update_provider(
            provider_id,
            name=request.name,
            config=request.config if request.config is not None else None,
            enabled=request.enabled,
            status=status_enum,
            status_detail=request.status_detail,
        )
        # Prefer fingerprint-based ETag for optimistic concurrency
        if fp := provider.get("config_fingerprint"):
            response.headers["ETag"] = f'W/"{fp}"'
        elif updated_at := provider.get("updated_at"):
            response.headers["ETag"] = f'W/"{updated_at}"'
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        return _to_provider_response(provider)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProviderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/{provider_id}/test",
    response_model=ProviderResponse,
    dependencies=[Depends(require_scope("write:events"))],
)
async def test_provider_connection(
    provider_id: str,
    db: Session = Depends(get_db),
):
    service = _service(db)
    try:
        provider = await service.test_provider_connection(provider_id)
        db.commit()
        return ProviderResponse(**provider)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete(
    "/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_scope("write:events"))],
)
def delete_provider(provider_id: str, db: Session = Depends(get_db)):
    service = _service(db)
    try:
        service.delete_provider(provider_id)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return None


def _provider_event_service() -> ProviderEventService:
    return ProviderEventService()


def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
    return serialize_datetime(dt)


def _serialize_provider_event(
    event: Event, mapping: Optional[ProviderMapping]
) -> ProviderEventResponse:
    start_at = _format_datetime(event.start_at)
    end_at = _format_datetime(event.end_at)
    updated_at = _format_datetime(event.updated_at)
    created_at = _format_datetime(event.created_at)
    tombstoned = event.tombstoned or (mapping.tombstoned if mapping else False)
    provider_event_id = mapping.provider_uid if mapping else None

    return ProviderEventResponse(
        id=event.id,
        provider_event_id=provider_event_id,
        title=event.title or "",
        start_at=start_at,
        end_at=end_at,
        location=event.location,
        notes=event.notes,
        tombstoned=tombstoned,
        created_at=created_at,
        updated_at=updated_at,
    )


def _get_event_row(
    db: Session, provider_id: str, event_id: str
) -> tuple[Event, ProviderMapping]:
    row = (
        db.query(Event, ProviderMapping)
        .join(ProviderMapping, Event.id == ProviderMapping.orbit_event_id)
        .options(joinedload(ProviderMapping.provider))
        .filter(
            Event.id == event_id,
            ProviderMapping.provider_id == provider_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provider event not found"
        )
    return row


@router.get(
    "/{provider_id}/events",
    response_model=List[ProviderEventResponse],
    dependencies=[Depends(require_scope("read:events"))],
)
def list_provider_events(
    provider_id: str,
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    _ = _service(db).get_provider(provider_id)

    query = (
        db.query(Event, ProviderMapping)
        .join(ProviderMapping, Event.id == ProviderMapping.orbit_event_id)
        .options(joinedload(ProviderMapping.provider))
        .filter(ProviderMapping.provider_id == provider_id)
        .order_by(Event.updated_at.desc(), Event.id.desc())
    )

    if cursor:
        try:
            created_at_str, record_id = cursor.split("::", 1)
            created_at = datetime.fromisoformat(created_at_str.replace("Z", ""))
            query = query.filter(
                (Event.updated_at < created_at)
                | ((Event.updated_at == created_at) & (Event.id < record_id))
            )
        except Exception:
            pass

    rows = query.limit(limit + 1).all()
    next_cursor = None
    if len(rows) > limit:
        last_event, _ = rows[limit - 1]
        cursor_timestamp = _format_datetime(last_event.updated_at)
        if not cursor_timestamp:
            cursor_timestamp = serialize_datetime(datetime.utcnow())
        next_cursor = f"{cursor_timestamp}::{last_event.id}"
        rows = rows[:limit]

    events = [_serialize_provider_event(event, mapping) for event, mapping in rows]
    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor
    return events


@router.get(
    "/{provider_id}/events/{event_id}",
    response_model=ProviderEventResponse,
    dependencies=[Depends(require_scope("read:events"))],
)
def get_provider_event(
    provider_id: str,
    event_id: str,
    db: Session = Depends(get_db),
):
    _ = _service(db).get_provider(provider_id)
    event, mapping = _get_event_row(db, provider_id, event_id)
    return _serialize_provider_event(event, mapping)


@router.post(
    "/{provider_id}/events",
    response_model=ProviderEventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("write:events"))],
)
async def create_provider_event(
    provider_id: str,
    request: ProviderEventCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
    _idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    _ = _service(db).get_provider(provider_id)
    event_service = _provider_event_service()
    operations = OperationService(db)
    try:
        start_dt = datetime.fromisoformat(request.start_at.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(request.end_at.replace("Z", "+00:00"))
        result = await event_service.create_event(
            {
                "title": request.title,
                "start": start_dt,
                "end": end_dt,
                "location": request.location or "",
                "notes": request.notes or "",
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ProviderEventServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    event_id = result.get("id")
    if not event_id:
        raise HTTPException(status_code=500, detail="Event creation failed")

    event, mapping = _get_event_row(db, provider_id, event_id)
    response.headers["Location"] = f"/api/v1/providers/{provider_id}/events/{event_id}"
    operations.create_operation(
        kind="provider_event_create",
        status="succeeded",
        resource_type="provider_event",
        resource_id=event_id,
        result={"provider_id": provider_id, "event_id": event_id},
        finished_at=datetime.utcnow(),
    )
    db.commit()
    return _serialize_provider_event(event, mapping)


@router.patch(
    "/{provider_id}/events/{event_id}",
    response_model=ProviderEventResponse,
    dependencies=[Depends(require_scope("write:events"))],
)
async def update_provider_event(
    provider_id: str,
    event_id: str,
    request: ProviderEventUpdateRequest,
    response: Response,
    db: Session = Depends(get_db),
    _if_match: Optional[str] = Header(None, alias="If-Match"),
):
    _ = _service(db).get_provider(provider_id)
    event_service = _provider_event_service()
    operations = OperationService(db)
    updates: Dict[str, Any] = {}
    if request.title is not None:
        updates["title"] = request.title
    if request.start_at is not None:
        try:
            datetime.fromisoformat(request.start_at.replace("Z", "+00:00"))
            updates["start_at"] = request.start_at
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid start_at: {exc}",
            )
    if request.end_at is not None:
        try:
            datetime.fromisoformat(request.end_at.replace("Z", "+00:00"))
            updates["end_at"] = request.end_at
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid end_at: {exc}",
            )
    if request.location is not None:
        updates["location"] = request.location
    if request.notes is not None:
        updates["notes"] = request.notes

    try:
        await event_service.update_event(event_id, updates)
    except EventNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )
    except ProviderEventServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    event, mapping = _get_event_row(db, provider_id, event_id)
    updated_at = event.updated_at
    if updated_at:
        etag_value = _format_datetime(updated_at)
        if etag_value:
            response.headers["ETag"] = f'W/"{etag_value}"'
    operations.create_operation(
        kind="provider_event_update",
        status="succeeded",
        resource_type="provider_event",
        resource_id=event_id,
        payload=updates,
        result={"provider_id": provider_id, "event_id": event_id},
        finished_at=datetime.utcnow(),
    )
    db.commit()
    return _serialize_provider_event(event, mapping)


@router.delete(
    "/{provider_id}/events/{event_id}",
    response_model=OperationAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_scope("write:events"))],
)
async def delete_provider_event(
    provider_id: str,
    event_id: str,
    db: Session = Depends(get_db),
):
    _ = _service(db).get_provider(provider_id)
    event_service = _provider_event_service()
    operations = OperationService(db)
    record = operations.create_operation(
        kind="provider_event_delete",
        status="queued",
        resource_type="provider_event",
        resource_id=event_id,
        payload={"provider_id": provider_id},
    )
    try:
        await event_service.delete_event(event_id)
        final_record = operations.update(
            record.id,
            status="succeeded",
            result={"provider_id": provider_id, "event_id": event_id},
            finished_at=datetime.utcnow(),
        )
        db.commit()
        return OperationAcceptedResponse(
            operation_id=final_record.id, status=final_record.status
        )
    except EventNotFoundError:
        operations.update(
            record.id,
            status="error",
            error={"message": "Event not found"},
            finished_at=datetime.utcnow(),
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )
    except ProviderEventServiceError as exc:
        operations.update(
            record.id,
            status="error",
            error={"message": str(exc)},
            finished_at=datetime.utcnow(),
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
