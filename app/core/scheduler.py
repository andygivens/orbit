# Background scheduler for sync operations
import asyncio
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..core.logging import logger
from ..infra.db import get_db_session
from ..services.operation_service import OperationService
from ..services.sync_definition_service import SyncDefinitionService


class SyncScheduler:
    def __init__(self, sync_service, session_factory=get_db_session):
        self.sync_service = sync_service
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.logger = logger.bind(component="scheduler")
        self.session_factory = session_factory
        self.sync_definitions = []

    async def start(self):
        """Start the background sync scheduler"""
        if self.scheduler is not None:
            self.logger.warning("Scheduler already started")
            return

        self.scheduler = AsyncIOScheduler()

        await self._load_sync_definitions()

        self._schedule_jobs()

        try:
            self.scheduler.start()
            self.logger.info(
                "Sync scheduler started",
                job_count=len(self.scheduler.get_jobs()),
            )
        except Exception as e:
            self.logger.error("Failed to start sync scheduler", error=str(e))

    async def stop(self):
        """Stop the background sync scheduler"""
        if self.scheduler is None:
            return

        self.scheduler.shutdown(wait=True)
        self.scheduler = None
        self.logger.info("Sync scheduler stopped")

    async def trigger_sync_now(self) -> dict:
        """Trigger an immediate sync operation"""
        self.logger.info("Manual sync triggered")
        try:
            await self._load_sync_definitions()
            active_definitions = [
                definition
                for definition in self.sync_definitions
                if definition.enabled
            ]
            if not active_definitions:
                self.logger.warning(
                    "Manual sync requested but no active sync definitions "
                    "are configured"
                )
                return {
                    "status": "skipped",
                    "reason": "no_active_sync_definitions",
                }

            gather_results = await asyncio.gather(
                *[
                    self._run_dynamic_sync(definition.id)
                    for definition in active_definitions
                ]
            )
            return {"status": "success", "result": list(gather_results)}
        except Exception as e:
            self.logger.error("Manual sync failed", error=str(e))
            return {"status": "error", "error": str(e)}

    async def _run_dynamic_sync(self, definition_id: str):
        definition = next(
            (sync for sync in self.sync_definitions if sync.id == definition_id),
            None,
        )
        if not definition:
            self.logger.warning("Sync definition missing", definition_id=definition_id)
            return {"status": "skipped", "reason": "definition missing"}

        self.logger.info(
            "Executing sync definition",
            sync_id=definition.id,
            endpoint_count=len(definition.endpoints),
        )
        operation_id = OperationService.create(
            kind="sync_run",
            status="running",
            resource_type="sync",
            resource_id=definition.id,
            payload={"trigger": "scheduler"},
            started_at=datetime.utcnow(),
        )
        try:
            result = await self.sync_service.run_sync(definition, mode="run")
        except Exception as exc:  # pragma: no cover - defensive logging
            OperationService.update_status(
                operation_id,
                status="failed",
                error={"message": str(exc)},
                finished_at=datetime.utcnow(),
            )
            raise
        else:
            OperationService.update_status(
                operation_id,
                status="succeeded",
                result=result,
                finished_at=datetime.utcnow(),
            )
            return result

    async def refresh_jobs(self) -> None:
        if self.scheduler is None:
            return
        await self._load_sync_definitions()
        self._schedule_jobs()
        self.logger.info(
            "Sync scheduler refreshed",
            job_count=len(self.scheduler.get_jobs()),
        )

    def _schedule_jobs(self) -> None:
        if self.scheduler is None:
            return

        self.scheduler.remove_all_jobs()

        if not self.sync_definitions:
            self.logger.warning(
                "No sync definitions available; scheduler will remain idle"
            )
            return

        for definition in self.sync_definitions:
            if not definition.enabled:
                continue
            interval = max(30, definition.interval_seconds)
            job_id = f"sync_{definition.id}"
            self.scheduler.add_job(
                self._run_dynamic_sync,
                trigger=IntervalTrigger(seconds=interval),
                id=job_id,
                name=f"Sync: {definition.name}",
                max_instances=1,
                coalesce=True,
                jitter=30,
                kwargs={"definition_id": definition.id},
            )

    async def _load_sync_definitions(self):
        with self.session_factory() as session:
            service = SyncDefinitionService(session)
            self.sync_definitions = service.list_syncs()
