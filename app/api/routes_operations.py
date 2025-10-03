"""Operations API endpoints."""

import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from ..api.auth import require_scope
from ..core.logging import logger
from ..infra.db import get_db
from ..services.operation_service import OperationService

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("", dependencies=[Depends(require_scope("read:events"))])
def list_operations(
    response: Response,
    resource_type: Optional[str] = Query(default=None),
    resource_id: Optional[str] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    db=Depends(get_db),
) -> List[dict]:
    service = OperationService(db)
    records, next_cursor = service.list(
        resource_type=resource_type,
        resource_id=resource_id,
        limit=limit,
        cursor=cursor,
    )
    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor
    return records


def _operation_signature(record: dict) -> str:
    payload = {
        "status": record.get("status"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "result": record.get("result") or {},
        "error": record.get("error") or {},
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _encode_sse(event: str, data: dict) -> bytes:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {body}\n\n".encode("utf-8")


@router.get(
    "/stream",
    dependencies=[Depends(require_scope("read:events"))],
)
async def stream_operations(
    resource_type: Optional[str] = Query(default=None),
    resource_id: Optional[str] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
    limit: int = Query(200, ge=1, le=500),
    poll_interval: float = Query(2.0, ge=0.0, le=30.0),
    db=Depends(get_db),
):
    """Stream operation updates over Server-Sent Events."""

    service = OperationService(db)
    seen_signatures: dict[str, str] = {}
    keepalive = b": keep-alive\n\n"

    async def event_stream():
        try:
            records, _ = service.list(
                resource_type=resource_type,
                resource_id=resource_id,
                limit=limit,
                cursor=cursor,
            )
            for record in records:
                seen_signatures[record["id"]] = _operation_signature(record)
            yield _encode_sse("snapshot", {"operations": records})

            while True:
                await asyncio.sleep(poll_interval if poll_interval > 0 else 0)
                records, _ = service.list(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    limit=limit,
                    cursor=cursor,
                )

                updates_sent = False
                for record in records:
                    signature = _operation_signature(record)
                    if seen_signatures.get(record["id"]) != signature:
                        seen_signatures[record["id"]] = signature
                        updates_sent = True
                        yield _encode_sse("operation", record)

                if not updates_sent:
                    yield keepalive

                if poll_interval <= 0:
                    break
        except asyncio.CancelledError:  # pragma: no cover - connection closed
            logger.debug("Operations stream closed by client")
            raise

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Orbit-Mode": "sse",
    }

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream; charset=utf-8",
        headers=headers,
    )


@router.get("/{operation_id}", dependencies=[Depends(require_scope("read:events"))])
def get_operation(operation_id: str, db=Depends(get_db)) -> dict:
    service = OperationService(db)
    record = service.get(operation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Operation not found")
    return record
