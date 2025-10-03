"""
OAuth 2.0 endpoints for external service authentication.
Implements Client Credentials flow for ChatGPT and other services.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..api.auth import require_scope
from ..infra.db import get_db
from ..services.oauth_service import OAuthService
from ..services.user_service import UserService

router = APIRouter(prefix="/oauth", tags=["oauth"])


# Pydantic models for OAuth endpoints
class TokenRequest(BaseModel):
    grant_type: str = "client_credentials"
    scope: str = "read:events,write:events"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    scope: str
    refresh_token: Optional[str] = None  # For MCP long-lived sessions
    subject: Optional[str] = None
    username: Optional[str] = None


class ClientResponse(BaseModel):
    client_id: str
    name: str
    description: str
    scopes: str
    is_active: bool
    created_at: datetime


class CreateClientRequest(BaseModel):
    name: str
    description: str = ""
    scopes: str = "read:events,write:events"


@router.get("/authorize")
async def oauth_authorize(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    state: str = Query(None),
    scope: str = Query("read:events,write:events"),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    db: Session = Depends(get_db)
):
    """
    Minimal OAuth 2.0 Authorization endpoint for Authorization Code + PKCE.
    Issues a code then redirects back to redirect_uri with code and state.
    """
    if response_type != "code":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported_response_type",
        )

    oauth_service = OAuthService(db)

    # Fetch client
    from ..domain.models import OAuthClient as OAuthClientModel

    client = (
        db.query(OAuthClientModel)
        .filter(
            OAuthClientModel.client_id == client_id,
            OAuthClientModel.is_active.is_(True),
        )
        .first()
    )
    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_client",
        )

    # Create code
    code = oauth_service.create_auth_code(
        client,
        redirect_uri,
        scope,
        code_challenge,
        code_challenge_method,
    )
    # Redirect
    from fastapi.responses import RedirectResponse
    redirect = f"{redirect_uri}?code={code}"
    if state:
        redirect += f"&state={state}"
    return RedirectResponse(url=redirect, status_code=302)


@router.options("/token")
async def token_options():
    """Handle CORS preflight for OAuth token endpoint"""
    return JSONResponse(
        content={},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400"
        }
    )


# OAuth 2.0 Token endpoint (RFC 6749)
@router.post("/token", response_model=TokenResponse)
async def create_access_token(
    grant_type: str = Form(...),
    client_id: str = Form(None),
    client_secret: str = Form(None),
    code: str = Form(None),
    redirect_uri: str = Form(None),
    code_verifier: str = Form(None),
    refresh_token: str = Form(None),  # For refresh token flow
    username: str = Form(None),
    password: str = Form(None),
    scope: str = Form(default="read:events,write:events"),
    db: Session = Depends(get_db)
):
    """
    OAuth 2.0 Token Endpoint

    Supports multiple grant types:
    - client_credentials: Machine-to-machine authentication
    - authorization_code: User authorization with PKCE
    - refresh_token: Token refresh for long-lived sessions (MCP)

    Parameters:
    - grant_type: "client_credentials", "authorization_code", or "refresh_token"
    - For client_credentials: client_id, client_secret, scope
    - For authorization_code: client_id, code, redirect_uri, code_verifier
    - For refresh_token: refresh_token (client_id optional for validation)
    """
    from ..core.logging import logger
    logger.info(
        "OAuth token request",
        client_id=client_id,
        grant_type=grant_type,
        requested_scope=scope,
    )
    oauth_service = OAuthService(db)

    if grant_type == "client_credentials":
        # Authenticate client
        client = oauth_service.authenticate_client(client_id, client_secret)
        if not client:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_client",
            )
        # Validate requested scopes against client's allowed scopes
        client_scopes = set(client.scopes.split(","))
        requested_scopes = set(scope.split(","))
        if not requested_scopes.issubset(client_scopes):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_scope",
            )
        try:
            # For client credentials, don't include refresh token by default
            token_data = oauth_service.create_access_token(
                client,
                scope,
                include_refresh=False,
            )
            return TokenResponse(**token_data)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="server_error",
            ) from exc
    elif grant_type == "authorization_code":
        if not all([client_id, code, redirect_uri, code_verifier]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_request",
            )

        from ..domain.models import OAuthClient as OAuthClientModel

        client = (
            db.query(OAuthClientModel)
            .filter(
                OAuthClientModel.client_id == client_id,
                OAuthClientModel.is_active.is_(True),
            )
            .first()
        )
        if not client:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_client",
            )

        token = oauth_service.exchange_auth_code(
            client,
            code,
            redirect_uri,
            code_verifier,
        )
        if not token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_grant",
            )
        return TokenResponse(**token)
    elif grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_request",
            )

        # Refresh the access token
        token_data = oauth_service.refresh_access_token(refresh_token)
        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_grant",
            )

        return TokenResponse(**token_data)
    elif grant_type == "password":
        if not username or not password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_request",
            )

        from ..domain.models import OAuthClient as OAuthClientModel

        effective_client_id = client_id or "orbit_ui"
        client = (
            db.query(OAuthClientModel)
            .filter(
                OAuthClientModel.client_id == effective_client_id,
                OAuthClientModel.is_active.is_(True),
            )
            .first()
        )
        if not client:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_client",
            )

        if client_secret:
            client = oauth_service.authenticate_client(
                effective_client_id,
                client_secret,
            )
            if not client:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid_client",
                )

        user_service = UserService(db)
        user = user_service.authenticate(username, password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_grant",
            )

        # Validate scopes requested
        client_scopes = set(client.scopes.split(","))
        requested_scopes = set(scope.split(","))
        if not requested_scopes.issubset(client_scopes):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_scope",
            )

        token_data = oauth_service.create_access_token(
            client,
            scopes=scope,
            include_refresh=True,
            subject=user.id,
        )
        token_data["username"] = user.username
        return TokenResponse(**token_data)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported_grant_type",
        )


# OAuth Client Management (Admin endpoints)
@router.post(
    "/clients",
    response_model=Dict[str, Any],
)
async def create_oauth_client(
    request: CreateClientRequest,
    _: str = Depends(require_scope("write:config")),
    db: Session = Depends(get_db)
):
    """
    Create a new OAuth client for external services.

    Returns client_id and client_secret (only returned once).
    Requires admin scope ("write:config") or API key.
    """
    oauth_service = OAuthService(db)

    try:
        client_data = oauth_service.create_client(
            name=request.name,
            description=request.description,
            scopes=request.scopes
        )
        return client_data

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create OAuth client: {str(e)}"
        )


@router.get(
    "/clients",
    response_model=List[ClientResponse],
)
async def list_oauth_clients(
    _: str = Depends(require_scope("read:config")),
    db: Session = Depends(get_db)
):
    """
    List all active OAuth clients.
    Requires admin scope ("read:config") or API key.
    """
    oauth_service = OAuthService(db)

    try:
        clients = oauth_service.list_clients()
        return [ClientResponse(**client) for client in clients]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list OAuth clients: {str(e)}"
        )


@router.delete("/clients/{client_id}")
async def deactivate_oauth_client(
    client_id: str,
    _: str = Depends(require_scope("write:config")),
    db: Session = Depends(get_db)
):
    """
    Deactivate an OAuth client and revoke all its tokens.
    Requires admin scope ("write:config") or API key.
    """
    oauth_service = OAuthService(db)

    success = oauth_service.deactivate_client(client_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OAuth client not found"
        )

    return {"detail": "OAuth client deactivated"}


@router.post("/tokens/{access_token}/revoke")
async def revoke_access_token(
    access_token: str,
    _: str = Depends(require_scope("write:config")),
    db: Session = Depends(get_db)
):
    """
    Revoke a specific access token.
    Requires admin scope (`write:config`) or API key.
    """
    oauth_service = OAuthService(db)

    success = oauth_service.revoke_token(access_token)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access token not found"
        )

    return {"detail": "Access token revoked"}
