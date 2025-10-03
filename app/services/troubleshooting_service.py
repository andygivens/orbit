"""Services supporting the troubleshooting API surface."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import joinedload, selectinload

from app.core.logging import logger
from app.domain.mapping import EventMapper, ProviderEventConverter
from app.domain.models import (
    Event,
    Provider,
    ProviderMapping,
    ProviderTypeEnum,
    serialize_datetime,
)
from app.infra.db import get_db_session
from app.providers.base import ProviderAdapter
from app.providers.registry import ProviderRegistry, provider_registry
from app.services.event_service import EventInspectionService
from app.services.operation_service import OperationService
from app.services.provider_event_service import (
    ProviderEventService,
    ProviderEventServiceError,
    ProviderSnapshot,
)
from app.services.sync_definition_service import SyncDefinitionService

WINDOW_PRESETS: Dict[str, timedelta] = {
    "0d": timedelta(0),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "14d": timedelta(days=14),
    "30d": timedelta(days=30),
}
DEFAULT_WINDOW = "7d"


class TroubleshootingServiceError(Exception):
    """Base exception for troubleshooting service failures."""


class InvalidWindowError(TroubleshootingServiceError):
    """Raised when the requested window preset is unknown."""


class InvalidCursorError(TroubleshootingServiceError):
    """Raised when the cursor token cannot be parsed."""


class SyncNotFoundError(TroubleshootingServiceError):
    """Raised when a referenced sync configuration cannot be located."""


@dataclass
class TroubleshootingService:
    """Coordinator for troubleshooting data access."""

    session_factory: Callable[[], Any] = get_db_session
    now_factory: Callable[[timezone], datetime] = datetime.now
    registry: ProviderRegistry = field(default_factory=lambda: provider_registry)
    converter: ProviderEventConverter = field(default_factory=ProviderEventConverter)

    # ------------------------------------------------------------------
    # Mapping inspection

    def list_mappings(
        self,
        *,
        window_key: str,
        future_window_key: str,
        limit: int,
        cursor: Optional[str],
        sync_id: Optional[str],
    ) -> Tuple[List[dict], Optional[str]]:
        logger.debug(
            "troubleshoot.list_mappings.request",
            window=window_key,
            limit=limit,
            cursor=cursor,
            sync_id=sync_id,
        )

        start_at, end_at = self._resolve_window(window_key, future_window_key)

        with self.session_factory() as session:
            provider_filter: Optional[set[str]] = None
            if sync_id:
                definition_service = SyncDefinitionService(session)
                definition = definition_service.get_sync(sync_id)
                if not definition:
                    raise SyncNotFoundError(f"Sync '{sync_id}' not found")
                provider_filter = {
                    endpoint.provider_id for endpoint in definition.endpoints
                }

            try:
                query = (
                    session.query(Event)
                    .options(
                        selectinload(Event.provider_mappings).selectinload(
                            ProviderMapping.provider
                        )
                    )
                    .filter(
                        Event.start_at >= start_at,
                        Event.start_at <= end_at,
                        Event.tombstoned.is_(False),
                    )
                )
            except OperationalError as exc:
                raise TroubleshootingServiceError(
                    "Troubleshooting requires the upgraded event schema (start_at column). "
                    "Drop orbit.db or apply migrations and restart."
                ) from exc

            if provider_filter:
                query = query.filter(
                    Event.provider_mappings.any(
                        ProviderMapping.provider_id.in_(provider_filter)
                    )
                )

            if cursor:
                cursor_dt, cursor_event_id = self._decode_cursor(cursor)
                query = query.filter(
                    or_(
                        Event.start_at < cursor_dt,
                        and_(Event.start_at == cursor_dt, Event.id < cursor_event_id),
                    )
                )

            query = query.order_by(Event.start_at.desc(), Event.id.desc())
            try:
                events: List[Event] = query.limit(limit + 1).all()
            except OperationalError as exc:
                raise TroubleshootingServiceError(
                    "Unable to load events for troubleshooting. Schema may be outdated."
                ) from exc

            next_cursor: Optional[str] = None
            if len(events) > limit:
                next_marker = events[limit]
                next_cursor = self._encode_cursor(next_marker)
                events = events[:limit]

            payload = self._serialize_events(events, provider_filter, sync_id)

        logger.debug(
            "troubleshoot.list_mappings.response",
            count=len(payload),
            next_cursor=next_cursor,
        )
        return payload, next_cursor

    # ------------------------------------------------------------------
    # Provider confirmations / recreation

    def confirm_event(
        self,
        *,
        provider_id: str,
        provider_uid: str,
        mapping_id: Optional[str] = None,
        sync_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self.session_factory() as session:
            mapping = self._find_mapping(
                session,
                provider_id=provider_id,
                provider_uid=provider_uid,
                mapping_id=mapping_id,
                sync_id=sync_id,
            )
            if not mapping:
                raise TroubleshootingServiceError("Mapping not found for confirmation")

            provider_service = ProviderEventService()
            confirmation = provider_service.confirm_event(provider_id, provider_uid)

            if not confirmation.get("exists", False):
                raise TroubleshootingServiceError("Provider did not confirm the event")

            now = self.now_factory(timezone.utc)
            mapping.last_seen_at = now
            session.add(mapping)
            session.commit()

            segment = self._serialize_segment(mapping)
            segment["last_seen_at"] = serialize_datetime(mapping.last_seen_at)

        return {
            "status": "confirmed",
            "provider_id": provider_id,
            "provider_uid": provider_uid,
            "mapping_id": mapping.id,
            "last_seen_at": segment["last_seen_at"],
        }

    async def recreate_event(
        self,
        *,
        mapping_id: str,
        target_provider_id: str,
        force: bool,
        sync_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        operation_id: Optional[str] = None
        started_at = self.now_factory(timezone.utc)

        with self.session_factory() as session:
            operations = OperationService(session)
            operation = operations.create_operation(
                kind="troubleshoot_mapping_recreate",
                status="running",
                resource_type="provider_mapping",
                resource_id=mapping_id,
                payload={
                    "target_provider_id": target_provider_id,
                    "force": force,
                    "sync_id": sync_id,
                },
                started_at=started_at,
            )
            operation_id = operation.id

        try:
            result = await ProviderEventService().recreate_mapping(
                mapping_id=mapping_id,
                target_provider_id=target_provider_id,
                force=force,
            )
        except ProviderEventServiceError as exc:
            finished_at = self.now_factory(timezone.utc)
            with self.session_factory() as session:
                operations = OperationService(session)
                operations.update(
                    operation_id,
                    status="failed",
                    error={"message": str(exc)},
                    finished_at=finished_at,
                )
            raise TroubleshootingServiceError(str(exc)) from exc

        finished_at = self.now_factory(timezone.utc)
        with self.session_factory() as session:
            operations = OperationService(session)
            operations.update(
                operation_id,
                status="succeeded",
                result={
                    "provider_id": result.get("provider_id"),
                    "provider_uid": result.get("provider_uid"),
                    "mapping_id": mapping_id,
                },
                finished_at=finished_at,
            )

        result["operation_id"] = operation_id
        return result

    # ------------------------------------------------------------------
    # Provider event inspection

    async def list_provider_events(
        self,
        *,
        provider_id: str,
        window_key: str,
        future_window_key: str,
        limit: int,
        cursor: Optional[str],
        sync_id: Optional[str],
    ) -> Tuple[List[dict], Optional[str], List[dict]]:
        logger.debug(
            "troubleshoot.list_provider_events.request",
            provider_id=provider_id,
            window=window_key,
            limit=limit,
            cursor=cursor,
            sync_id=sync_id,
        )

        start_at, end_at = self._resolve_window(window_key, future_window_key)
        start_iso = serialize_datetime(start_at)
        end_iso = serialize_datetime(end_at)

        with self.session_factory() as session:
            provider = (
                session.query(Provider)
                .filter(Provider.id == provider_id)
                .first()
            )
            if not provider:
                raise TroubleshootingServiceError(
                    f"Provider '{provider_id}' not found"
                )
            provider_snapshot = self._snapshot_provider(provider)

            operations_service = OperationService(session)
            operation_record = operations_service.create_operation(
                kind="troubleshoot_provider_query",
                status="running",
                resource_type="provider",
                resource_id=provider_id,
                payload={
                    "window": window_key,
                    "future": future_window_key,
                    "limit": limit,
                    "cursor": cursor,
                    "sync_id": sync_id,
                },
                started_at=started_at,
            )
            operation_id = operation_record.id

            mapping_lookup = {
                (row.provider_id, row.provider_uid): {
                    "mapping_id": row.id,
                    "orbit_event_id": row.orbit_event_id,
                }
                for row in (
                    session.query(ProviderMapping)
                    .filter(ProviderMapping.provider_id == provider_id)
                    .all()
                )
            }

            if sync_id:
                definition_service = SyncDefinitionService(session)
                definition = definition_service.get_sync(sync_id)
                if not definition:
                    raise SyncNotFoundError(f"Sync '{sync_id}' not found")
                provider_ids = {endpoint.provider_id for endpoint in definition.endpoints}
                if provider_id not in provider_ids:
                    raise TroubleshootingServiceError(
                        "Provider is not associated with the requested sync"
                    )

            inspection = EventInspectionService(session)
            events, next_cursor = inspection.list_provider_events(
                provider_ids=[provider_id],
                since=start_at,
                until=end_at,
                limit=limit,
                cursor=cursor,
            )

        mapped_uids = {
            entry.get("provider_event_id")
            for entry in events
            if entry.get("provider_event_id")
        }

        orphans: List[dict] = []
        try:
            raw_events = await self._fetch_provider_window(provider_snapshot, start_iso, end_iso)
        except TroubleshootingServiceError as exc:
            fetch_error = str(exc)
            raw_events = []

        for raw in raw_events:
            canonical = self._to_canonical(provider_snapshot, raw)
            if not canonical:
                continue
            provider_uid = canonical.get("provider_uid") or canonical.get("uid")
            if not provider_uid:
                continue
            uid_text = str(provider_uid)
            if uid_text in mapped_uids:
                continue
            mapping = mapping_lookup.get((provider_snapshot.id, uid_text))
            orphans.append(
                {
                    "provider_event_id": uid_text,
                    "provider_id": provider_snapshot.id,
                    "provider_name": provider_snapshot.name,
                    "title": canonical.get("title") or canonical.get("summary"),
                    "start_at": self._serialize_optional_datetime(
                        canonical.get("start")
                        or canonical.get("start_at")
                        or canonical.get("start_time")
                    ),
                    "end_at": self._serialize_optional_datetime(
                        canonical.get("end")
                        or canonical.get("end_at")
                        or canonical.get("end_time")
                    ),
                    "timezone": canonical.get("timezone"),
                    "mapping_id": mapping.get("mapping_id") if mapping else None,
                    "orbit_event_id": mapping.get("orbit_event_id") if mapping else None,
                }
            )

        logger.debug(
            "troubleshoot.list_provider_events.response",
            count=len(events),
            orphans=len(orphans),
            next_cursor=next_cursor,
        )

        if operation_id:
            finished_at = self.now_factory(timezone.utc)
            with self.session_factory() as session:
                operations_service = OperationService(session)
                if fetch_error:
                    operations_service.update(
                        operation_id,
                        status="failed",
                        error={"message": fetch_error},
                        finished_at=finished_at,
                    )
                else:
                    operations_service.update(
                        operation_id,
                        status="succeeded",
                        result={
                            "events": len(events),
                            "orphans": len(orphans),
                            "provider_id": provider_id,
                        },
                        finished_at=finished_at,
                    )

        return events, next_cursor, orphans

    # ------------------------------------------------------------------
    # Duplicate detection

    async def list_duplicates(
        self,
        *,
        window_key: str,
        future_window_key: str,
        limit: int,
        cursor: Optional[str],
        sync_id: Optional[str],
    ) -> Tuple[List[dict], Optional[str], List[dict]]:
        logger.debug(
            "troubleshoot.list_duplicates.request",
            window=window_key,
            future_window=future_window_key,
            limit=limit,
            cursor=cursor,
            sync_id=sync_id,
        )

        start_at, end_at = self._resolve_window(window_key, future_window_key)
        start_iso = serialize_datetime(start_at)
        end_iso = serialize_datetime(end_at)

        mapper = EventMapper()
        orbit_groups: Dict[str, List[dict]] = {}
        provider_lookup: Dict[str, ProviderSnapshot] = {}
        mapping_lookup: Dict[Tuple[str, str], Dict[str, Any]] = {}

        with self.session_factory() as session:
            provider_filter: Optional[set[str]] = None
            if sync_id:
                definition_service = SyncDefinitionService(session)
                definition = definition_service.get_sync(sync_id)
                if not definition:
                    raise SyncNotFoundError(f"Sync '{sync_id}' not found")
                provider_filter = {
                    endpoint.provider_id for endpoint in definition.endpoints
                }

            try:
                query = (
                    session.query(Event)
                    .options(
                        selectinload(Event.provider_mappings).selectinload(
                            ProviderMapping.provider
                        )
                    )
                    .filter(
                        Event.start_at >= start_at,
                        Event.start_at <= end_at,
                        Event.tombstoned.is_(False),
                    )
                    .filter(Event.provider_mappings.any())
                )
            except OperationalError as exc:
                raise TroubleshootingServiceError(
                    "Troubleshooting requires the upgraded event schema (start_at column). "
                    "Drop orbit.db or apply migrations and restart."
                ) from exc

            if provider_filter:
                query = query.filter(
                    Event.provider_mappings.any(
                        ProviderMapping.provider_id.in_(provider_filter)
                    )
                )

            try:
                events = query.all()
            except OperationalError as exc:
                raise TroubleshootingServiceError(
                    "Unable to load events for troubleshooting. Schema may be outdated."
                ) from exc

            provider_ids_from_events: set[str] = set()

            for event in events:
                if not event.start_at or not event.title:
                    continue

                mapping_records: List[dict] = []
                mapping_ids: List[str] = []
                provider_ids: List[str] = []
                provider_uids: List[str] = []

                for mapping in event.provider_mappings:
                    if mapping.tombstoned:
                        continue
                    if provider_filter and mapping.provider_id not in provider_filter:
                        continue
                    mapping_records.append(self._serialize_duplicate_mapping(mapping))
                    mapping_ids.append(mapping.id)
                    provider_ids.append(mapping.provider_id)
                    provider_uids.append(mapping.provider_uid)
                    provider_ids_from_events.add(mapping.provider_id)
                    mapping_lookup[(mapping.provider_id, mapping.provider_uid)] = {
                        "id": mapping.id,
                        "provider_id": mapping.provider_id,
                        "provider_uid": mapping.provider_uid,
                        "orbit_event_id": mapping.orbit_event_id,
                        "provider_label": mapping.provider.name if mapping.provider and mapping.provider.name else mapping.provider_id,
                    }

                if not mapping_records:
                    continue

                dedupe_key = mapper.create_dedup_key(event.title, event.start_at)
                orbit_groups.setdefault(dedupe_key, []).append(
                    {
                        "orbit_event_id": event.id,
                        "title": event.title,
                        "start_at": event.start_at,
                        "end_at": event.end_at,
                        "location": event.location,
                        "notes": event.notes,
                        "provider_ids": provider_ids,
                        "provider_uids": provider_uids,
                        "mapping_ids": mapping_ids,
                        "mappings": mapping_records,
                        "created_at": event.created_at,
                        "updated_at": event.updated_at,
                    }
                )

            if provider_filter:
                provider_ids = set(provider_filter)
            else:
                provider_ids = set(provider_ids_from_events)
                if not provider_ids:
                    provider_ids = {
                        row[0]
                        for row in session.query(Provider.id).all()
                    }

            if provider_ids:
                providers = (
                    session.query(Provider)
                    .filter(Provider.id.in_(provider_ids))
                    .all()
                )
                for provider in providers:
                    provider_lookup[provider.id] = self._snapshot_provider(provider)

        duplicate_groups: List[dict] = []
        for dedupe_key, items in orbit_groups.items():
            if len(items) < 2:
                continue

            sorted_items = sorted(
                items,
                key=lambda item: item["created_at"] or item["start_at"],
            )

            mapping_ids = sorted({mid for item in sorted_items for mid in item["mapping_ids"]})
            primary_mapping_ids = sorted(set(sorted_items[0]["mapping_ids"]))
            duplicate_mapping_ids = sorted(
                {
                    mid
                    for item in sorted_items[1:]
                    for mid in item["mapping_ids"]
                }
            )

            encoded_group_id = self._encode_group_token(
                {
                    "key": dedupe_key,
                    "mapping_ids": mapping_ids,
                    "primary_mapping_ids": primary_mapping_ids,
                    "duplicate_mapping_ids": duplicate_mapping_ids,
                    "orbit_event_id": sorted_items[0]["orbit_event_id"],
                }
            )

            duplicate_groups.append(
                {
                    "group_id": encoded_group_id,
                    "dedupe_key": dedupe_key,
                    "original": self._serialize_duplicate_event(sorted_items[0]),
                    "duplicates": [
                        self._serialize_duplicate_event(item) for item in sorted_items[1:]
                    ],
                    "created_at": serialize_datetime(sorted_items[0]["created_at"]),
                }
            )

        duplicate_groups = duplicate_groups[:limit]

        provider_duplicate_map: Dict[Tuple[str, str], List[dict]] = {}
        if provider_lookup:
            for provider_id, snapshot in provider_lookup.items():
                try:
                    raw_events = await self._fetch_provider_window(snapshot, start_iso, end_iso)
                except TroubleshootingServiceError:
                    continue

                for raw in raw_events:
                    canonical = self._to_canonical(snapshot, raw)
                    if not canonical:
                        continue
                    title = (canonical.get("title") or "").strip()
                    start = canonical.get("start") or canonical.get("start_at")
                    if not title or not start:
                        continue

                    dedupe_key = mapper.create_dedup_key(title, start)
                    provider_uid = canonical.get("provider_uid") or canonical.get("uid")
                    if not provider_uid:
                        continue

                    mapping = mapping_lookup.get((provider_id, str(provider_uid)))
                    entry = {
                        "provider_uid": str(provider_uid),
                        "title": title,
                        "start_at": self._serialize_optional_datetime(start),
                        "end_at": self._serialize_optional_datetime(
                            canonical.get("end") or canonical.get("end_at")
                        ),
                        "timezone": canonical.get("timezone"),
                        "orbit_event_id": mapping.get("orbit_event_id") if mapping else None,
                        "mapping_id": mapping.get("id") if mapping else None,
                        "provider_id": provider_id,
                        "provider_label": (
                            mapping.get("provider_label")
                            if mapping and mapping.get("provider_label")
                            else snapshot.name if snapshot and snapshot.name else provider_id
                        ),
                        "source": canonical.get("source"),
                    }
                    provider_duplicate_map.setdefault((dedupe_key, provider_id), []).append(entry)

        provider_only_groups: List[dict] = []
        for (dedupe_key, provider_id), entries in provider_duplicate_map.items():
            if len(entries) < 2:
                continue
            provider_snapshot = provider_lookup.get(provider_id)
            provider_only_groups.append(
                {
                    "group_id": self._encode_provider_group_token(
                        dedupe_key, provider_id, [e["provider_uid"] for e in entries]
                    ),
                    "dedupe_key": dedupe_key,
                    "provider_id": provider_id,
                    "provider_label": provider_snapshot.name if provider_snapshot and provider_snapshot.name else provider_id,
                    "events": entries,
                }
            )

        logger.debug(
            "troubleshoot.list_duplicates.response",
            orbit_groups=len(duplicate_groups),
            provider_groups=len(provider_only_groups),
        )
        return duplicate_groups, None, provider_only_groups

    def resolve_duplicate_group(
        self,
        *,
        group_id: str,
        action: str,
    ) -> Dict[str, Any]:
        logger.debug(
            "troubleshoot.resolve_duplicate.request",
            group_id=group_id,
            action=action,
        )

        payload = self._decode_group_token(group_id)
        dedupe_key = payload.get("key")
        primary_mapping_ids = set(payload.get("primary_mapping_ids", []))
        duplicate_mapping_ids = set(payload.get("duplicate_mapping_ids", []))
        all_mapping_ids = set(payload.get("mapping_ids", []))

        if not all_mapping_ids:
            raise TroubleshootingServiceError("Duplicate group is empty")

        if action not in {"delete", "tombstone", "ignore"}:
            raise TroubleshootingServiceError(f"Unsupported action '{action}'")

        if duplicate_mapping_ids:
            target_ids = duplicate_mapping_ids
        else:
            target_ids = all_mapping_ids - primary_mapping_ids

        now = self.now_factory(timezone.utc)

        with self.session_factory() as session:
            mappings = (
                session.query(ProviderMapping)
                .options(joinedload(ProviderMapping.provider))
                .filter(ProviderMapping.id.in_(all_mapping_ids))
                .all()
            )

            mapping_by_id = {mapping.id: mapping for mapping in mappings}
            missing = all_mapping_ids - set(mapping_by_id.keys())
            if missing:
                raise TroubleshootingServiceError(
                    f"Mappings missing for duplicate group: {sorted(missing)}"
                )

            kept_mappings = [mapping_by_id[mid] for mid in primary_mapping_ids if mid in mapping_by_id]
            target_mappings = [mapping_by_id[mid] for mid in target_ids if mid in mapping_by_id]

            tombstoned: List[dict] = []
            if action in {"delete", "tombstone"}:
                for mapping in target_mappings:
                    if not mapping.tombstoned:
                        mapping.tombstoned = True
                        mapping.updated_at = now
                        session.add(mapping)
                    tombstoned.append(self._serialize_duplicate_mapping(mapping))
            else:
                tombstoned = [self._serialize_duplicate_mapping(mapping) for mapping in target_mappings]

            kept = [self._serialize_duplicate_mapping(mapping) for mapping in kept_mappings]

            operation_status = "queued" if action == "delete" else "succeeded"
            finished_at = None if action == "delete" else now

            operations = OperationService(session)
            record = operations.create_operation(
                kind="troubleshoot_duplicate_resolve",
                status=operation_status,
                resource_type="troubleshoot_duplicate_group",
                resource_id=dedupe_key,
                payload={
                    "group_id": group_id,
                    "action": action,
                    "targets": tombstoned,
                    "kept": kept,
                },
                result={
                    "tombstoned_count": len(tombstoned),
                    "kept_count": len(kept),
                    "dedupe_key": dedupe_key,
                },
                started_at=now,
                finished_at=finished_at,
            )
            operation_id = record.id

        logger.debug(
            "troubleshoot.resolve_duplicate.response",
            group_id=group_id,
            action=action,
            operation_id=operation_id,
        )

        return {
            "status": "completed",
            "group_id": group_id,
            "operation_id": operation_id,
        }

    # ------------------------------------------------------------------
    # Missing counterpart acknowledgement & orphan remediations

    def acknowledge_missing_counterpart(
        self,
        *,
        mapping_id: str,
        missing_provider_id: str,
        reason: Optional[str],
        sync_id: Optional[str],
    ) -> Dict[str, Any]:
        logger.debug(
            "troubleshoot.missing_resolve.request",
            mapping_id=mapping_id,
            missing_provider_id=missing_provider_id,
            sync_id=sync_id,
        )

        now = self.now_factory(timezone.utc)

        with self.session_factory() as session:
            mapping = (
                session.query(ProviderMapping)
                .options(joinedload(ProviderMapping.provider))
                .filter(ProviderMapping.id == mapping_id)
                .first()
            )
            if not mapping:
                raise TroubleshootingServiceError(
                    f"Mapping '{mapping_id}' not found for acknowledgement"
                )

            orbit_event_id = mapping.orbit_event_id

            operations = OperationService(session)
            record = operations.create_operation(
                kind="troubleshoot_missing_resolve",
                status="succeeded",
                resource_type="provider_mapping",
                resource_id=mapping_id,
                payload={
                    "mapping_id": mapping_id,
                    "orbit_event_id": mapping.orbit_event_id,
                    "missing_provider_id": missing_provider_id,
                    "sync_id": sync_id,
                    "reason": reason,
                },
                result={"acknowledged": True},
                started_at=now,
                finished_at=now,
            )
            operation_id = record.id

        return {
            "status": "acknowledged",
            "mapping_id": mapping_id,
            "missing_provider_id": missing_provider_id,
            "orbit_event_id": orbit_event_id,
            "operation_id": operation_id,
        }

    async def pull_orphan(
        self,
        *,
        provider_id: str,
        provider_uid: str,
        reason: Optional[str],
        sync_id: Optional[str],
    ) -> Dict[str, Any]:
        logger.debug(
            "troubleshoot.orphan.pull.request",
            provider_id=provider_id,
            provider_uid=provider_uid,
            sync_id=sync_id,
        )

        now = self.now_factory(timezone.utc)

        with self.session_factory() as session:
            provider = session.query(Provider).filter(Provider.id == provider_id).first()
            if not provider:
                raise TroubleshootingServiceError(
                    f"Provider '{provider_id}' not found"
                )

            operations = OperationService(session)
            record = operations.create_operation(
                kind="troubleshoot_orphan_pull",
                status="queued",
                resource_type="provider_orphan",
                resource_id=f"{provider_id}:{provider_uid}",
                payload={
                    "provider_id": provider_id,
                    "provider_uid": provider_uid,
                    "sync_id": sync_id,
                    "reason": reason,
                },
                started_at=now,
            )
            operation_id = record.id

        return {
            "status": "queued",
            "provider_id": provider_id,
            "provider_uid": provider_uid,
            "operation_id": operation_id,
        }

    async def delete_orphan(
        self,
        *,
        provider_id: str,
        provider_uid: str,
        reason: Optional[str],
        sync_id: Optional[str],
    ) -> Dict[str, Any]:
        logger.debug(
            "troubleshoot.orphan.delete.request",
            provider_id=provider_id,
            provider_uid=provider_uid,
            sync_id=sync_id,
        )

        now = self.now_factory(timezone.utc)

        with self.session_factory() as session:
            provider = session.query(Provider).filter(Provider.id == provider_id).first()
            if not provider:
                raise TroubleshootingServiceError(
                    f"Provider '{provider_id}' not found"
                )

            operations = OperationService(session)
            record = operations.create_operation(
                kind="troubleshoot_orphan_delete",
                status="queued",
                resource_type="provider_orphan",
                resource_id=f"{provider_id}:{provider_uid}",
                payload={
                    "provider_id": provider_id,
                    "provider_uid": provider_uid,
                    "sync_id": sync_id,
                    "reason": reason,
                },
                started_at=now,
            )
            operation_id = record.id

        return {
            "status": "queued",
            "provider_id": provider_id,
            "provider_uid": provider_uid,
            "operation_id": operation_id,
        }

    # ------------------------------------------------------------------
    # Helpers

    def _resolve_window(
        self,
        window_key: str,
        future_key: Optional[str] = None,
    ) -> Tuple[datetime, datetime]:
        past_token = window_key or DEFAULT_WINDOW
        if past_token not in WINDOW_PRESETS:
            raise InvalidWindowError(f"Unsupported window '{window_key}'")

        future_token = future_key or "0d"
        if future_token not in WINDOW_PRESETS:
            raise InvalidWindowError(f"Unsupported future window '{future_key}'")

        past_delta = WINDOW_PRESETS[past_token]
        future_delta = WINDOW_PRESETS[future_token]
        midpoint = self.now_factory(timezone.utc)
        start = midpoint - past_delta
        end = midpoint + future_delta
        return start, end

    def _snapshot_provider(self, provider: Provider) -> ProviderSnapshot:
        type_id = provider.type_id
        if not type_id and provider.type:
            type_id = provider.type.value
        if not type_id:
            raise TroubleshootingServiceError(
                f"Provider '{provider.id}' is missing a type identifier"
            )
        return ProviderSnapshot(
            id=provider.id,
            type_id=type_id,
            config=dict(provider.config or {}),
            name=provider.name,
        )

    async def _fetch_provider_window(
        self,
        provider: ProviderSnapshot,
        start_iso: str,
        end_iso: str,
    ) -> List[dict]:
        adapter: Optional[ProviderAdapter] = None
        try:
            adapter = self.registry.create(provider.type_id, provider.id, provider.config or {})
            await adapter.initialize()
            raw_events = await adapter.list_events(start_iso, end_iso)
            return list(raw_events or [])
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "troubleshoot.provider.fetch_failed",
                provider_id=provider.id,
                error=str(exc),
            )
            raise TroubleshootingServiceError("Unable to query provider events") from exc
        finally:
            if adapter:
                try:
                    await adapter.close()
                except Exception:  # pragma: no cover - cleanup best-effort
                    pass

    def _to_canonical(self, provider: ProviderSnapshot, raw_event: dict) -> Optional[dict]:
        type_id = provider.type_id
        try:
            provider_type = (
                ProviderTypeEnum(type_id)
                if not isinstance(type_id, ProviderTypeEnum)
                else type_id
            )
        except ValueError:
            return None

        try:
            if provider_type == ProviderTypeEnum.APPLE_CALDAV:
                return self.converter.apple_to_canonical(raw_event)
            if provider_type == ProviderTypeEnum.SKYLIGHT:
                return self.converter.skylight_to_canonical(raw_event)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "troubleshoot.provider.canonical_failed",
                provider_id=provider.id,
                provider_type=provider_type.value,
                error=str(exc),
            )
        return None

    @staticmethod
    def _serialize_optional_datetime(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return serialize_datetime(dt)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return serialize_datetime(parsed)
            except ValueError:
                return value
        return str(value)

    def _decode_cursor(self, token: str) -> Tuple[datetime, str]:
        try:
            timestamp, event_id = token.split("::", 1)
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt, event_id
        except Exception as exc:  # pragma: no cover - defensive
            raise InvalidCursorError("Cursor token is invalid") from exc

    @staticmethod
    def _encode_cursor(event: Event) -> str:
        return f"{serialize_datetime(event.start_at)}::{event.id}"

    def _serialize_events(
        self,
        events: Iterable[Event],
        provider_filter: Optional[set[str]],
        sync_id: Optional[str],
    ) -> List[dict]:
        payload: List[dict] = []
        for event in events:
            segments = []
            for provider_mapping in event.provider_mappings:
                if provider_filter and provider_mapping.provider_id not in provider_filter:
                    continue
                segments.append(self._serialize_segment(provider_mapping))

            if not segments:
                continue

            payload.append(
                {
                    "orbit_event_id": event.id,
                    "title": event.title,
                    "start_at": serialize_datetime(event.start_at),
                    "end_at": serialize_datetime(event.end_at),
                    "sync_id": sync_id,
                    "segments": segments,
                    "last_merged_at": None,
                    "notes": None,
                }
            )
        return payload

    @staticmethod
    def _serialize_segment(mapping: ProviderMapping) -> dict:
        provider_label = None
        if mapping.provider and mapping.provider.name:
            provider_label = mapping.provider.name
        elif mapping.provider:
            provider_label = mapping.provider.id

        extra = {"etag_or_version": mapping.etag_or_version} if mapping.etag_or_version else None

        provider_label = provider_label or mapping.provider_id

        return {
            "mapping_id": mapping.id,
            "provider_id": mapping.provider_id,
            "provider_type": mapping.provider_type.value if mapping.provider_type else None,
            "provider_uid": mapping.provider_uid,
            "provider_label": provider_label,
            "role": "unknown",
            "first_seen_at": serialize_datetime(mapping.created_at),
            "last_seen_at": serialize_datetime(mapping.last_seen_at),
            "created_at": serialize_datetime(mapping.created_at),
            "updated_at": serialize_datetime(mapping.updated_at),
            "tombstoned": bool(mapping.tombstoned),
            "extra": extra,
        }

    @staticmethod
    def _serialize_duplicate_mapping(mapping: ProviderMapping) -> dict:
        provider_label = None
        if mapping.provider and mapping.provider.name:
            provider_label = mapping.provider.name
        elif mapping.provider:
            provider_label = mapping.provider.id
        provider_label = provider_label or mapping.provider_id

        return {
            "mapping_id": mapping.id,
            "provider_id": mapping.provider_id,
            "provider_uid": mapping.provider_uid,
            "provider_label": provider_label,
            "provider_type": mapping.provider_type.value if mapping.provider_type else None,
            "last_seen_at": serialize_datetime(mapping.last_seen_at),
            "etag_or_version": mapping.etag_or_version,
            "tombstoned": bool(mapping.tombstoned),
            "created_at": serialize_datetime(mapping.created_at),
            "updated_at": serialize_datetime(mapping.updated_at),
        }

    @staticmethod
    def _serialize_duplicate_event(item: dict) -> dict:
        return {
            "orbit_event_id": item.get("orbit_event_id"),
            "title": item.get("title"),
            "start_at": serialize_datetime(item.get("start_at")),
            "end_at": serialize_datetime(item.get("end_at")),
            "location": item.get("location"),
            "notes": item.get("notes"),
            "created_at": serialize_datetime(item.get("created_at")),
            "updated_at": serialize_datetime(item.get("updated_at")),
            "provider_ids": item.get("provider_ids"),
            "provider_uids": item.get("provider_uids"),
            "mappings": item.get("mappings", []),
        }

    @staticmethod
    def _encode_group_token(data: Dict[str, Any]) -> str:
        raw = json.dumps(data, sort_keys=True).encode()
        token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        return f"dup:{token}"

    @staticmethod
    def _decode_group_token(group_id: str) -> Dict[str, Any]:
        if not group_id.startswith("dup:"):
            raise TroubleshootingServiceError("Duplicate group identifier is invalid")
        token = group_id[len("dup:") :]
        padding = "=" * (-len(token) % 4)
        try:
            raw = base64.urlsafe_b64decode(token + padding)
            data = json.loads(raw.decode())
            if not isinstance(data, dict):
                raise ValueError("Group payload must be an object")
            return data
        except (ValueError, json.JSONDecodeError) as exc:
            raise TroubleshootingServiceError("Duplicate group identifier cannot be parsed") from exc

    @staticmethod
    def _encode_provider_group_token(
        dedupe_key: str,
        provider_id: str,
        provider_uids: Iterable[str],
    ) -> str:
        payload = {
            "key": dedupe_key,
            "provider_id": provider_id,
            "provider_uids": sorted(provider_uids),
        }
        raw = json.dumps(payload, sort_keys=True).encode()
        token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        return f"provdup:{token}"

    @staticmethod
    def _find_mapping(
        session,
        *,
        provider_id: str,
        provider_uid: str,
        mapping_id: Optional[str],
        sync_id: Optional[str],
    ) -> Optional[ProviderMapping]:
        query = (
            session.query(ProviderMapping)
            .options(joinedload(ProviderMapping.provider), joinedload(ProviderMapping.event))
            .filter(
                ProviderMapping.provider_id == provider_id,
                ProviderMapping.provider_uid == provider_uid,
            )
        )

        if mapping_id:
            query = query.filter(ProviderMapping.id == mapping_id)

        mapping = query.first()

        if mapping and sync_id:
            event = mapping.event
            if event and getattr(event, "sync_id", None) not in (None, sync_id):
                return None

        return mapping
