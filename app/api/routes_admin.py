from typing import Any, Dict

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..api.auth import require_scope
from ..infra.db import get_db
from ..services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/api-key",
    dependencies=[Depends(require_scope("read:config"))],
)
async def get_api_key(db: Session = Depends(get_db)) -> Dict[str, Any]:
    service = AdminService(db)
    key = service.get_api_key()
    return {"key": key}


@router.post(
    "/api-key",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("write:config"))],
)
async def generate_api_key(db: Session = Depends(get_db)) -> Dict[str, Any]:
    service = AdminService(db)
    key = service.generate_api_key()
    db.commit()
    return {"key": key}
