"""High-level event orchestration helpers that operate through provider adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session, joinedload

from ..core.logging import logger
from ..domain.mapping import ProviderEventConverter
from ..domain.models import (
    Event,
    Provider,
    ProviderMapping,
    ProviderTypeEnum,
    serialize_datetime,
)
from ..infra.db import get_db_session
from ..providers.base import ProviderAdapter
from ..providers.registry import ProviderRegistry, provider_registry
from ..services.sync_definition_service import SyncDefinition, SyncDefinitionService


class ProviderEventServiceError(Exception):
    """Base exception for provider event orchestration errors."""


class EventNotFoundError(ProviderEventServiceError):
    """Raised when a requested Orbit event cannot be located."""


@dataclass(frozen=True)
class ProviderSnapshot:
    """Lightweight representation of a provider detached from the session."""

    id: str
    type_id: str
    config: Dict[str, Any]
    name: Optional[str] = None


@dataclass
class ProviderInvocationResult:
    provider: ProviderSnapshot
    adapter: ProviderAdapter
    payload: Dict[str, Any]
    result: Dict[str, Any]


@dataclass
class MappingSnapshot:
    """Detached representation of a provider mapping."""

    id: str
    provider_id: str
    provider_uid: str
    provider_type: ProviderTypeEnum
    etag_or_version: Optional[str]
    last_seen_at: Optional[datetime]
    provider: ProviderSnapshot
    alternate_uids: Optional[List[str]]


class ProviderEventService:
    """Coordinate event CRUD operations across configured providers via adapters."""

    def __init__(
        self,
        *,
        session_factory=get_db_session,
        registry: ProviderRegistry = provider_registry,
        converter: Optional[ProviderEventConverter] = None,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.converter = converter or ProviderEventConverter()
        self.log = logger.bind(component="provider_event_service")

    # ------------------------------------------------------------------
    # Provider snapshot helpers

    @staticmethod
    def _snapshot_provider_from_model(
        provider: Provider,
        *,
        type_hint: Optional[ProviderTypeEnum] = None,
    ) -> ProviderSnapshot:
        type_id = (
            type_hint.value
            if isinstance(type_hint, ProviderTypeEnum)
            else None
        )
        if not type_id and provider.type_id:
            type_id = provider.type_id
        if not type_id and provider.type:
            type_id = provider.type.value
        if not type_id:
            raise ProviderEventServiceError(
                f"Provider '{provider.id}' is missing a type identifier"
            )
        return ProviderSnapshot(
            id=provider.id,
            type_id=type_id,
            config=dict(provider.config or {}),
            name=provider.name,
        )

    def _snapshot_provider_from_mapping(
        self,
        mapping: ProviderMapping,
    ) -> ProviderSnapshot:
        provider = mapping.provider
        type_hint = mapping.provider_type
        if provider:
            return self._snapshot_provider_from_model(provider, type_hint=type_hint)
        if not type_hint:
            raise ProviderEventServiceError(
                f"Provider mapping '{mapping.provider_id}' is missing type metadata"
            )
        return ProviderSnapshot(
            id=mapping.provider_id,
            type_id=type_hint.value,
            config={},
            name=None,
        )

    def _snapshot_mapping(self, mapping: ProviderMapping) -> MappingSnapshot:
        provider_snapshot = self._snapshot_provider_from_mapping(mapping)
        if not mapping.provider_type:
            raise ProviderEventServiceError(
                f"Mapping for provider '{mapping.provider_id}' is missing provider_type"
            )
        return MappingSnapshot(
            id=mapping.id,
            provider_id=mapping.provider_id,
            provider_uid=mapping.provider_uid,
            provider_type=mapping.provider_type,
            etag_or_version=mapping.etag_or_version,
            last_seen_at=mapping.last_seen_at,
            provider=provider_snapshot,
            alternate_uids=list(mapping.alternate_uids or []),
        )

    async def recreate_mapping(
        self,
        mapping_id: str,
        *,
        target_provider_id: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Recreate a provider event for the specified mapping."""

        with self.session_factory() as session:
            mapping = (
                session.query(ProviderMapping)
                .options(
                    joinedload(ProviderMapping.provider),
                    joinedload(ProviderMapping.event),
                )
                .filter(ProviderMapping.id == mapping_id)
                .first()
            )

            if not mapping:
                raise ProviderEventServiceError("Mapping not found")

            event = mapping.event
            if not event:
                raise ProviderEventServiceError("Orbit event not found for mapping")

            provider_id = target_provider_id or mapping.provider_id
            if provider_id != mapping.provider_id:
                raise ProviderEventServiceError(
                    "Mapping does not belong to the requested provider"
                )

            provider_model = mapping.provider
            if not provider_model:
                provider_model = (
                    session.query(Provider)
                    .filter(Provider.id == provider_id)
                    .first()
                )
                if not provider_model:
                    raise ProviderEventServiceError("Provider not found")

            provider_snapshot = self._snapshot_provider_from_model(
                provider_model, type_hint=mapping.provider_type
            )
            mapping_snapshot = self._snapshot_mapping(mapping)
            canonical_event = {
                "title": event.title,
                "start": event.start_at,
                "end": event.end_at,
                "location": event.location or "",
                "notes": event.notes or "",
            }

        normalized_event = self._normalize_canonical_event(canonical_event)

        contexts = await self._initialize_adapters([provider_snapshot])
        try:
            adapter = contexts[0][1]
            payload = await self._build_provider_payload(
                provider_snapshot,
                adapter,
                normalized_event,
            )
            result = await adapter.create_event(payload)
        finally:
            await self._close_adapters(contexts)

        provider_uid, alternate_uids = self._extract_provider_identifiers(
            provider_snapshot,
            result,
        )
        if not provider_uid:
            raise ProviderEventServiceError("Provider did not return an event identifier")

        etag_or_version = self._extract_etag(result) or mapping_snapshot.etag_or_version
        created_timestamp = self._extract_created_timestamp(result)

        with self.session_factory() as session:
            mapping = (
                session.query(ProviderMapping)
                .filter(ProviderMapping.id == mapping_id)
                .first()
            )
            if not mapping:
                raise ProviderEventServiceError(
                    "Mapping disappeared during recreation"
                )

            mapping.provider_uid = provider_uid
            mapping.alternate_uids = alternate_uids or mapping.alternate_uids
            mapping.etag_or_version = etag_or_version or mapping.etag_or_version
            mapping.last_seen_at = datetime.utcnow()
            mapping.tombstoned = False
            session.flush()
            last_seen_at = serialize_datetime(mapping.last_seen_at)
            session.commit()

        return {
            "status": "recreated",
            "provider_id": provider_snapshot.id,
            "provider_uid": provider_uid,
            "mapping_id": mapping_id,
            "created_at": created_timestamp,
            "last_seen_at": last_seen_at,
            "operation_id": None,
        }

    def confirm_event(self, provider_id: str, provider_uid: str) -> Dict[str, Any]:
        """Return whether a provider event mapping still exists locally."""

        with self.session_factory() as session:
            mapping = (
                session.query(ProviderMapping)
                .options(joinedload(ProviderMapping.provider))
                .filter(
                    ProviderMapping.provider_id == provider_id,
                    ProviderMapping.provider_uid == provider_uid,
                )
                .first()
            )

        exists = mapping is not None and not mapping.tombstoned
        last_seen = serialize_datetime(mapping.last_seen_at) if mapping else None
        return {
            "provider_id": provider_id,
            "provider_uid": provider_uid,
            "exists": exists,
            "last_seen_at": last_seen,
        }

    async def create_event(
        self,
        canonical_event: Dict[str, Any],
        *,
        category_names: Optional[Sequence[str]] = None,
        sync_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an event across all active providers."""
        canonical = self._normalize_canonical_event(canonical_event)

        providers = self._providers_for_sync(sync_id=sync_id)
        if not providers:
            raise ProviderEventServiceError(
                "No active providers configured for event creation"
            )

        contexts = await self._initialize_adapters(providers)
        invocation_chain: List[ProviderInvocationResult] = []

        try:
            for provider, adapter in contexts:
                payload = await self._build_provider_payload(
                    provider,
                    adapter,
                    canonical,
                    category_names=category_names,
                )
                result = await adapter.create_event(payload)
                invocation_chain.append(
                    ProviderInvocationResult(
                        provider=provider,
                        adapter=adapter,
                        payload=payload,
                        result=result or {},
                    )
                )
        except Exception as exc:
            await self._rollback_creates(invocation_chain)
            raise ProviderEventServiceError(f"Provider create failed: {exc}") from exc

        try:
            with self.session_factory() as session:
                event = self._persist_new_event(session, canonical)
                mappings = self._persist_mappings(session, event, invocation_chain)
                session.commit()
                return self._serialize_event(event, mappings)
        finally:
            await self._close_adapters(contexts)

    async def update_event(
        self,
        event_id: str,
        updates: Dict[str, Any],
        *,
        category_names: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Update an existing event and propagate changes to linked providers."""

        with self.session_factory() as session:
            event, mapping_models = self._load_event_with_mappings(session, event_id)
            if not event:
                raise EventNotFoundError(f"Event '{event_id}' not found")

            normalized_updates = dict(updates or {})
            if "start_at" in normalized_updates:
                normalized_updates["start"] = normalized_updates.pop("start_at")
            if "end_at" in normalized_updates:
                normalized_updates["end"] = normalized_updates.pop("end_at")
            self._apply_updates_to_event(event, normalized_updates)
            canonical = self._normalize_canonical_event(
                {
                    "title": event.title,
                    "start": event.start_at,
                    "end": event.end_at,
                    "location": event.location,
                    "notes": event.notes,
                }
            )

            mapping_snapshots = [
                self._snapshot_mapping(mapping)
                for mapping in mapping_models
            ]
            event_snapshot = {
                "title": event.title,
                "start_at": event.start_at,
                "end_at": event.end_at,
                "location": event.location,
                "notes": event.notes,
            }

        provider_contexts = {
            snapshot.provider.id: snapshot.provider
            for snapshot in mapping_snapshots
        }
        contexts = await self._initialize_adapters(provider_contexts.values())
        adapter_map = {provider.id: adapter for provider, adapter in contexts}

        try:
            for snapshot in mapping_snapshots:
                adapter = adapter_map.get(snapshot.provider_id)
                if not adapter:
                    continue
                # Use the nested provider snapshot (has type_id) instead of the mapping snapshot
                payload = await self._build_provider_payload(
                    snapshot.provider,
                    adapter,
                    canonical,
                    category_names=category_names,
                    existing_uid=snapshot.provider_uid,
                )
                try:
                    result = await adapter.update_event(snapshot.provider_uid, payload)
                except Exception as exc:  # pragma: no cover - defensive
                    raise ProviderEventServiceError(
                        f"Failed to update provider {snapshot.provider_id}: {exc}"
                    ) from exc

                if isinstance(result, dict):
                    if etag := result.get("etag"):
                        snapshot.etag_or_version = etag
                    elif version := result.get("version"):
                        snapshot.etag_or_version = version
                primary_uid, alternate_uids = self._extract_provider_identifiers(
                    snapshot.provider,
                    result,
                )
                if primary_uid:
                    snapshot.provider_uid = primary_uid
                if alternate_uids:
                    snapshot.alternate_uids = alternate_uids
                snapshot.last_seen_at = datetime.utcnow()

            with self.session_factory() as session:
                event_model = (
                    session.query(Event)
                    .filter(Event.id == event_id)
                    .first()
                )
                if not event_model:
                    raise EventNotFoundError(f"Event '{event_id}' not found")

                event_model.title = event_snapshot["title"]
                event_model.start_at = event_snapshot["start_at"]
                event_model.end_at = event_snapshot["end_at"]
                event_model.location = event_snapshot["location"]
                event_model.notes = event_snapshot["notes"]
                event_model.update_content_hash()
                session.add(event_model)

                for snapshot in mapping_snapshots:
                    mapping_model = (
                        session.query(ProviderMapping)
                        .filter(
                            ProviderMapping.orbit_event_id == event_id,
                            ProviderMapping.provider_id == snapshot.provider_id,
                        )
                        .first()
                    )
                    if not mapping_model:
                        continue
                    mapping_model.provider_uid = snapshot.provider_uid
                    mapping_model.alternate_uids = snapshot.alternate_uids or mapping_model.alternate_uids
                    mapping_model.etag_or_version = snapshot.etag_or_version
                    mapping_model.last_seen_at = snapshot.last_seen_at
                    session.add(mapping_model)

                session.commit()

                refreshed_event, refreshed_mappings = self._load_event_with_mappings(
                    session,
                    event_id,
                )
                return self._serialize_event(refreshed_event, refreshed_mappings)
        finally:
            await self._close_adapters(contexts)

    async def delete_event(self, event_id: str) -> Dict[str, Any]:
        """Delete an event from all linked providers and tombstone it locally."""

        with self.session_factory() as session:
            event, mapping_models = self._load_event_with_mappings(session, event_id)
            if not event:
                raise EventNotFoundError(f"Event '{event_id}' not found")

            mapping_snapshots = [
                self._snapshot_mapping(mapping)
                for mapping in mapping_models
            ]

        provider_contexts = {
            snapshot.provider.id: snapshot.provider
            for snapshot in mapping_snapshots
        }
        contexts = await self._initialize_adapters(provider_contexts.values())
        adapter_map = {provider.id: adapter for provider, adapter in contexts}

        try:
            for snapshot in mapping_snapshots:
                adapter = adapter_map.get(snapshot.provider_id)
                if not adapter:
                    continue
                try:
                    await adapter.delete_event(snapshot.provider_uid)
                except Exception as exc:  # pragma: no cover - defensive
                    self.log.warning(
                        "Provider delete failed",
                        provider_id=snapshot.provider_id,
                        provider_uid=snapshot.provider_uid,
                        error=str(exc),
                    )
            with self.session_factory() as session:
                persistent_event, persistent_mappings = self._load_event_with_mappings(
                    session,
                    event_id,
                )
                if persistent_event:
                    persistent_event.tombstoned = True
                for mapping in persistent_mappings:
                    mapping.tombstoned = True
                    session.add(mapping)
                session.commit()
            return {"event_id": event_id, "status": "deleted"}
        finally:
            await self._close_adapters(contexts)

    # ------------------------------------------------------------------
    # Internal helpers

    def _providers_for_sync(
        self,
        *,
        sync_id: Optional[str] = None,
    ) -> List[ProviderSnapshot]:
        with self.session_factory() as session:
            definition_service = SyncDefinitionService(session)
            definitions: List[SyncDefinition] = []
            if sync_id:
                definition = definition_service.get_sync(sync_id)
                if definition and definition.enabled:
                    definitions.append(definition)
            else:
                definitions = [
                    definition
                    for definition in definition_service.list_syncs()
                    if definition.enabled
                ]

            provider_ids = {
                endpoint.provider_id
                for definition in definitions
                for endpoint in definition.endpoints
                if endpoint.enabled
            }

            if not provider_ids:
                return []

            providers = (
                session.query(Provider)
                .filter(Provider.id.in_(provider_ids))
                .all()
            )

            return [
                self._snapshot_provider_from_model(provider)
                for provider in providers
            ]

    async def _initialize_adapters(
        self,
        providers: Iterable[ProviderSnapshot],
    ) -> List[Tuple[ProviderSnapshot, ProviderAdapter]]:
        contexts: List[Tuple[ProviderSnapshot, ProviderAdapter]] = []
        for provider in providers:
            adapter = self.registry.create(
                provider.type_id,
                provider.id,
                provider.config or {},
            )
            await adapter.initialize()
            contexts.append((provider, adapter))
        return contexts

    async def _close_adapters(
        self,
        contexts: Iterable[Tuple[ProviderSnapshot, ProviderAdapter]],
    ) -> None:
        for _, adapter in contexts:
            try:
                await adapter.close()
            except Exception:  # pragma: no cover - best effort cleanup
                continue

    async def _rollback_creates(
        self,
        invocations: Iterable[ProviderInvocationResult],
    ) -> None:
        for invocation in invocations:
            provider_uid, _ = self._extract_provider_identifiers(
                invocation.provider,
                invocation.result,
            )
            if not provider_uid:
                continue
            try:
                await invocation.adapter.delete_event(provider_uid)
            except Exception:  # pragma: no cover - best effort cleanup
                self.log.warning(
                    "Rollback delete failed",
                    provider_id=invocation.provider.id,
                    provider_uid=provider_uid,
                )

    def _persist_new_event(self, session: Session, canonical: Dict[str, Any]) -> Event:
        event = Event(
            title=canonical["title"],
            start_at=canonical["start"],
            end_at=canonical["end"],
            location=canonical.get("location"),
            notes=canonical.get("notes"),
        )
        event.update_content_hash()
        session.add(event)
        session.flush()
        return event

    def _persist_mappings(
        self,
        session: Session,
        event: Event,
        invocations: Sequence[ProviderInvocationResult],
    ) -> List[ProviderMapping]:
        mappings: List[ProviderMapping] = []
        for invocation in invocations:
            provider = invocation.provider
            provider_uid, alternate_uids = self._extract_provider_identifiers(
                provider,
                invocation.result,
            )
            if not provider_uid:
                raise ProviderEventServiceError(
                    f"Provider '{provider.id}' did not return a UID for created event"
                )

            mapping = ProviderMapping(
                orbit_event_id=event.id,
                provider_id=provider.id,
                provider_type=ProviderTypeEnum(provider.type_id),
                provider_uid=provider_uid,
                etag_or_version=self._extract_etag(invocation.result),
                alternate_uids=alternate_uids or None,
                last_seen_at=datetime.utcnow(),
            )
            session.add(mapping)
            mappings.append(mapping)
        session.flush()
        return mappings

    def _serialize_event(
        self,
        event: Event,
        mappings: Sequence[ProviderMapping],
    ) -> Dict[str, Any]:
        providers_payload = [
            {
                "provider_id": mapping.provider_id,
                "provider_type": (
                    mapping.provider_type.value
                    if mapping.provider_type
                    else None
                ),
                "provider_uid": mapping.provider_uid,
                "etag_or_version": mapping.etag_or_version,
                "alternate_uids": list(mapping.alternate_uids or []),
                "last_seen_at": serialize_datetime(mapping.last_seen_at),
            }
            for mapping in mappings
            if not mapping.tombstoned
        ]

        return {
            "id": event.id,
            "title": event.title,
            "start_at": serialize_datetime(event.start_at),
            "end_at": serialize_datetime(event.end_at),
            "location": event.location or "",
            "notes": event.notes or "",
            "updated_at": serialize_datetime(event.updated_at),
            "providers": providers_payload,
        }

    def _normalize_canonical_event(self, canonical: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(canonical)
        normalized["title"] = (
            (normalized.get("title") or "").strip() or "Untitled Event"
        )
        normalized["start"] = self._coerce_datetime(normalized.get("start"))
        normalized["end"] = self._coerce_datetime(normalized.get("end"))
        if not normalized["start"] or not normalized["end"]:
            raise ProviderEventServiceError("Start and end datetime are required")
        return normalized

    def _coerce_datetime(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    async def _build_provider_payload(
        self,
        provider: ProviderSnapshot,
        adapter: ProviderAdapter,
        canonical: Dict[str, Any],
        *,
        category_names: Optional[Sequence[str]] = None,
        existing_uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        provider_type = ProviderTypeEnum(provider.type_id)
        if provider_type == ProviderTypeEnum.APPLE_CALDAV:
            payload = self.converter.canonical_to_apple(
                canonical,
                existing_uid=existing_uid,
            )
            if not payload:
                raise ProviderEventServiceError(
                    "Failed to convert event for Apple CalDAV"
                )
            return payload
        if provider_type == ProviderTypeEnum.SKYLIGHT:
            payload = self.converter.canonical_to_skylight(canonical)
            if category_names and hasattr(adapter, "client"):
                try:
                    category_ids = await adapter.client.get_category_ids_by_names(
                        list(category_names)
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    self.log.warning(
                        "Failed to resolve Skylight categories",
                        provider_id=provider.id,
                        error=str(exc),
                    )
                    category_ids = []
                if category_ids:
                    payload["category_ids"] = category_ids
            return payload
        return dict(canonical)

    def _extract_provider_identifiers(
        self,
        provider: ProviderSnapshot,
        result: Dict[str, Any],
    ) -> Tuple[Optional[str], List[str]]:
        aliases: List[str] = []

        if not isinstance(result, dict):
            return None, aliases

        data = result
        if isinstance(result.get("data"), dict):
            data = result["data"]

        primary: Optional[str] = None
        if data.get("id") is not None:
            primary = str(data["id"])
        elif result.get("id") is not None:
            primary = str(result["id"])
        elif data.get("uid"):
            primary = str(data["uid"])

        attrs = data.get("attributes", {}) if isinstance(data, dict) else {}

        def _try_append(value: Any) -> None:
            if value is None:
                return
            try:
                text = str(value)
            except Exception:
                return
            if not text.strip():
                return
            if primary is not None and text == primary:
                return
            if text not in aliases:
                aliases.append(text)

        _try_append(attrs.get("uid"))
        _try_append(attrs.get("original_uid"))
        _try_append(attrs.get("source_uid"))
        _try_append(result.get("uid"))

        return primary, aliases

    def _extract_provider_uid(
        self,
        provider: ProviderSnapshot,
        result: Dict[str, Any],
    ) -> Optional[str]:
        primary, _ = self._extract_provider_identifiers(provider, result)
        return primary

    def _extract_etag(self, result: Dict[str, Any]) -> Optional[str]:
        if not isinstance(result, dict):
            return None
        return result.get("etag") or result.get("version")

    @staticmethod
    def _extract_created_timestamp(result: Dict[str, Any]) -> Optional[str]:
        if not isinstance(result, dict):
            return None
        for key in ("created_at", "created", "createdISO", "createdAt"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _load_event_with_mappings(
        self,
        session: Session,
        event_id: str,
    ) -> Tuple[Optional[Event], List[ProviderMapping]]:
        event = (
            session.query(Event)
            .filter(Event.id == event_id, ~Event.tombstoned)
            .first()
        )
        if not event:
            return None, []
        mappings = (
            session.query(ProviderMapping)
            .options(joinedload(ProviderMapping.provider))
            .filter(
                ProviderMapping.orbit_event_id == event.id,
                ~ProviderMapping.tombstoned,
            )
            .all()
        )
        return event, mappings

    def _apply_updates_to_event(self, event: Event, updates: Dict[str, Any]) -> None:
        if "title" in updates and updates["title"] is not None:
            event.title = updates["title"].strip() or event.title
        if "start" in updates and updates["start"] is not None:
            start_dt = self._coerce_datetime(updates["start"])
            if not start_dt:
                raise ProviderEventServiceError("Invalid start datetime format")
            event.start_at = start_dt
        if "end" in updates and updates["end"] is not None:
            end_dt = self._coerce_datetime(updates["end"])
            if not end_dt:
                raise ProviderEventServiceError("Invalid end datetime format")
            event.end_at = end_dt
        if "location" in updates and updates["location"] is not None:
            event.location = updates["location"]
        if "notes" in updates and updates["notes"] is not None:
            event.notes = updates["notes"]
        event.update_content_hash()
