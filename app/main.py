"""
Orbit Calendar Sync - Main FastAPI Application

A bidirectional calendar sync service between Apple iCloud and Skylight calendars
with MCP (Model Context Protocol) integration for ChatGPT.

This is the main application entry point with focused responsibilities:
- FastAPI app initialization
- Middleware configuration
- Route registration
- Lifespan management
- Basic health endpoints

Complex logic has been extracted to focused modules for better maintainability.
"""

import json as jsonlib
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, RedirectResponse

from .api.routes_admin import router as admin_router
from .api.routes_discovery import router as discovery_router
from .api.routes_mcp import router as mcp_router
from .api.routes_mcp_sse import router as mcp_sse_router
from .api.routes_oauth import router as oauth_router
from .api.routes_operations import router as operations_router
from .api.routes_providers import router as providers_router
from .api.routes_syncs import router as syncs_router
from .api.routes_syncs import sync_runs_router
from .api.routes_troubleshooting import router as troubleshooting_router
from .core.bootstrap import bootstrap_defaults
from .core.logging import configure_logging, logger
from .core.middleware import add_cors_middleware, add_request_logging_middleware
from .core.scheduler import SyncScheduler
from .core.settings import settings
from .domain.models import serialize_datetime
from .infra.db import create_tables, get_db_session
from .services.operation_processor import OperationProcessor
from .services.sync_service import SyncService

# Path to compiled frontend (populated in container build)
FRONTEND_DIST = Path(__file__).parent / "static" / "ui"
TROUBLESHOOTING_UI = Path(__file__).parent / "static" / "troubleshooting" / "index.html"

# Global scheduler instance
scheduler = None
operation_processor: Optional[OperationProcessor] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global scheduler, operation_processor

    # Startup
    logger.info("Starting Orbit application")

    # Configure logging
    configure_logging()

    # Create database tables
    create_tables()
    logger.info("Database tables created")

    # Audit deprecated env vars early
    import os
    deprecated_found = [
        v for v in getattr(settings, "_deprecated_env_vars", []) if os.getenv(v)
    ]
    if deprecated_found:
        logger.warning(
            "Deprecated provider credential env vars detected (ignored)",
            vars=deprecated_found,
            action="remove from .env",
        )

    # Bootstrap default admin user and UI OAuth client
    with get_db_session() as session:
        bootstrap_defaults(session)

    # Initialize and start sync scheduler
    sync_service = SyncService()
    scheduler = SyncScheduler(sync_service)
    await scheduler.start()
    app.state.sync_scheduler = scheduler
    logger.info("Sync scheduler started")

    # Start operation processor (queued troubleshooting remediations)
    operation_processor = OperationProcessor()
    await operation_processor.start()
    app.state.operation_processor = operation_processor

    try:
        yield
    finally:
        # Shutdown
        logger.info("Shutting down Orbit application")
        if scheduler:
            await scheduler.stop()
        app.state.sync_scheduler = None
        logger.info("Sync scheduler stopped")

        if operation_processor:
            await operation_processor.stop()
        app.state.operation_processor = None


# Create FastAPI app
app = FastAPI(
    title="Orbit Calendar Sync",
    description="Bidirectional calendar sync between Apple iCloud and Skylight",
    version="1.0.0",
    lifespan=lifespan
)

api_v1_router = APIRouter(prefix="/api/v1")

# Add middleware
add_cors_middleware(app)
add_request_logging_middleware(app)

# Mount static assets if the UI bundle is present
if FRONTEND_DIST.exists():
    assets_directory = FRONTEND_DIST / "assets"
    if assets_directory.exists():
        app.mount(
            "/ui/assets",
            StaticFiles(directory=str(assets_directory)),
            name="ui-assets",
        )

"""Debug static mount removed intentionally.
If static diagnostic assets are needed later, they can be reintroduced with a
controlled mount (e.g., /internal/debug) behind auth.
"""


# Basic endpoints
@app.get("/", include_in_schema=False)
async def root(request: Request, format: str | None = Query(default=None)):
    """Root endpoint that serves the UI when bundled; JSON metadata otherwise."""

    index_file = FRONTEND_DIST / "index.html"

    accept_header = (request.headers.get("accept") or "").lower()
    wants_json = (
        (format or "").lower() == "json"
        or "application/json" in accept_header
        or "application/*+json" in accept_header
    )

    if index_file.exists() and not wants_json:
        return FileResponse(index_file)

    return {
        "name": "Orbit Calendar Sync MCP Server",
        "version": "1.0.0",
        "description": "Calendar event management API with bidirectional sync",
        "mcp_version": "0.1.0",
        "endpoints": {
            "oauth_discovery": "/.well-known/oauth-authorization-server",
            "mcp_discovery": "/.well-known/mcp",
            "sse": "/api/v1/integrations/sse/",
            "mcp_tools": "/api/v1/integrations/mcp/tools",
            "mcp_call": "/api/v1/integrations/mcp/call",
            "health": "/health"
        }
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "service": "orbit"
    }


