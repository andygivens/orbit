"""Background processor for queued operations (troubleshooting remediations)."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..core.logging import logger
from ..domain.models import OperationRecord, Provider
from ..infra.db import get_db_session
from ..providers.registry import ProviderRegistry, provider_registry
from .operation_service import OperationService

SUPPORTED_KINDS = {
    "troubleshoot_duplicate_resolve",
    "troubleshoot_orphan_delete",
    "troubleshoot_orphan_pull",
}


class OperationProcessor:
    """Poll operation records and execute queued remediation actions."""

    def __init__(
        self,
        *,
        session_factory=get_db_session,
        registry: ProviderRegistry = provider_registry,
        interval: float = 15.0,
        batch_size: int = 10,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.interval = interval
        self.batch_size = batch_size
        self.log = logger.bind(component="operation_processor")
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        self.log.info("Operation processor started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.log.info("Operation processor stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.process_batch(self.batch_size)
            except Exception as exc:  # pragma: no cover - defensive logging
                self.log.exception("operation_processor.batch_failed", error=str(exc))
            await asyncio.sleep(self.interval)

    async def process_batch(self, limit: int) -> None:
        operations = self._fetch_pending_operations(limit)
        if not operations:
            return

        for operation in operations:
            await self._process_operation(operation)

    def _fetch_pending_operations(self, limit: int) -> List[Dict[str, Any]]:
        with self.session_factory() as session:
            records: Sequence[OperationRecord] = (
                session.query(OperationRecord)
                .filter(OperationRecord.kind.in_(SUPPORTED_KINDS))
                .filter(OperationRecord.status == "queued")
                .order_by(OperationRecord.created_at.asc())
                .limit(limit)
                .all()
            )

            now = datetime.utcnow()
            materialized: List[Dict[str, Any]] = []
            for record in records:
                record.status = "running"
                record.started_at = record.started_at or now
                session.add(record)
                materialized.append(record.to_dict())

            if records:
                session.commit()

        return materialized

    async def _process_operation(self, operation: Dict[str, Any]) -> None:
        kind = operation.get("kind")
        operation_id = operation.get("id")
        payload = operation.get("payload") or {}

        handlers = {
            "troubleshoot_duplicate_resolve": self._handle_duplicate_resolve,
            "troubleshoot_orphan_delete": self._handle_orphan_delete,
            "troubleshoot_orphan_pull": self._handle_orphan_pull,
        }

        handler = handlers.get(kind)
        if not handler:
            await self._mark_failed(operation_id, f"Unsupported operation kind '{kind}'")
            return

        try:
            await handler(operation, payload)
        except Exception as exc:  # pragma: no cover - defensive logging
            self.log.exception(
                "operation_processor.handler_failed",
                operation_id=operation_id,
                kind=kind,
                error=str(exc),
            )
            await self._mark_failed(operation_id, str(exc))

    async def _handle_duplicate_resolve(
        self,
        operation: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> None:
        operation_id = operation.get("id")
        action = payload.get("action")
        if action != "delete":
            await self._mark_succeeded(operation_id, result={"note": "No external work required."})
            return

        targets: Iterable[Dict[str, Any]] = payload.get("targets") or []
        errors: List[str] = []
        for target in targets:
            provider_id = target.get("provider_id")
            provider_uid = target.get("provider_uid")
            if not provider_id or not provider_uid:
                errors.append("Missing provider metadata for duplicate target")
                continue
            try:
                await self._delete_provider_event(provider_id, provider_uid)
            except Exception as exc:
                errors.append(str(exc))

        if errors:
            await self._mark_failed(operation_id, "; ".join(errors))
        else:
            await self._mark_succeeded(operation_id)

    async def _handle_orphan_delete(
        self,
        operation: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> None:
        provider_id = payload.get("provider_id")
        provider_uid = payload.get("provider_uid")
        if not provider_id or not provider_uid:
            await self._mark_failed(operation.get("id"), "Missing provider orphan metadata")
            return

        await self._delete_provider_event(provider_id, provider_uid)
        await self._mark_succeeded(
            operation.get("id"),
            result={"provider_id": provider_id, "provider_uid": provider_uid},
        )

    async def _handle_orphan_pull(
        self,
        operation: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> None:
        await self._mark_failed(
            operation.get("id"),
            "Pulling provider orphans into Orbit is not yet implemented.",
        )

    async def _delete_provider_event(self, provider_id: str, provider_uid: str) -> None:
        provider = self._load_provider_snapshot(provider_id)
        if not provider:
            raise RuntimeError(f"Provider '{provider_id}' not found")

        type_id = provider["type_id"]
        if not type_id:
            raise RuntimeError(f"Provider '{provider_id}' missing type identifier")

        adapter = self.registry.create(type_id, provider_id, provider["config"])
        await adapter.initialize()
        try:
            await adapter.delete_event(provider_uid)
        finally:
            with suppress(Exception):  # defensive
                await adapter.close()

    def _load_provider_snapshot(self, provider_id: str) -> Optional[Dict[str, Any]]:
        with self.session_factory() as session:
            provider = (
                session.query(Provider)
                .filter(Provider.id == provider_id)
                .first()
            )
            if not provider:
                return None
            type_id = provider.type_id or (
                provider.type.value if provider.type else None
            )
            return {
                "id": provider.id,
                "type_id": type_id,
                "config": dict(provider.config or {}),
                "name": provider.name,
            }

    async def _mark_succeeded(self, operation_id: Optional[str], result: Optional[Dict[str, Any]] = None) -> None:
        if not operation_id:
            return
        with self.session_factory() as session:
            operations = OperationService(session)
            operations.update(
                operation_id,
                status="succeeded",
                result=result,
                finished_at=datetime.utcnow(),
            )
            session.commit()

    async def _mark_failed(self, operation_id: Optional[str], message: str) -> None:
        if not operation_id:
            return
        with self.session_factory() as session:
            operations = OperationService(session)
            operations.update(
                operation_id,
                status="failed",
                error={"message": message},
                finished_at=datetime.utcnow(),
            )
            session.commit()
