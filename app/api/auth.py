# API authentication middleware with OAuth support
from typing import Optional

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..infra.db import get_db
from ..services.admin_service import AdminService
from ..services.oauth_service import OAuthService

# Allow OAuth validation to inspect missing tokens before raising errors.
security = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db),
) -> str:
    """Verify API key from Authorization header"""
    admin_service = AdminService(db)
    stored_key = admin_service.get_api_key()
    if not stored_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key is not configured. Please generate one in the Admin page."
        )

    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )

    if credentials.credentials != stored_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    return credentials.credentials


async def verify_api_key_header(
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
) -> str:
    """Verify API key from X-API-Key header"""
    admin_service = AdminService(db)
    stored_key = admin_service.get_api_key()
    if not stored_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key is not configured. Please generate one in the Admin page."
        )

    if x_api_key != stored_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    return x_api_key


async def verify_oauth_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db),
    required_scope: Optional[str] = None
) -> str:
    """Verify OAuth Bearer token"""
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Bearer token required",
            headers={
                "WWW-Authenticate": (
                    'Bearer realm="orbit", error="invalid_token", '
                    'error_description="Bearer token required"'
                )
            },
        )

    oauth_service = OAuthService(db)
    token = oauth_service.validate_access_token(
        credentials.credentials,
        required_scope=required_scope,
    )

    if not token:
        # Return proper Bearer challenge for expired/invalid tokens
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={
                "WWW-Authenticate": (
                    'Bearer realm="orbit", error="invalid_token", '
                    'error_description="The access token expired or is invalid"'
                )
            },
        )

    return token.client_id


async def verify_hybrid_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
    required_scope: Optional[str] = None,
) -> str:
    """
    Verify authentication using either API key OR OAuth token.

    Priority:
    1. X-API-Key header (admin access)
    2. Authorization: Bearer <oauth_token>

    Returns:
    - For API key: the API key string
    - For OAuth: the client_id
    """
    # Try API key first (admin access)
    if x_api_key:
        admin_service = AdminService(db)
        stored_key = admin_service.get_api_key()
        if stored_key and x_api_key == stored_key:
            return f"api_key:{x_api_key}"
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key"
            )

    # Try OAuth token
    if credentials and credentials.scheme.lower() == "bearer":
        oauth_service = OAuthService(db)
        token = oauth_service.validate_access_token(
            credentials.credentials,
            required_scope=required_scope,
        )

        if token:
            return f"oauth:{token.client_id}"

    # No valid authentication found
    raise HTTPException(
        status_code=401,
        detail=(
            "Authentication required. Provide X-API-Key header or "
            "Authorization: Bearer <token>"
        ),
        headers={
            "WWW-Authenticate": (
                'Bearer realm="orbit", error="invalid_token", '
                'error_description="Authentication required"'
            )
        },
    )


def require_scope(scope: str):
    """Dependency factory for OAuth scope requirements"""
    async def _verify_scope(
        credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
        x_api_key: Optional[str] = Header(default=None),
        db: Session = Depends(get_db),
    ) -> str:
        return await verify_hybrid_auth(
            credentials,
            x_api_key,
            db,
            required_scope=scope,
        )

    return _verify_scope