@app.get("/ready")
async def ready():
    """Readiness check endpoint"""
    try:
        sync_service = SyncService()
        readiness = await sync_service.check_readiness()

        if readiness.get("status") != "ready":
            logger.warning("Readiness degraded", detail=readiness)
            raise HTTPException(status_code=503, detail=readiness)

        return readiness
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        raise HTTPException(status_code=503, detail="Service not ready")


@api_v1_router.get("/health")
async def api_health():
    return await health()


@api_v1_router.get("/ready")
async def api_ready():
    return await ready()


@api_v1_router.get("/meta")
async def api_meta():
    now = serialize_datetime(datetime.utcnow())
    return {
        "name": app.title,
        "version": app.version,
        "build_hash": None,
        "server_time": now,
        "links": {
            "health": "/api/v1/health",
            "ready": "/api/v1/ready",
            "providers": "/api/v1/providers",
            "syncs": "/api/v1/syncs",
            "oauth_authorize": "/oauth/authorize",
            "oauth_token": "/oauth/token",
            "mcp_discovery": "/.well-known/mcp",
        },
    }
@app.post("/mcp/tools")
async def mcp_list_tools():
    """List available MCP tools for ChatGPT integration (HTTP fallback)"""
    logger.info("MCP tools list requested")

    # Use modern tool definitions
    from .api.mcp_tools import get_all_tools
    tools = get_all_tools()
    tools_dict = [tool.dict() for tool in tools]

    return {"tools": tools_dict}


@app.post("/mcp/search")
async def mcp_search_compat(body: dict = Body(...)):
    """
    Accepts payloads with queries/source_specific_search_parameters and returns
    search results.
    Uses modern search implementation via MCP routes.
    """
    query = ""
    try:
        sssp = body.get("source_specific_search_parameters") or {}
        if isinstance(sssp, dict):
            for v in sssp.values():
                if isinstance(v, list):
                    for item in v:
                        q = (item or {}).get("query")
                        if isinstance(q, str) and q.strip():
                            query = q.strip()
                            break
                if query:
                    break
        if not query:
            qs = body.get("queries") or []
            for q in qs:
                if isinstance(q, str) and q.strip():
                    query = q.strip()
                    break
    except Exception:
        query = ""

    # Use modern search implementation
    from .api.routes_mcp import _handle_search
    result = await _handle_search({"query": query})

    # Format response for compatibility
    if result.get("success"):
        return {"content": [{"type": "text", "text": jsonlib.dumps(result)}]}
    else:
        return {"content": [{"type": "text", "text": jsonlib.dumps({"error": result.get("error", "Search failed")})}]}


# Include API routers

api_v1_router.include_router(admin_router)
api_v1_router.include_router(providers_router)
api_v1_router.include_router(syncs_router)
api_v1_router.include_router(sync_runs_router)
api_v1_router.include_router(operations_router)
api_v1_router.include_router(troubleshooting_router)
api_v1_router.include_router(mcp_router, prefix="/integrations", tags=["mcp"])
api_v1_router.include_router(mcp_sse_router, prefix="/integrations", tags=["mcp-sse"])
api_v1_router.include_router(oauth_router, tags=["oauth"])

app.include_router(api_v1_router)
app.include_router(discovery_router, tags=["discovery"])


@app.get("/ui/troubleshooting", include_in_schema=False)
async def ui_troubleshooting():
    """Serve the troubleshooting mock UI."""
    try:
        html_path = TROUBLESHOOTING_UI.resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Troubleshooting UI not bundled")
    return FileResponse(html_path)


@app.get("/ui/troubleshoot", include_in_schema=False)
async def ui_troubleshoot_alias():
    """Backwards-compatible alias for the troubleshooting UI."""
    return RedirectResponse(url="/ui/troubleshooting")


@app.get("/ui", include_in_schema=False)
@app.get("/ui/{path:path}", include_in_schema=False)
async def ui_app(path: str = ""):
    """Serve the compiled Orbit UI frontend (if bundled)."""
    try:
        frontend_root = FRONTEND_DIST.resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(
            status_code=503, detail="Web UI not bundled in this deployment"
        )

    index_file = frontend_root / "index.html"

    # Directly return the index for initial load or SPA fallbacks
    if not path or path == "index.html":
        if index_file.exists():
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="UI index not found")

    requested_path = (frontend_root / path).resolve()
    if requested_path.is_file() and frontend_root in requested_path.parents:
        return FileResponse(requested_path)

    if index_file.exists():
        return FileResponse(index_file)

    raise HTTPException(status_code=404, detail="UI asset not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
