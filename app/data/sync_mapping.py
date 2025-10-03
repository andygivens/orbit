"""Database helpers for provider event mappings."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.domain.models import (
    Event,
    Provider,
    ProviderEnum,  # Legacy helpers still reference this
    ProviderMapping,
    ProviderTypeEnum,
)


class EventMappingService:
    """Reusable DB-backed mapping helpers for canonical <-> provider events."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Internal helpers

    @staticmethod
    def _normalize_aliases(alternate_uids: Optional[Sequence[str]]) -> Optional[List[str]]:
        if not alternate_uids:
            return None

        normalized: List[str] = []
        for candidate in alternate_uids:
            if candidate is None:
                continue
            text = str(candidate).strip()
            if not text:
                continue
            if text not in normalized:
                normalized.append(text)
        return normalized or None

    @staticmethod
    def _coerce_datetime(value) -> Optional[datetime]:
        """Normalize incoming datetime or ISO8601 strings to naive datetimes."""

        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None
            candidate = candidate.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(candidate)
            except ValueError:
                return None
            return parsed.replace(tzinfo=None)
        return None

    @staticmethod
    def _compute_content_hash(
        *,
        title: str,
        start_at: Optional[datetime],
        end_at: Optional[datetime],
        location: str,
        notes: str,
    ) -> str:
        """Mirror Event.update_content_hash logic for external comparisons."""

        start_str = start_at.isoformat() if start_at else ""
        end_str = end_at.isoformat() if end_at else ""
        content = f"{title}|{start_str}|{end_str}|{location}|{notes}"
        return hashlib.md5(content.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Provider mapping helpers

    def upsert_mapping(
        self,
        provider_id: str,
        provider_type: ProviderTypeEnum | str,
        provider_uid: str,
        orbit_event_id: str,
        *,
        etag_or_ver: Optional[str] = None,
        tombstoned: bool = False,
        last_seen_at: Optional[datetime] = None,
        alternate_uids: Optional[Sequence[str]] = None,
    ) -> ProviderMapping:
        """Insert or update a mapping row for a provider event."""

        provider_type_enum = (
            provider_type
            if isinstance(provider_type, ProviderTypeEnum)
            else ProviderTypeEnum(provider_type)
        )

        normalized_aliases = self._normalize_aliases(alternate_uids)

        mapping = (
            self.db.query(ProviderMapping)
            .filter(
                ProviderMapping.provider_id == provider_id,
                ProviderMapping.provider_uid == provider_uid,
            )
            .first()
        )

        fallback_mapping = None
        if mapping is None:
            # Providers like Apple may rewrite the primary UID after creation.
            # If we already have a mapping for this orbit event and provider,
            # repoint the existing row instead of inserting a duplicate.
            fallback_mapping = (
                self.db.query(ProviderMapping)
                .filter(
                    ProviderMapping.provider_id == provider_id,
                    ProviderMapping.orbit_event_id == orbit_event_id,
                )
                .first()
            )

        now = last_seen_at or datetime.utcnow()

        if mapping:
            mapping.last_seen_at = now
            mapping.tombstoned = tombstoned
            mapping.orbit_event_id = orbit_event_id
            mapping.provider_type = provider_type_enum
            if etag_or_ver is not None:
                mapping.etag_or_version = etag_or_ver
            if normalized_aliases:
                existing = set(mapping.alternate_uids or [])
                updated = existing.union(normalized_aliases)
                if updated != existing:
                    mapping.alternate_uids = sorted(updated)
        elif fallback_mapping:
            alias_pool = set(normalized_aliases or [])
            alias_pool.update(fallback_mapping.alternate_uids or [])
            previous_uid = fallback_mapping.provider_uid
            if previous_uid and previous_uid != provider_uid:
                alias_pool.add(previous_uid)

            fallback_mapping.provider_uid = provider_uid
            fallback_mapping.provider_type = provider_type_enum
            fallback_mapping.last_seen_at = now
            fallback_mapping.tombstoned = tombstoned
            if etag_or_ver is not None:
                fallback_mapping.etag_or_version = etag_or_ver
            if alias_pool:
                fallback_mapping.alternate_uids = sorted(alias_pool)
            mapping = fallback_mapping
        else:
            mapping = ProviderMapping(
                provider_id=provider_id,
                provider_type=provider_type_enum,
                provider_uid=provider_uid,
                orbit_event_id=orbit_event_id,
                etag_or_version=etag_or_ver or "",
                last_seen_at=now,
                tombstoned=tombstoned,
                alternate_uids=normalized_aliases or None,
            )
            self.db.add(mapping)

        return mapping

    def find_matching_orbit_event(
        self,
        canonical_event: dict,
        *,
        window_seconds: int = 120,
    ) -> Optional[Event]:
        """Return an existing Orbit event that matches the canonical payload."""

        title = (canonical_event.get("title") or "").strip()
        if not title:
            return None

        start_at = self._coerce_datetime(canonical_event.get("start"))
        if not start_at:
            return None

        end_at = self._coerce_datetime(canonical_event.get("end"))
        location = (canonical_event.get("location") or "").strip()
        notes = (canonical_event.get("notes") or "").strip()

        content_hash = self._compute_content_hash(
            title=title,
            start_at=start_at,
            end_at=end_at,
            location=location,
            notes=notes,
        )

        lower = start_at - timedelta(seconds=window_seconds)
        upper = start_at + timedelta(seconds=window_seconds)

        return (
            self.db.query(Event)
            .filter(
                Event.content_hash == content_hash,
                Event.start_at >= lower,
                Event.start_at <= upper,
                Event.tombstoned.is_(False),
            )
            .order_by(Event.updated_at.desc())
            .first()
        )

    def get_mapping(
        self,
        provider_id: str,
        provider_uid: str,
        *,
        alternate_uids: Optional[Sequence[str]] = None,
    ) -> Optional[ProviderMapping]:
        mapping = (
            self.db.query(ProviderMapping)
            .filter(
                ProviderMapping.provider_id == provider_id,
                ProviderMapping.provider_uid == provider_uid,
            )
            .first()
        )
        if mapping or not alternate_uids:
            return mapping

        search_values = {
            str(provider_uid),
            *{
                str(candidate).strip()
                for candidate in alternate_uids
                if candidate is not None and str(candidate).strip()
            },
        }

        candidates = (
            self.db.query(ProviderMapping)
            .filter(ProviderMapping.provider_id == provider_id)
            .all()
        )

        for candidate in candidates:
            if candidate.provider_uid in search_values:
                return candidate
            for alias in candidate.alternate_uids or []:
                if alias in search_values:
                    return candidate
        return None

    def get_mappings_for_orbit(self, orbit_id: str) -> Iterable[ProviderMapping]:
        return (
            self.db.query(ProviderMapping)
            .filter(ProviderMapping.orbit_event_id == orbit_id)
            .all()
        )

    def get_orbit_id(self, provider_id: str, provider_uid: str) -> Optional[str]:
        mapping = self.get_mapping(provider_id, provider_uid)
        return mapping.orbit_event_id if mapping else None

    def get_provider_uid(self, provider_id: str, orbit_id: str) -> Optional[str]:
        mapping = (
            self.db.query(ProviderMapping)
            .filter(
                ProviderMapping.provider_id == provider_id,
                ProviderMapping.orbit_event_id == orbit_id,
            )
            .first()
        )
        return mapping.provider_uid if mapping else None

    def mark_tombstoned(
        self,
        provider_id: str,
        provider_uid: str,
        *,
        value: bool = True,
    ) -> None:
        mapping = self.get_mapping(provider_id, provider_uid)
        if mapping:
            mapping.tombstoned = value

    def is_tombstoned(self, provider_id: str, provider_uid: str) -> bool:
        mapping = self.get_mapping(provider_id, provider_uid)
        return bool(mapping and mapping.tombstoned)

    def prune_stale(self, provider_id: str, *, before: datetime) -> int:
        """Remove tombstoned mappings older than a threshold. Returns rows deleted."""

        rows = (
            self.db.query(ProviderMapping)
            .filter(
                ProviderMapping.provider_id == provider_id,
                ProviderMapping.tombstoned.is_(True),
                ProviderMapping.last_seen_at < before,
            )
            .all()
        )

        for row in rows:
            self.db.delete(row)

        return len(rows)

    # ------------------------------------------------------------------
    # Canonical helpers

    def create_canonical_event(self, event_data: dict) -> Event:
        """Create a canonical event row and return the persisted instance."""

        event = Event(
            title=event_data["title"],
            start_at=event_data["start"],
            end_at=event_data["end"],
            location=event_data.get("location"),
            notes=event_data.get("notes"),
        )
        event.update_content_hash()
        self.db.add(event)
        self.db.flush()
        return event

    def update_canonical_event(self, event: Event, event_data: dict) -> bool:
        """Update an existing canonical event. Returns True if fields changed."""

        changed = False

        for field in ("title", "start_at", "end_at", "location", "notes"):
            new_value = event_data.get(field)
            if field in {"start_at", "end_at"} and new_value is None:
                continue
            if getattr(event, field) != new_value:
                setattr(event, field, new_value)
                changed = True

        if changed:
            event.update_content_hash()

        return changed

    # ------------------------------------------------------------------
    # Legacy compatibility helpers (ProviderEnum-based)

    def _provider_ids_for_enum(self, provider_enum: ProviderEnum) -> list[str]:
        type_map = {
            ProviderEnum.APPLE: ProviderTypeEnum.APPLE_CALDAV,
            ProviderEnum.SKYLIGHT: ProviderTypeEnum.SKYLIGHT,
        }
        provider_type = type_map.get(provider_enum)
        if not provider_type:
            return []
        return [
            provider.id
            for provider in (
                self.db.query(Provider)
                .filter(Provider.type == provider_type)
                .all()
            )
        ]

    def get_other_provider_uid(
        self,
        from_provider: ProviderEnum,
        from_uid: str,
        to_provider: ProviderEnum,
    ) -> Optional[str]:
        from_ids = self._provider_ids_for_enum(from_provider)
        to_ids = self._provider_ids_for_enum(to_provider)
        if not from_ids or not to_ids:
            return None

        mapping = (
            self.db.query(ProviderMapping)
            .filter(
                ProviderMapping.provider_id.in_(from_ids),
                ProviderMapping.provider_uid == from_uid,
            )
            .first()
        )
        if not mapping:
            return None

        other = (
            self.db.query(ProviderMapping)
            .filter(
                ProviderMapping.orbit_event_id == mapping.orbit_event_id,
                ProviderMapping.provider_id.in_(to_ids),
            )
            .first()
        )
        return other.provider_uid if other else None

    def set_bidirectional_mapping(
        self,
        apple_uid: str,
        skylight_id: str,
        orbit_event_id: str,
        apple_etag: Optional[str] = None,
        skylight_ver: Optional[str] = None,
    ) -> None:
        apple_ids = self._provider_ids_for_enum(ProviderEnum.APPLE)
        skylight_ids = self._provider_ids_for_enum(ProviderEnum.SKYLIGHT)
        if not apple_ids or not skylight_ids:
            return

        self.upsert_mapping(
            apple_ids[0],
            ProviderTypeEnum.APPLE_CALDAV,
            apple_uid,
            orbit_event_id,
            etag_or_ver=apple_etag,
        )
        self.upsert_mapping(
            skylight_ids[0],
            ProviderTypeEnum.SKYLIGHT,
            skylight_id,
            orbit_event_id,
            etag_or_ver=skylight_ver,
        )
