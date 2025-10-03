"""
OAuth and MCP discovery endpoints for the Orbit application.
Extracted from main.py to improve modularity and separation of concerns.
"""

from typing import Any, Dict

from fastapi import APIRouter, Request

from ..core.logging import logger

router = APIRouter()


def _external_base_url(request: Request) -> str:
    """Build external base URL using forwarded headers when available."""
    xf_proto = request.headers.get("x-forwarded-proto")
    xf_host = request.headers.get("x-forwarded-host")
    if xf_proto and xf_host:
        return f"{xf_proto}://{xf_host}"
    # Fallback to request url
    return f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"


@router.get("/.well-known/oauth-authorization-server")
async def oauth_discovery(request: Request) -> Dict[str, Any]:
    """OAuth 2.0 Authorization Server Discovery (RFC 8414)"""
    base_url = _external_base_url(request)

    discovery = {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "jwks_uri": f"{base_url}/.well-known/jwks.json",
        "registration_endpoint": f"{base_url}/oauth/register",
        "scopes_supported": ["read:events", "write:events"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "code_challenge_methods_supported": ["S256"]
    }

    logger.info("OAuth discovery requested", base_url=base_url)
    return discovery


@router.get("/.well-known/mcp")
async def mcp_discovery(request: Request) -> Dict[str, Any]:
    """MCP (Model Context Protocol) discovery endpoint"""
    base_url = _external_base_url(request)

    discovery = {
        "version": "2025-03-26",
        "capabilities": {
            "tools": {"list": True, "call": True},
            "resources": {"list": False, "read": False},
            "prompts": {"list": False, "get": False}
        },
        "endpoints": {
            "sse": f"{base_url}/api/v1/integrations/sse/",
            "tools": f"{base_url}/api/v1/integrations/mcp/tools",
            "call": f"{base_url}/api/v1/integrations/mcp/call"
        },
        "auth": {
            "oauth2": {
                "authorization_url": f"{base_url}/oauth/authorize",
                "token_url": f"{base_url}/oauth/token",
                "scopes": ["read:events", "write:events"]
            }
        }
    }

    logger.info("MCP discovery requested", base_url=base_url)
    return discovery


@router.get("/.well-known/jwks.json")
async def jwks() -> Dict[str, Any]:
    """JSON Web Key Set (JWKS) endpoint - placeholder for future JWT support"""
    return {"keys": []}
