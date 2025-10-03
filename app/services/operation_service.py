"""Service layer for creating and querying operations."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..domain.models import OperationRecord, serialize_datetime
from ..infra.db import get_db_session


class OperationService:
    """Persist and retrieve async operation records."""

    def __init__(self, db: Session):
        self.db = db

    @classmethod
    def create(cls, **kwargs) -> str:
        with get_db_session() as session:
            service = cls(session)
            record = service._create(**kwargs)
            operation_id = record.id
            session.commit()
            return operation_id

    def _reattach_or_query(self, instance: OperationRecord) -> OperationRecord:
        if not self.db.object_session(instance):
            return self.db.query(OperationRecord).get(instance.id)
        return instance

    def _create(
        self,
        *,
        kind: str,
        status: str = "queued",
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        payload: Optional[Dict] = None,
        result: Optional[Dict] = None,
        error: Optional[Dict] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> OperationRecord:
        record = OperationRecord(
            kind=kind,
            status=status,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload or {},
            result=result or {},
            error=error or {},
            started_at=started_at,
            finished_at=finished_at,
        )
        self.db.add(record)
        self.db.flush()
        return self._reattach_or_query(record)

    def create_operation(
        self,
        *,
        kind: str,
        status: str = "queued",
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        payload: Optional[Dict] = None,
        result: Optional[Dict] = None,
        error: Optional[Dict] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> OperationRecord:
        record = self._create(
            kind=kind,
            status=status,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
            result=result,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
        )
        self.db.flush()
        return record

    def update(
        self,
        operation_id: str,
        *,
        status: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[Dict] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> OperationRecord:
        record = self.db.query(OperationRecord).filter(OperationRecord.id == operation_id).first()
        if not record:
            raise ValueError(f"Operation '{operation_id}' not found")

        if status is not None:
            record.status = status
        if result is not None:
            record.result = result
        if error is not None:
            record.error = error
        if started_at is not None:
            record.started_at = started_at
        if finished_at is not None:
            record.finished_at = finished_at

        self.db.add(record)
        self.db.flush()
        return record

    @classmethod
    def update_status(
        cls,
        operation_id: str,
        **kwargs,
    ) -> OperationRecord:
        with get_db_session() as session:
            service = cls(session)
            record = service.update(operation_id, **kwargs)
            session.commit()
            session.refresh(record)
            return record

    def get(self, operation_id: str) -> Optional[dict]:
        record = self.db.query(OperationRecord).filter(OperationRecord.id == operation_id).first()
        return record.to_dict() if record else None

    def list(
        self,
        *,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Tuple[List[dict], Optional[str]]:
        query = self.db.query(OperationRecord).order_by(OperationRecord.created_at.desc(), OperationRecord.id.desc())
        if resource_type:
            query = query.filter(OperationRecord.resource_type == resource_type)
        if resource_id:
            query = query.filter(OperationRecord.resource_id == resource_id)

        if cursor:
            try:
                created_at_str, record_id = cursor.split("::", 1)
                created_at = datetime.fromisoformat(created_at_str.replace("Z", ""))
                query = query.filter(
                    (OperationRecord.created_at < created_at)
                    | (
                        (OperationRecord.created_at == created_at)
                        & (OperationRecord.id < record_id)
                    )
                )
            except Exception:
                pass

        records = query.limit(limit + 1).all()
        next_cursor = None
        if len(records) > limit:
            last = records[limit - 1]
            created_at = serialize_datetime(last.created_at)
            if created_at is None:
                created_at = serialize_datetime(datetime.utcnow())
            next_cursor = f"{created_at}::{last.id}"
            records = records[:limit]

        return [record.to_dict() for record in records], next_cursor
