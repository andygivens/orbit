"""Adapter-driven sync engine for Orbit multi-provider synchronization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..core.logging import logger
from ..data.sync_mapping import EventMappingService
from ..domain.mapping import ProviderEventConverter
from ..domain.models import (
    ConfigItem,
    Event,
    Provider,
    ProviderStatusEnum,
    ProviderTypeEnum,
    SyncDirectionEnum,
    SyncEndpointRoleEnum,
    SyncEventFlow,
    SyncRun,
    serialize_datetime,
)
from ..infra.db import get_db_session
from ..providers.base import ProviderAdapter
from ..providers.registry import ProviderRegistry, provider_registry
from ..services.sync_definition_service import SyncDefinition, SyncEndpointDefinition


@dataclass
class SyncRunStats:
    """Aggregated statistics for a directional sync run."""

    events_processed: int = 0
    events_created: int = 0
    events_updated: int = 0
    events_deleted: int = 0
    errors: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "events_processed": self.events_processed,
            "events_created": self.events_created,
            "events_updated": self.events_updated,
            "events_deleted": self.events_deleted,
            "errors": self.errors,
        }


@dataclass
class EndpointContext:
    """Runtime context for a sync endpoint."""

    definition: SyncEndpointDefinition
    adapter: ProviderAdapter
    type: ProviderTypeEnum
    role: SyncEndpointRoleEnum
    config: Dict[str, Any] = field(default_factory=dict)
    timezone: Optional[str] = None


class SyncService:
    """Adapter-driven sync orchestration across configured providers."""

    def __init__(
        self,
        *,
        session_factory=get_db_session,
        registry: ProviderRegistry = provider_registry,
        max_runs_per_sync: int = 25,
    ):
        self.session_factory = session_factory
        self.registry = registry
        self.max_runs_per_sync = max_runs_per_sync
        self.converter = ProviderEventConverter()
        self.log = logger.bind(component="sync_engine")

    # ------------------------------------------------------------------
    # Public API

    async def check_readiness(self) -> Dict[str, Any]:
        """Validate provider adapters can initialize using the registry."""

        with self.session_factory() as session:
            provider_specs = [
                {
                    "id": provider.id,
                    "name": provider.name,
                    "type_id": provider.type_id,
                    "config": dict(provider.config or {}),
                }
                for provider in (
                    session.query(Provider)
                    .filter(Provider.enabled.is_(True))
                    .all()
                )
            ]

        if not provider_specs:
            checked_at = datetime.utcnow()
            return {
                "status": "degraded",
                "reason": "no_enabled_providers",
                "checked_at": serialize_datetime(checked_at),
                "providers": [],
            }

        readiness_results: List[Dict[str, Any]] = []
        all_healthy = True
        failure_reason: Optional[str] = None
        checked_at = datetime.utcnow()
        checked_at_iso = serialize_datetime(checked_at)

        for spec in provider_specs:
            adapter = None
            status = "connected"
            detail: Optional[str] = None

            try:
                adapter = self.registry.create(spec["type_id"], spec["id"], spec["config"])
                await adapter.initialize()
            except Exception as exc:  # pragma: no cover - defensive logging
                status = "error"
                detail = str(exc)
                all_healthy = False
                failure_reason = "provider_initialization_failed"
                self.log.warning(
                    "Provider readiness check failed",
                    provider_id=spec["id"],
                    provider_type=spec["type_id"],
                    error=detail,
                )
            finally:
                if adapter:
                    try:
                        await adapter.close()
                    except Exception:  # pragma: no cover - best effort cleanup
                        pass

            readiness_results.append(
                {
                    "id": spec["id"],
                    "name": spec["name"],
                    "type": spec["type_id"],
                    "status": status,
                    "detail": detail,
                }
            )

        # Persist provider status updates
        status_updates = {
            result["id"]: result for result in readiness_results
        }
        with self.session_factory() as session:
            providers = (
                session.query(Provider)
                .filter(Provider.id.in_(status_updates.keys()))
                .all()
            )
            for provider in providers:
                update = status_updates.get(provider.id)
                provider.last_checked_at = checked_at
                if update["status"] == "connected":
                    provider.status = ProviderStatusEnum.ACTIVE
                    provider.status_detail = None
                else:
                    provider.status = ProviderStatusEnum.ERROR
                    provider.status_detail = update["detail"]
                session.add(provider)

        overall_status = "ready" if all_healthy else "degraded"

        payload: Dict[str, Any] = {
            "status": overall_status,
            "checked_at": checked_at_iso,
            "providers": readiness_results,
        }
        if overall_status != "ready" and failure_reason:
            payload["reason"] = failure_reason

        return payload

    async def run_sync(self, definition: SyncDefinition, *, mode: str = "run") -> Dict[str, Any]:
        """Execute the given sync definition across all endpoint pairs."""

        if not definition.enabled:
            self.log.info("Sync disabled, skipping", sync_id=definition.id)
            return {
                "sync_id": definition.id,
                "status": "skipped",
                "reason": "disabled",
                "runs": [],
            }

        contexts = await self._prepare_endpoints(definition)
        if not contexts:
            self.log.warning("No active endpoints available", sync_id=definition.id)
            return {
                "sync_id": definition.id,
                "status": "skipped",
                "reason": "no_active_endpoints",
                "runs": [],
            }

        window_start, window_end = self._sync_window(
            definition.window_days_past,
            definition.window_days_future,
        )
        await self._maybe_bootstrap(definition, contexts, window_start, window_end)
        run_summaries: List[Dict[str, Any]] = []
        overall_status = "success"

        for source_ctx, target_ctx in self._iter_direction_pairs(definition, contexts):
            summary = await self._run_direction(
                definition,
                source_ctx,
                target_ctx,
                window_start,
                window_end,
                mode=mode,
            )
            run_summaries.append(summary)

            if summary["status"] == "error":
                overall_status = "error"
            elif summary["status"] == "warning" and overall_status == "success":
                overall_status = "warning"

        await self._close_adapters(contexts)

        return {
            "sync_id": definition.id,
            "status": overall_status,
            "window": {
                "start": serialize_datetime(window_start),
                "end": serialize_datetime(window_end),
            },
            "runs": run_summaries,
        }

    # ------------------------------------------------------------------
    # Core execution helpers

    async def _prepare_endpoints(self, definition: SyncDefinition) -> List[EndpointContext]:
        contexts: List[EndpointContext] = []

        for endpoint in definition.endpoints:
            if not endpoint.enabled:
                continue

            try:
                provider_type = ProviderTypeEnum(endpoint.provider_type)
            except ValueError:
                self.log.warning(
                    "Unknown provider type for endpoint, skipping",
                    sync_id=definition.id,
                    provider_type=endpoint.provider_type,
                    provider_id=endpoint.provider_id,
                )
                continue

            try:
                role = SyncEndpointRoleEnum(endpoint.role)
            except ValueError:
                self.log.warning(
                    "Invalid endpoint role, defaulting to SECONDARY",
                    sync_id=definition.id,
                    provider_id=endpoint.provider_id,
                    role=endpoint.role,
                )
                role = SyncEndpointRoleEnum.SECONDARY

            adapter = self.registry.create(provider_type.value, endpoint.provider_id, endpoint.config or {})
            await adapter.initialize()

            contexts.append(
                EndpointContext(
                    definition=endpoint,
                    adapter=adapter,
                    type=provider_type,
                    role=role,
                    config=endpoint.config or {},
                    timezone=adapter.timezone or endpoint.config.get("timezone"),
                )
            )

        return contexts

    async def _maybe_bootstrap(
        self,
        definition: SyncDefinition,
        contexts: List[EndpointContext],
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        if not contexts:
            return

        with self.session_factory() as session:
            if not self._should_run_bootstrap(session, definition.id):
                return

        window_start_iso = serialize_datetime(window_start)
        window_end_iso = serialize_datetime(window_end)
        bootstrap_events: List[Tuple[EndpointContext, Dict[str, Any]]] = []

        for ctx in contexts:
            try:
                raw_events = await ctx.adapter.list_events(window_start_iso, window_end_iso)
            except Exception as exc:  # pragma: no cover - defensive logging
                self.log.warning(
                    "Bootstrap fetch failed",
                    sync_id=definition.id,
                    provider_id=ctx.definition.provider_id,
                    error=str(exc),
                )
                continue

            for raw_event in raw_events or []:
                try:
                    canonical = self._to_canonical_event(ctx, raw_event)
                except Exception as exc:  # pragma: no cover - defensive logging
                    self.log.debug(
                        "Bootstrap canonical conversion failed",
                        sync_id=definition.id,
                        provider_id=ctx.definition.provider_id,
                        error=str(exc),
                    )
                    continue

                if not canonical.get("provider_uid"):
                    continue

                canonical.setdefault("timezone", ctx.timezone)
                bootstrap_events.append((ctx, canonical))

        if not bootstrap_events:
            with self.session_factory() as session:
                self._mark_bootstrap_complete(session, definition.id)
            return

        matched_groups = 0

        with self.session_factory() as session:
            mapping_service = EventMappingService(session)
            buckets: Dict[str, List[Tuple[EndpointContext, Dict[str, Any]]]] = {}

            for ctx, canonical in bootstrap_events:
                start = mapping_service._coerce_datetime(
                    canonical.get("start_at") or canonical.get("start")
                )
                if not start:
                    continue
                canonical["start"] = start
                canonical["start_at"] = start
                end = mapping_service._coerce_datetime(
                    canonical.get("end_at") or canonical.get("end")
                )
                canonical["end"] = end
                canonical["end_at"] = end

                key = mapping_service._compute_content_hash(
                    title=(canonical.get("title") or "").strip(),
                    start_at=start,
                    end_at=end,
                    location=(canonical.get("location") or "").strip(),
                    notes=(canonical.get("notes") or "").strip(),
                )

                buckets.setdefault(key, []).append((ctx, canonical))

            for entries in buckets.values():
                per_provider: Dict[str, Tuple[EndpointContext, Dict[str, Any]]] = {}
                for ctx, canonical in entries:
                    provider_id = ctx.definition.provider_id
                    if provider_id in per_provider:
                        continue
                    if not canonical.get("provider_uid"):
                        continue
                    per_provider[provider_id] = (ctx, canonical)

                if len(per_provider) < 2:
                    continue

                seed_ctx, seed_canonical = next(iter(per_provider.values()))
                orbit_event: Optional[Event] = None

                for provider_id, (ctx, canonical) in per_provider.items():
                    provider_uid = canonical.get("provider_uid")
                    if not provider_uid:
                        continue
                    existing = mapping_service.get_mapping(provider_id, provider_uid)
                    if existing:
                        orbit_event = (
                            session.query(Event)
                            .filter(Event.id == existing.orbit_event_id)
                            .first()
                        )
                        if orbit_event:
                            break

                if not orbit_event:
                    orbit_event = mapping_service.find_matching_orbit_event(seed_canonical)

                if orbit_event:
                    mapping_service.update_canonical_event(orbit_event, seed_canonical)
                else:
                    orbit_event = mapping_service.create_canonical_event(seed_canonical)

                for provider_id, (ctx, canonical) in per_provider.items():
                    provider_uid = canonical.get("provider_uid")
                    if not provider_uid:
                        continue
                    mapping_service.upsert_mapping(
                        provider_id=provider_id,
                        provider_type=ctx.type,
                        provider_uid=provider_uid,
                        orbit_event_id=orbit_event.id,
                        tombstoned=False,
                    )

                matched_groups += 1

            session.flush()
            self._mark_bootstrap_complete(session, definition.id)

        if matched_groups:
            self.log.info(
                "Bootstrap reconciliation linked existing events",
                sync_id=definition.id,
                matched_groups=matched_groups,
            )
        else:
            self.log.info(
                "Bootstrap reconciliation completed with no matches",
                sync_id=definition.id,
            )

    def _iter_direction_pairs(
        self,
        definition: SyncDefinition,
        contexts: Iterable[EndpointContext],
    ) -> Iterable[Tuple[EndpointContext, EndpointContext]]:
        direction = SyncDirectionEnum(definition.direction)
        contexts = list(contexts)

        if direction == SyncDirectionEnum.ONE_WAY:
            sources = [ctx for ctx in contexts if ctx.role == SyncEndpointRoleEnum.PRIMARY]
            if not sources:
                sources = [ctx for ctx in contexts if ctx.role != SyncEndpointRoleEnum.OUTBOUND_ONLY]
            targets = [ctx for ctx in contexts if ctx not in sources]
            for source in sources:
                for target in targets:
                    if source.definition.provider_id == target.definition.provider_id:
                        continue
                    yield source, target
        else:  # BIDIRECTIONAL
            for source in contexts:
                if source.role == SyncEndpointRoleEnum.OUTBOUND_ONLY:
                    continue
                for target in contexts:
                    if source.definition.provider_id == target.definition.provider_id:
                        continue
                    yield source, target

    async def _run_direction(
        self,
        definition: SyncDefinition,
        source_ctx: EndpointContext,
        target_ctx: EndpointContext,
        window_start: datetime,
        window_end: datetime,
        *,
        mode: str,
    ) -> Dict[str, Any]:
        stats = SyncRunStats()
        status = "success"
        error_message: Optional[str] = None

        with self.session_factory() as session:
            run = self._start_sync_run(
                session,
                definition.id,
                source_ctx,
                target_ctx,
                window_start,
                window_end,
                mode,
            )
            run_id = run.id

        try:
            await self._sync_events_between(
                source_ctx=source_ctx,
                target_ctx=target_ctx,
                window_start=window_start,
                window_end=window_end,
                stats=stats,
                sync_id=definition.id,
                run_id=run_id,
            )
            if stats.errors:
                status = "warning"
        except Exception as exc:  # pragma: no cover - defensive fallback
            status = "error"
            error_message = str(exc)
            stats.errors += 1
            self.log.exception(
                "Directional sync failed",
                sync_id=definition.id,
                source_provider=source_ctx.definition.provider_id,
                target_provider=target_ctx.definition.provider_id,
                error=error_message,
            )

        with self.session_factory() as session:
            run = (
                session.query(SyncRun)
                .filter(SyncRun.id == run_id)
                .first()
            )
            if run:
                self._complete_sync_run(run, status, stats, error_message)
                self._prune_sync_runs(session, definition.id)
            else:  # pragma: no cover - diagnostic safeguard
                self.log.warning("Sync run missing during completion", run_id=run_id)

        return {
            "run_id": run_id,
            "status": status,
            "stats": stats.to_dict(),
            "source_provider_id": source_ctx.definition.provider_id,
            "target_provider_id": target_ctx.definition.provider_id,
            "window_start": serialize_datetime(window_start),
            "window_end": serialize_datetime(window_end),
            "error": error_message,
            "mode": mode,
        }

    async def _sync_events_between(
        self,
        *,
        source_ctx: EndpointContext,
        target_ctx: EndpointContext,
        window_start: datetime,
        window_end: datetime,
        stats: SyncRunStats,
        sync_id: str,
        run_id: str,
    ) -> None:
        start_iso = serialize_datetime(window_start)
        end_iso = serialize_datetime(window_end)

        raw_events = await source_ctx.adapter.list_events(start_iso, end_iso)
        events = list(raw_events or [])

        self.log.info(
            "Fetched events for directional sync",
            source_provider=source_ctx.definition.provider_id,
            target_provider=target_ctx.definition.provider_id,
            count=len(events),
        )

        for raw_event in events:
            stats.events_processed += 1
            try:
                await self._process_single_event(
                    raw_event=raw_event,
                    source_ctx=source_ctx,
                    target_ctx=target_ctx,
                    stats=stats,
                    sync_id=sync_id,
                    run_id=run_id,
                )
            except Exception as exc:
                stats.errors += 1
                self.log.warning(
                    "Failed to sync individual event",
                    source_provider=source_ctx.definition.provider_id,
                    target_provider=target_ctx.definition.provider_id,
                    error=str(exc),
                )

    async def _process_single_event(
        self,
        *,
        raw_event: Dict[str, Any],
        source_ctx: EndpointContext,
        target_ctx: EndpointContext,
        stats: SyncRunStats,
        sync_id: str,
        run_id: str,
    ) -> None:
        canonical = self._to_canonical_event(source_ctx, raw_event)
        provider_uid = canonical.get("provider_uid")
        if not provider_uid:
            raise ValueError("Provider UID missing in canonical event")

        canonical.setdefault("timezone", source_ctx.timezone)

        with self.session_factory() as session:
            mapping_service = EventMappingService(session)
            orbit_event = self._upsert_canonical_event(
                session=session,
                mapping_service=mapping_service,
                source_ctx=source_ctx,
                canonical_event=canonical,
                raw_event=raw_event,
            )
            await self._propagate_to_target(
                session=session,
                mapping_service=mapping_service,
                source_ctx=source_ctx,
                target_ctx=target_ctx,
                canonical_event=canonical,
                orbit_event=orbit_event,
                stats=stats,
                sync_id=sync_id,
                run_id=run_id,
            )

    def _upsert_canonical_event(
        self,
        *,
        session: Session,
        mapping_service: EventMappingService,
        source_ctx: EndpointContext,
        canonical_event: Dict[str, Any],
        raw_event: Dict[str, Any],
    ) -> Event:
        provider_id = source_ctx.definition.provider_id
        provider_uid = canonical_event["provider_uid"]
        alternate_uids = canonical_event.get("provider_uid_aliases")

        existing_mapping = mapping_service.get_mapping(
            provider_id,
            provider_uid,
            alternate_uids=alternate_uids,
        )
        orbit_event: Optional[Event] = None

        if existing_mapping:
            orbit_event = (
                session.query(Event)
                .filter(Event.id == existing_mapping.orbit_event_id)
                .first()
            )

        if not orbit_event:
            orbit_event = mapping_service.find_matching_orbit_event(canonical_event)

        if orbit_event:
            mapping_service.update_canonical_event(orbit_event, canonical_event)
        else:
            orbit_event = mapping_service.create_canonical_event(canonical_event)

        version = self._extract_version(source_ctx.type, raw_event, canonical_event)
        mapping_service.upsert_mapping(
            provider_id=provider_id,
            provider_type=source_ctx.type,
            provider_uid=provider_uid,
            orbit_event_id=orbit_event.id,
            etag_or_ver=version,
            tombstoned=False,
            alternate_uids=alternate_uids,
        )
        session.flush()
        return orbit_event

    async def _propagate_to_target(
        self,
        *,
        session: Session,
        mapping_service: EventMappingService,
        source_ctx: EndpointContext,
        target_ctx: EndpointContext,
        canonical_event: Dict[str, Any],
        orbit_event: Event,
        stats: SyncRunStats,
        sync_id: str,
        run_id: str,
    ) -> None:
        provider_id = target_ctx.definition.provider_id
        orbit_event_id = orbit_event.id
        target_uid = mapping_service.get_provider_uid(provider_id, orbit_event_id)

        payload = self._to_provider_payload(
            target_ctx,
            canonical_event,
            existing_uid=target_uid,
        )

        if not target_uid:
            response = await target_ctx.adapter.create_event(payload)
            target_uid = self._extract_response_uid(
                target_ctx.type,
                response,
                canonical_event,
                payload=payload,
            )
            if not target_uid:
                raise ValueError("Adapter did not return identifier for created event")
            version = self._extract_version(target_ctx.type, response, canonical_event)
            mapping_service.upsert_mapping(
                provider_id=provider_id,
                provider_type=target_ctx.type,
                provider_uid=target_uid,
                orbit_event_id=orbit_event_id,
                etag_or_ver=version,
                tombstoned=False,
                alternate_uids=canonical_event.get("provider_uid_aliases"),
            )
            stats.events_created += 1
        else:
            response = await target_ctx.adapter.update_event(target_uid, payload)
            version = self._extract_version(target_ctx.type, response, canonical_event)
            mapping_service.upsert_mapping(
                provider_id=provider_id,
                provider_type=target_ctx.type,
                provider_uid=target_uid,
                orbit_event_id=orbit_event_id,
                etag_or_ver=version,
                tombstoned=False,
                alternate_uids=canonical_event.get("provider_uid_aliases"),
            )
            stats.events_updated += 1

        session.flush()

        flow = SyncEventFlow(
            sync_id=sync_id,
            sync_run_id=run_id,
            orbit_event_id=orbit_event.id,
            source_provider_id=source_ctx.definition.provider_id,
            target_provider_id=target_ctx.definition.provider_id,
            direction=f"{source_ctx.definition.provider_id}->{target_ctx.definition.provider_id}",
        )
        session.add(flow)

    # ------------------------------------------------------------------
    # Conversion helpers

    def _to_canonical_event(
        self,
        ctx: EndpointContext,
        raw_event: Dict[str, Any],
    ) -> Dict[str, Any]:
        if ctx.type == ProviderTypeEnum.APPLE_CALDAV:
            return self.converter.apple_to_canonical(raw_event)
        if ctx.type == ProviderTypeEnum.SKYLIGHT:
            return self.converter.skylight_to_canonical(raw_event)
        raise ValueError(f"Unsupported provider type '{ctx.type.value}'")

    def _to_provider_payload(
        self,
        ctx: EndpointContext,
        canonical_event: Dict[str, Any],
        *,
        existing_uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        enriched = dict(canonical_event)
        enriched.setdefault("timezone", ctx.timezone)

        if ctx.type == ProviderTypeEnum.APPLE_CALDAV:
            payload = self.converter.canonical_to_apple(enriched, existing_uid=existing_uid)
            return payload or {
                "title": enriched["title"],
                "start": enriched["start"],
                "end": enriched["end"],
                "location": enriched.get("location", ""),
                "notes": enriched.get("notes", ""),
            }
        if ctx.type == ProviderTypeEnum.SKYLIGHT:
            if "category_ids" not in enriched and ctx.config.get("category_ids"):
                enriched["category_ids"] = ctx.config["category_ids"]
            return self.converter.canonical_to_skylight(enriched)
        raise ValueError(f"Unsupported provider type '{ctx.type.value}'")

    def _extract_response_uid(
        self,
        provider_type: ProviderTypeEnum,
        response: Any,
        canonical_event: Dict[str, Any],
        *,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if provider_type == ProviderTypeEnum.APPLE_CALDAV:
            if isinstance(response, dict):
                candidate = response.get("uid") or response.get("provider_uid")
                if candidate:
                    return candidate
            if payload and isinstance(payload, dict):
                candidate = payload.get("uid")
                if candidate:
                    return candidate
            return canonical_event.get("provider_uid")
        if provider_type == ProviderTypeEnum.SKYLIGHT:
            if isinstance(response, dict):
                candidate = response
                if isinstance(candidate.get("data"), dict):
                    candidate = candidate["data"]

                # Primary identifiers returned by Skylight live on the resource
                # object itself. Prefer the explicit "id" field, then fall back
                # to any UID-style attributes Skylight may surface.
                raw_id = candidate.get("id")
                if raw_id is not None:
                    return str(raw_id)

                attributes = candidate.get("attributes", {}) if isinstance(candidate, dict) else {}
                attr_id = attributes.get("id")
                if attr_id is not None:
                    return str(attr_id)

                attr_uid = attributes.get("uid") or candidate.get("uid")
                if attr_uid:
                    return str(attr_uid)

            return canonical_event.get("provider_uid")
        return None

    def _extract_version(
        self,
        provider_type: ProviderTypeEnum,
        data: Any,
        canonical_event: Dict[str, Any],
    ) -> Optional[str]:
        if provider_type == ProviderTypeEnum.APPLE_CALDAV:
            if isinstance(data, dict):
                return data.get("etag") or data.get("etag_or_version")
            return canonical_event.get("etag")
        if provider_type == ProviderTypeEnum.SKYLIGHT:
            if isinstance(data, dict):
                attributes = data.get("attributes", data)
                version = attributes.get("version")

                if version is None and isinstance(data.get("data"), dict):
                    nested = data["data"]
                    version = (
                        nested.get("version")
                        or nested.get("attributes", {}).get("version")
                    )

                return str(version) if version is not None else None
            return canonical_event.get("version")
        return None

    # ------------------------------------------------------------------
    # Run bookkeeping helpers

    def _start_sync_run(
        self,
        session: Session,
        sync_id: str,
        source_ctx: EndpointContext,
        target_ctx: EndpointContext,
        window_start: datetime,
        window_end: datetime,
        mode: str,
    ) -> SyncRun:
        run = SyncRun(
            sync_id=sync_id,
            direction=f"{source_ctx.definition.provider_id}->{target_ctx.definition.provider_id}",
            status="running",
            started_at=datetime.utcnow(),
            details={
                "source_provider_id": source_ctx.definition.provider_id,
                "target_provider_id": target_ctx.definition.provider_id,
                "source_role": source_ctx.role.value,
                "target_role": target_ctx.role.value,
                "window_start": serialize_datetime(window_start),
                "window_end": serialize_datetime(window_end),
                "mode": mode,
            },
        )
        session.add(run)
        session.flush()
        return run

    def _complete_sync_run(
        self,
        run: SyncRun,
        status: str,
        stats: SyncRunStats,
        error_message: Optional[str],
    ) -> None:
        run.status = status
        run.completed_at = datetime.utcnow()
        run.events_processed = stats.events_processed
        run.events_created = stats.events_created
        run.events_updated = stats.events_updated
        run.events_deleted = stats.events_deleted
        run.errors = stats.errors
        run.error_message = error_message
        run.details = (run.details or {}) | {"stats": stats.to_dict()}

    def _prune_sync_runs(self, session: Session, sync_id: str) -> None:
        stale_runs = (
            session.query(SyncRun)
            .filter(SyncRun.sync_id == sync_id)
            .order_by(SyncRun.started_at.desc())
            .offset(self.max_runs_per_sync)
            .all()
        )
        for run in stale_runs:
            session.delete(run)

    # ------------------------------------------------------------------
    # Utility helpers

    def _sync_window(self, past_days: int, future_days: int) -> Tuple[datetime, datetime]:
        now = datetime.utcnow()
        start = now - timedelta(days=max(0, past_days))
        end = now + timedelta(days=max(0, future_days))
        return start, end

    def _bootstrap_config_key(self, sync_id: str) -> str:
        return f"sync_bootstrap_complete:{sync_id}"

    def _should_run_bootstrap(self, session: Session, sync_id: str) -> bool:
        key = self._bootstrap_config_key(sync_id)
        record = session.query(ConfigItem).filter(ConfigItem.key == key).first()
        return record is None

    def _mark_bootstrap_complete(self, session: Session, sync_id: str) -> None:
        key = self._bootstrap_config_key(sync_id)
        timestamp = serialize_datetime(datetime.utcnow())
        record = session.query(ConfigItem).filter(ConfigItem.key == key).first()
        if record:
            record.value = timestamp
        else:
            session.add(ConfigItem(key=key, value=timestamp))

    async def _close_adapters(self, contexts: Iterable[EndpointContext]) -> None:
        for ctx in contexts:
            try:
                await ctx.adapter.close()
            except Exception:  # pragma: no cover - defensive
                self.log.warning(
                    "Failed to close adapter",
                    provider_id=ctx.definition.provider_id,
                )
