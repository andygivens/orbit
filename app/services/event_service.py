"""Provider event inspection helpers for troubleshooting."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from ..core.logging import logger
from ..domain.models import Event, Provider, ProviderMapping, serialize_datetime


class EventInspectionService:
    """Query raw provider event mappings for troubleshooting flows."""

    def __init__(self, db: Session):
        self.db = db
        self.log = logger.bind(component="event_inspection")

    def list_provider_events(
        self,
        *,
        provider_ids: List[str],
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Tuple[List[dict], Optional[str]]:
        if not provider_ids:
            return [], None

        query = (
            self.db.query(Event, ProviderMapping)
            .join(ProviderMapping, Event.id == ProviderMapping.orbit_event_id)
            .options(joinedload(ProviderMapping.provider))
            .filter(ProviderMapping.provider_id.in_(provider_ids))
            .order_by(Event.updated_at.desc(), Event.id.desc())
        )

        if since:
            query = query.filter(Event.updated_at >= since)
        if until:
            query = query.filter(Event.updated_at <= until)

        if cursor:
            try:
                created_at_str, record_id = cursor.split("::", 1)
                created_at = datetime.fromisoformat(created_at_str.replace("Z", ""))
                query = query.filter(
                    (Event.updated_at < created_at)
                    | (
                        (Event.updated_at == created_at)
                        & (Event.id < record_id)
                    )
                )
            except Exception:
                pass

        rows = query.limit(limit + 1).all()
        results: List[dict] = []
        next_cursor: Optional[str] = None

        for event, mapping in rows[:limit]:
            provider: Optional[Provider] = mapping.provider
            results.append(
                {
                    "orbit_event_id": event.id,
                    "provider_event_id": mapping.provider_uid,
                    "provider_id": mapping.provider_id,
                    "provider_name": provider.name if provider and provider.name else mapping.provider_id,
                    "title": event.title,
                    "start_at": serialize_datetime(event.start_at),
                    "end_at": serialize_datetime(event.end_at),
                    "updated_at": serialize_datetime(event.updated_at),
                    "provider_last_seen_at": serialize_datetime(mapping.last_seen_at),
                    "tombstoned": mapping.tombstoned,
                }
            )

        if len(rows) > limit:
            last_event, _ = rows[limit - 1]
            timestamp_dt = last_event.updated_at
            if timestamp_dt:
                timestamp = serialize_datetime(timestamp_dt)
            else:
                timestamp = serialize_datetime(datetime.utcnow())
            next_cursor = f"{timestamp}::{last_event.id}"

        return results, next_cursor
