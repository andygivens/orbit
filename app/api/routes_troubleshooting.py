"""Troubleshooting-specific API endpoints.

These endpoints intentionally return HTTP 501 until the underlying services
are implemented. The router and data models mirror the contract captured in
`docs/openapi/backend-v1.yaml` so downstream work can plug in business logic
incrementally without reshaping the surface.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.core.logging import logger

router = APIRouter(prefix="/troubleshooting", tags=["troubleshooting"])

sync_router = APIRouter(prefix="/sync", tags=["troubleshooting:sync"])
provider_router = APIRouter(prefix="/provider", tags=["troubleshooting:provider"])
system_router = APIRouter(prefix="/system", tags=["troubleshooting:system"])

RoleLiteral = Literal["source", "target", "mirror", "unknown"]
ActionLiteral = Literal["delete", "tombstone", "ignore"]


class TroubleshootMappingSegment(BaseModel):
    mapping_id: str = Field(..., description="Provider mapping identifier")
    provider_id: str = Field(..., description="Provider configuration identifier")
    provider_type: str = Field(..., description="Provider type identifier")
    provider_uid: str = Field(..., description="Provider-side event UID")
    provider_label: Optional[str] = Field(
        None, description="Human-readable provider label, if available"
    )
    role: Optional[RoleLiteral] = Field(
        None, description="Role of the provider within the sync"
    )
    first_seen_at: Optional[str] = Field(
        None, description="Timestamp when the provider event was first observed"
    )
    last_seen_at: Optional[str] = Field(
        None, description="Timestamp when the provider event was last confirmed"
    )
    created_at: Optional[str] = Field(
        None, description="Timestamp when the provider mapping was created"
    )
    updated_at: Optional[str] = Field(
        None, description="Timestamp when the provider mapping last changed"
    )
    tombstoned: bool = Field(False, description="Whether the provider mapping is tombstoned")
    extra: Optional[dict] = Field(
        None, description="Adapter-specific metadata useful for diagnostics"
    )


class TroubleshootMapping(BaseModel):
    orbit_event_id: str = Field(..., description="Orbit event identifier")
    title: str = Field(..., description="Orbit event title")
    start_at: str = Field(..., description="Orbit event start timestamp")
    end_at: Optional[str] = Field(None, description="Orbit event end timestamp")
    sync_id: Optional[str] = Field(None, description="Sync definition associated with the mapping")
    segments: List[TroubleshootMappingSegment] = Field(
        ..., description="Provider segments linked to the Orbit event"
    )
    last_merged_at: Optional[str] = Field(
        None, description="Last time the Orbit event was merged during sync"
    )
    notes: Optional[str] = Field(None, description="Freeform troubleshooting notes")


class TroubleshootMappingsResponse(BaseModel):
    mappings: List[TroubleshootMapping] = Field(
        default_factory=list,
        description="Collection of mappings scoped to the requested window",
    )


class TroubleshootProviderConfirmationRequest(BaseModel):
    provider_id: str = Field(..., description="Provider configuration identifier")
    provider_uid: str = Field(..., description="Provider-side UID to confirm")
    mapping_id: Optional[str] = Field(
        None, description="Optional provider mapping identifier for faster lookup"
    )
    sync_id: Optional[str] = Field(
        None, description="Optional sync definition identifier for scoping"
    )


class TroubleshootProviderConfirmationResponse(BaseModel):
    status: Literal["confirmed"] = Field(
        "confirmed", description="Outcome of the confirmation request"
    )
    provider_id: str = Field(..., description="Provider configuration identifier")
    provider_uid: str = Field(..., description="Provider-side UID that was confirmed")
    mapping_id: Optional[str] = Field(
        None, description="Provider mapping identifier linked to the UID"
    )
    last_seen_at: Optional[str] = Field(
        None, description="Updated `last_seen_at` timestamp if available"
    )
    operation_id: Optional[str] = Field(
        None, description="Async operation identifier when work is offloaded"
    )


class TroubleshootRecreateRequest(BaseModel):
    mapping_id: str = Field(..., description="Provider mapping identifier to recreate")
    target_provider_id: str = Field(..., description="Provider that should receive the recreation")
    force: bool = Field(
        False, description="Force recreation even if the provider reports the event"
    )
    sync_id: Optional[str] = Field(
        None, description="Optional sync identifier used for provider selection"
    )


class TroubleshootRecreateResponse(BaseModel):
    status: Literal["recreated"] = Field(
        "recreated", description="Outcome of the recreate operation"
    )
    provider_id: str = Field(..., description="Provider configuration identifier")
    provider_uid: str = Field(..., description="Provider-side UID after recreation")
    mapping_id: str = Field(..., description="Provider mapping identifier updated during recreation")
    created_at: Optional[str] = Field(
        None, description="Timestamp when the provider event was created"
    )
    last_seen_at: Optional[str] = Field(
        None, description="Timestamp when the provider event was last confirmed"
    )
    operation_id: Optional[str] = Field(
        None, description="Async operation identifier when recreation is queued"
    )


class TroubleshootDuplicateMapping(BaseModel):
    mapping_id: str = Field(..., description="Provider mapping identifier")
    provider_id: str = Field(..., description="Provider configuration identifier")
    provider_uid: str = Field(..., description="Provider-side UID")
    provider_label: Optional[str] = Field(
        None, description="Human-friendly provider label"
    )
    provider_type: Optional[str] = Field(
        None, description="Provider type identifier"
    )
    last_seen_at: Optional[str] = Field(
        None, description="Timestamp when the provider event was last confirmed"
    )
    etag_or_version: Optional[str] = Field(
        None, description="Provider change token, if returned"
    )
    tombstoned: bool = Field(False, description="Whether the mapping is tombstoned")
    created_at: Optional[str] = Field(
        None, description="Timestamp when the provider mapping was created"
    )
    updated_at: Optional[str] = Field(
        None, description="Timestamp when the provider mapping last changed"
    )


class TroubleshootDuplicateEvent(BaseModel):
    orbit_event_id: Optional[str] = Field(
        None, description="Orbit event identifier for the duplicate entry"
    )
    title: str = Field(..., description="Event title used for deduplication")
    start_at: Optional[str] = Field(None, description="Start timestamp for the event")
    end_at: Optional[str] = Field(None, description="End timestamp for the event")
    location: Optional[str] = Field(None, description="Location associated with the event")
    notes: Optional[str] = Field(None, description="Orbit notes captured on the event")
    provider_ids: Optional[List[str]] = Field(
        None, description="Provider identifiers where the event exists"
    )
    provider_uids: Optional[List[str]] = Field(
        None, description="Provider-specific UIDs for the event"
    )
    created_at: Optional[str] = Field(
        None, description="Timestamp when the Orbit event was created"
    )
    updated_at: Optional[str] = Field(
        None, description="Timestamp when the Orbit event last changed"
    )
    mappings: List[TroubleshootDuplicateMapping] = Field(
        default_factory=list,
        description="Provider mappings associated with the event",
    )


class TroubleshootDuplicateGroup(BaseModel):
    group_id: str = Field(..., description="Identifier for the duplicate group")
    dedupe_key: Optional[str] = Field(
        None, description="Content hash used to detect the duplicate"
    )
    original: TroubleshootDuplicateEvent = Field(
        ..., description="The original Orbit event selected as canonical"
    )
    duplicates: List[TroubleshootDuplicateEvent] = Field(
        default_factory=list, description="Duplicate events that can be resolved"
    )
    created_at: Optional[str] = Field(
        None, description="Timestamp when the duplicate group was computed"
    )


class TroubleshootProviderDuplicateEvent(BaseModel):
    provider_uid: str = Field(..., description="Provider-side event identifier")
    title: str = Field(..., description="Event title as reported by the provider")
    start_at: Optional[str] = Field(
        None, description="Provider event start timestamp"
    )
    end_at: Optional[str] = Field(
        None, description="Provider event end timestamp"
    )
    timezone: Optional[str] = Field(None, description="Provider event timezone")
    orbit_event_id: Optional[str] = Field(
        None, description="Orbit event identifier if a mapping exists"
    )
    mapping_id: Optional[str] = Field(
        None, description="Mapping identifier when the provider event is linked"
    )
    source: Optional[str] = Field(
        None, description="Provider reported source for the event"
    )


class TroubleshootProviderDuplicateGroup(BaseModel):
    group_id: str = Field(..., description="Identifier for the provider duplicate group")
    dedupe_key: Optional[str] = Field(
        None, description="Content hash used to detect the duplicate"
    )
    provider_id: str = Field(..., description="Provider configuration identifier")
    provider_label: Optional[str] = Field(
        None, description="Human-friendly provider label"
    )
    events: List[TroubleshootProviderDuplicateEvent] = Field(
        ..., description="Events detected as duplicates on the provider"
    )


class TroubleshootDuplicatesResponse(BaseModel):
    groups: List[TroubleshootDuplicateGroup] = Field(
        default_factory=list,
        description="Duplicate groups detected in the requested window",
    )
    provider_only_groups: List[TroubleshootProviderDuplicateGroup] = Field(
        default_factory=list,
        description="Provider-only duplicate groups detected in the requested window",
    )


class TroubleshootDuplicateResolveRequest(BaseModel):
    action: ActionLiteral = Field(
        ..., description="Resolution strategy to apply to the duplicate group"
    )


class TroubleshootDuplicateResolveResponse(BaseModel):
    status: Literal["completed"] = Field(
        "completed", description="Outcome of the duplicate resolution"
    )
    group_id: Optional[str] = Field(
        None, description="Duplicate group identifier that was processed"
    )
    operation_id: Optional[str] = Field(
        None, description="Async operation identifier for queued work"
    )


class TroubleshootMissingResolveRequest(BaseModel):
    missing_provider_id: str = Field(
        ..., description="Provider configuration identifier missing the counterpart"
    )
    reason: Optional[str] = Field(
        None, description="Optional note explaining the acknowledgement"
    )
    sync_id: Optional[str] = Field(
        None, description="Optional sync identifier used for auditing"
    )


class TroubleshootMissingResolveResponse(BaseModel):
    status: Literal["acknowledged"] = Field(
        "acknowledged",
        description="Outcome of the missing counterpart acknowledgement",
    )
    mapping_id: str = Field(..., description="Provider mapping identifier that was reviewed")
    missing_provider_id: str = Field(
        ..., description="Provider configuration identifier missing the event"
    )
    orbit_event_id: Optional[str] = Field(
        None, description="Orbit event identifier linked to the mapping"
    )
    operation_id: Optional[str] = Field(
        None, description="Operation identifier recorded for the acknowledgement"
    )


class TroubleshootOrphanActionRequest(BaseModel):
    reason: Optional[str] = Field(
        None, description="Optional note describing the remediation"
    )
    sync_id: Optional[str] = Field(
        None, description="Optional sync identifier used for auditing"
    )


class TroubleshootOrphanActionResponse(BaseModel):
    status: Literal["queued", "acknowledged"] = Field(
        "queued", description="Outcome of the orphan remediation request"
    )
    provider_id: str = Field(..., description="Provider configuration identifier")
    provider_uid: str = Field(..., description="Provider-side event identifier")
    operation_id: Optional[str] = Field(
        None, description="Operation identifier recorded for the remediation"
    )


class TroubleshootProviderEvent(BaseModel):
    orbit_event_id: Optional[str] = Field(
        None, description="Orbit event identifier linked to the provider entry"
    )
    provider_event_id: Optional[str] = Field(
        None, description="Provider-side event identifier"
    )
    provider_id: str = Field(..., description="Provider configuration identifier")
    provider_name: Optional[str] = Field(
        None, description="Human-friendly provider label"
    )
    title: Optional[str] = Field(
        None, description="Event title as stored in Orbit"
    )
    start_at: Optional[str] = Field(
        None, description="Event start timestamp, if available"
    )
    end_at: Optional[str] = Field(
        None, description="Event end timestamp, if available"
    )
    updated_at: Optional[str] = Field(
        None, description="Last update timestamp for the Orbit event"
    )
    provider_last_seen_at: Optional[str] = Field(
        None, description="Timestamp when the provider mapping was last confirmed"
    )
    tombstoned: bool = Field(
        False, description="Whether the provider mapping is marked as tombstoned"
    )


class TroubleshootProviderOrphan(BaseModel):
    provider_event_id: str = Field(
        ..., description="Provider-side event identifier with no Orbit mapping"
    )
    provider_id: str = Field(..., description="Provider configuration identifier")
    provider_name: Optional[str] = Field(
        None, description="Human-friendly provider label"
    )
    title: Optional[str] = Field(
        None, description="Provider-sourced event title"
    )
    start_at: Optional[str] = Field(
        None, description="Provider-sourced start timestamp"
    )
    end_at: Optional[str] = Field(
        None, description="Provider-sourced end timestamp"
    )
    timezone: Optional[str] = Field(
        None, description="Provider-reported timezone"
    )


class TroubleshootProviderEventsResponse(BaseModel):
    events: List[TroubleshootProviderEvent] = Field(
        default_factory=list,
        description="Provider events scoped to the requested window",
    )
    next_cursor: Optional[str] = Field(
        None, description="Cursor token for fetching the next page of results"
    )
    orphans: List[TroubleshootProviderOrphan] = Field(
        default_factory=list,
        description="Provider events that are present remotely but not mapped in Orbit",
    )


try:
    from app.services.troubleshooting_service import (
        InvalidCursorError,
        InvalidWindowError,
        SyncNotFoundError,
        TroubleshootingService,
        TroubleshootingServiceError,
    )
except Exception:  # pragma: no cover - service not available during early bootstrap
    TroubleshootingService = None  # type: ignore
    InvalidWindowError = InvalidCursorError = SyncNotFoundError = TroubleshootingServiceError = Exception  # type: ignore


def _not_implemented() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Troubleshooting work is tracked but not yet implemented",
    )


def get_troubleshooting_service():
    if TroubleshootingService is None:  # pragma: no cover - guard for early bootstrap
        raise _not_implemented()
    return TroubleshootingService()


@sync_router.get(
    "/mappings",
    response_model=TroubleshootMappingsResponse,
    summary="List Orbit and provider mappings for troubleshooting",
)
async def list_troubleshoot_mappings(
    response: Response,
    window: str = Query("7d", description="Activity window filter"),
    future: str = Query("0d", description="Future activity window filter"),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None, description="Opaque cursor for pagination"),
    sync_id: Optional[str] = Query(None, description="Optional sync identifier filter"),
    service = Depends(get_troubleshooting_service),
) -> TroubleshootMappingsResponse:
    try:
        mappings, next_cursor = service.list_mappings(
            window_key=window,
            future_window_key=future,
            limit=limit,
            cursor=cursor,
            sync_id=sync_id,
        )
    except InvalidWindowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidCursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TroubleshootingServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor
    return TroubleshootMappingsResponse(mappings=mappings)


@provider_router.get(
    "/{provider_id}/events",
    response_model=TroubleshootProviderEventsResponse,
    summary="List provider events observed within a window",
)
async def list_troubleshoot_provider_events(
    provider_id: str,
    response: Response,
    window: str = Query("7d", description="Activity window filter"),
    future: str = Query("0d", description="Future activity window filter"),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None, description="Opaque cursor for pagination"),
    sync_id: Optional[str] = Query(None, description="Optional sync identifier filter"),
    service = Depends(get_troubleshooting_service),
) -> TroubleshootProviderEventsResponse:
    try:
        events, next_cursor, orphans = await service.list_provider_events(
            provider_id=provider_id,
            window_key=window,
            future_window_key=future,
            limit=limit,
            cursor=cursor,
            sync_id=sync_id,
        )
    except InvalidWindowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidCursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TroubleshootingServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor
    return TroubleshootProviderEventsResponse(
        events=events,
        next_cursor=next_cursor,
        orphans=orphans,
    )


@provider_router.post(
    "/confirmations",
    response_model=TroubleshootProviderConfirmationResponse,
    summary="Confirm a provider event is still present",
)
async def confirm_troubleshoot_provider_event(
    payload: TroubleshootProviderConfirmationRequest = Body(...),
    service = Depends(get_troubleshooting_service),
) -> TroubleshootProviderConfirmationResponse:
    logger.info(
        "troubleshoot.provider.confirm.request",
        provider_id=payload.provider_id,
        provider_uid=payload.provider_uid,
        mapping_id=payload.mapping_id,
        sync_id=payload.sync_id,
    )
    try:
        result = service.confirm_event(
            provider_id=payload.provider_id,
            provider_uid=payload.provider_uid,
            mapping_id=payload.mapping_id,
            sync_id=payload.sync_id,
        )
    except TroubleshootingServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "troubleshoot.provider.confirm.response",
        provider_id=result.get("provider_id"),
        provider_uid=result.get("provider_uid"),
        mapping_id=result.get("mapping_id"),
    )
    return TroubleshootProviderConfirmationResponse(**result)


@provider_router.post(
    "/recreate",
    response_model=TroubleshootRecreateResponse,
    summary="Recreate an event on a provider from its Orbit mapping",
)
async def recreate_troubleshoot_mapping(
    payload: TroubleshootRecreateRequest = Body(...),
    service = Depends(get_troubleshooting_service),
) -> TroubleshootRecreateResponse:
    logger.info(
        "troubleshoot.provider.recreate.request",
        mapping_id=payload.mapping_id,
        target_provider_id=payload.target_provider_id,
        sync_id=payload.sync_id,
        force=payload.force,
    )
    try:
        result = await service.recreate_event(
            mapping_id=payload.mapping_id,
            target_provider_id=payload.target_provider_id,
            force=payload.force,
            sync_id=payload.sync_id,
        )
    except TroubleshootingServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "troubleshoot.provider.recreate.response",
        provider_id=result.get("provider_id"),
        provider_uid=result.get("provider_uid"),
        mapping_id=result.get("mapping_id"),
        operation_id=result.get("operation_id"),
    )
    return TroubleshootRecreateResponse(**result)


@sync_router.get(
    "/duplicates",
    response_model=TroubleshootDuplicatesResponse,
    summary="Detect potential duplicate events within a window",
)
async def list_troubleshoot_duplicates(
    window: str = Query("7d", description="Activity window filter"),
    future: str = Query("0d", description="Future activity window filter"),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None, description="Opaque cursor for pagination"),
    sync_id: Optional[str] = Query(None, description="Optional sync identifier filter"),
    service = Depends(get_troubleshooting_service),
) -> TroubleshootDuplicatesResponse:
    try:
        groups, next_cursor, provider_only = await service.list_duplicates(
            window_key=window,
            future_window_key=future,
            limit=limit,
            cursor=cursor,
            sync_id=sync_id,
        )
    except InvalidWindowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidCursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SyncNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TroubleshootingServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if next_cursor:
        # Future enhancement: return cursor once pagination implemented
        pass
    return TroubleshootDuplicatesResponse(
        groups=groups,
        provider_only_groups=provider_only,
    )


@sync_router.post(
    "/duplicates/{group_id}/resolve",
    response_model=TroubleshootDuplicateResolveResponse,
    summary="Resolve a duplicate group",
)
async def resolve_troubleshoot_duplicate(
    group_id: str,
    payload: TroubleshootDuplicateResolveRequest = Body(...),
    service = Depends(get_troubleshooting_service),
) -> TroubleshootDuplicateResolveResponse:
    try:
        result = service.resolve_duplicate_group(
            group_id=group_id,
            action=payload.action,
        )
    except TroubleshootingServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return TroubleshootDuplicateResolveResponse(**result)


@sync_router.post(
    "/mappings/{mapping_id}/missing/resolve",
    response_model=TroubleshootMissingResolveResponse,
    summary="Acknowledge missing provider counterpart",
)
async def acknowledge_troubleshoot_missing(
    mapping_id: str,
    payload: TroubleshootMissingResolveRequest = Body(...),
    service = Depends(get_troubleshooting_service),
) -> TroubleshootMissingResolveResponse:
    try:
        result = service.acknowledge_missing_counterpart(
            mapping_id=mapping_id,
            missing_provider_id=payload.missing_provider_id,
            reason=payload.reason,
            sync_id=payload.sync_id,
        )
    except TroubleshootingServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return TroubleshootMissingResolveResponse(**result)


@provider_router.post(
    "/{provider_id}/orphans/{provider_uid}/pull",
    response_model=TroubleshootOrphanActionResponse,
    summary="Pull an orphaned provider event into Orbit",
)
async def pull_troubleshoot_orphan(
    provider_id: str,
    provider_uid: str,
    payload: TroubleshootOrphanActionRequest = Body(default=TroubleshootOrphanActionRequest()),
    service = Depends(get_troubleshooting_service),
) -> TroubleshootOrphanActionResponse:
    try:
        result = await service.pull_orphan(
            provider_id=provider_id,
            provider_uid=provider_uid,
            reason=payload.reason,
            sync_id=payload.sync_id,
        )
    except TroubleshootingServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return TroubleshootOrphanActionResponse(**result)


@provider_router.post(
    "/{provider_id}/orphans/{provider_uid}/delete",
    response_model=TroubleshootOrphanActionResponse,
    summary="Delete an orphaned provider event remotely",
)
async def delete_troubleshoot_orphan(
    provider_id: str,
    provider_uid: str,
    payload: TroubleshootOrphanActionRequest = Body(default=TroubleshootOrphanActionRequest()),
    service = Depends(get_troubleshooting_service),
) -> TroubleshootOrphanActionResponse:
    try:
        result = await service.delete_orphan(
            provider_id=provider_id,
            provider_uid=provider_uid,
            reason=payload.reason,
            sync_id=payload.sync_id,
        )
    except TroubleshootingServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return TroubleshootOrphanActionResponse(**result)


@system_router.get(
    "/status",
    summary="Placeholder troubleshooting system status endpoint",
)
async def troubleshooting_system_status() -> dict:
    raise _not_implemented()


router.include_router(sync_router)
router.include_router(provider_router)
router.include_router(system_router)
