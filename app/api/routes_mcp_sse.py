"""
MCP (Model Context Protocol) Server-Sent Events and JSON-RPC endpoints.
Extracted from main.py to improve modularity and separation of concerns.
"""

import json as jsonlib
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Security
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.responses import Response as FastAPIResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..api.auth import verify_hybrid_auth
from ..core.logging import logger
from ..infra.db import get_db
from ..mcp.handlers import protocol_handlers
from .mcp_models import MCPToolCallRequest
from .mcp_tools import get_tool_by_name

router = APIRouter()
security = HTTPBearer(auto_error=False)


def sse_message(payload: dict) -> bytes:
    """Convert JSON-RPC response to SSE format"""
    json_data = jsonlib.dumps(payload, ensure_ascii=False)
    return (
        b"event: message\n"
        + b"data: " + json_data.encode("utf-8") + b"\n\n"
    )


def pick_response_mode(accept_header: str) -> str:
    """Pick response mode based on Accept header using q-values when provided."""
    if not accept_header:
        return "json"

    best_mode = "json"
    best_q = -1.0

    for entry in accept_header.split(","):
        entry = entry.strip()
        if not entry:
            continue

        parts = [part.strip() for part in entry.split(";") if part.strip()]
        media_type = parts[0].lower()
        q = 1.0

        for param in parts[1:]:
            if param.startswith("q="):
                try:
                    q = float(param[2:])
                except ValueError:
                    q = 0.0

        if media_type == "text/event-stream":
            mode = "sse"
        elif media_type in {"application/json", "application/*", "*/*"}:
            mode = "json"
        else:
            continue

        if q > best_q or (q == best_q and mode == "json"):
            best_mode = mode
            best_q = q

    return best_mode if best_q >= 0 else "json"


def create_response(response_payload: dict, is_sse_mode: bool):
    """Create either SSE or JSON response based on mode"""
    if is_sse_mode:
        async def event_stream():
            yield sse_message(response_payload)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Orbit-Mode": "sse"
            }
        )
    else:
        return JSONResponse(
            response_payload,
            media_type="application/json; charset=utf-8",
            headers={
                "X-Orbit-Mode": "json",
                "Vary": "Accept"
            }
        )


async def handle_notifications(method: str, req_id: Optional[str], is_sse_mode: bool):
    """Handle MCP notifications (return 202 for notifications)"""
    logger.info(
        "MCP notification received",
        method=method,
        response_mode="sse" if is_sse_mode else "json",
    )

    if req_id is None:
        # Return 202 Accepted for notifications without ID
        if is_sse_mode:
            async def empty_stream():
                yield b""
            return StreamingResponse(
                empty_stream(),
                status_code=202,
                media_type="text/event-stream; charset=utf-8",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Orbit-Mode": "sse"
                }
            )
        else:
            return FastAPIResponse(
                status_code=202,
                headers={"X-Orbit-Mode": "json"}
            )

    # If an id was provided, acknowledge with empty result
    ack_payload = {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return create_response(ack_payload, is_sse_mode)


async def handle_initialize(params: dict, req_id: Optional[str], is_sse_mode: bool):
    """Handle MCP initialize method - no auth required"""
    # Mirror the protocol version from the request if provided
    requested_version = params.get("protocolVersion", "2025-03-26")
    protocol_version = (
        requested_version if requested_version == "2025-06-18" else "2025-03-26"
    )

    # Advertise at least one tool capability so stricter adapters know it's available
    result = {
        "protocolVersion": protocol_version,
        "capabilities": {"tools": {"search": {}}},
        "serverInfo": {"name": "Orbit Calendar Sync", "version": "1.0.0"}
    }
    init_payload = {"jsonrpc": "2.0", "id": req_id, "result": result}
    logger.info(
        "MCP initialize response",
        response_mode="sse" if is_sse_mode else "json",
        result=result,
        rpc_in_id=req_id,
        rpc_out_id=req_id,
        id_match=True,
        protocol_version=protocol_version,
    )
    return create_response(init_payload, is_sse_mode)


async def handle_ping(req_id: Optional[str], is_sse_mode: bool):
    """Handle MCP ping method - no auth required"""
    ping_payload = {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}}
    logger.info("MCP ping response", response_mode="sse" if is_sse_mode else "json")
    return create_response(ping_payload, is_sse_mode)


async def handle_tools_list(req_id: Optional[str], is_sse_mode: bool):
    """Handle MCP tools/list method"""
    # Import the comprehensive MCP tools from the MCP module
    from .mcp_tools import get_all_tools
    tools = get_all_tools()
    # Convert to dict format for JSON-RPC response
    tools_dict = []
    for tool in tools:
        if hasattr(tool, "model_dump"):
            tools_dict.append(tool.model_dump())
        else:  # pragma: no cover - legacy Pydantic 1.x fallback
            tools_dict.append(tool.dict())
    list_response = {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"tools": tools_dict},
    }
    logger.info(
        "MCP tools/list response",
        response_mode="sse" if is_sse_mode else "json",
        tools_count=len(tools_dict),
    )
    return create_response(list_response, is_sse_mode)


async def handle_tools_call(
    params: dict,
    payload: dict,
    req_id: Optional[str],
    is_sse_mode: bool,
    auth_result: str,
):
    """Handle MCP tools/call method"""
    name = params.get("name") or payload.get("name")
    arguments = params.get("arguments") or payload.get("arguments", {})

    try:
        # Check if this is one of the comprehensive tools
        get_tool_by_name(name)

        # Create the request object
        mcp_request = MCPToolCallRequest(name=name, arguments=arguments)

        # Call the handler with proper auth context
        try:
            response = await protocol_handlers.call_mcp_tool(mcp_request, auth_result)
            # Extract the result from the MCP response
            if response.error:
                tool_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: {response.error}",
                        }
                    ]
                }
            else:
                tool_result = {
                    "content": response.content
                }
                # If the original result has structured content, include it
                if (
                    hasattr(response, "result")
                    and response.result
                    and isinstance(response.result, dict)
                    and "structuredContent" in response.result
                ):
                    tool_result["structuredContent"] = response.result[
                        "structuredContent"
                    ]
        except HTTPException as e:
            tool_result = {
                "content": [
                    {"type": "text", "text": f"Error: {e.detail}"}
                ]
            }

    except ValueError:
        # Tool not found in modern system
        tool_result = {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Error: Unknown tool '{name}'. "
                        "List tools with tools/list."
                    ),
                }
            ]
        }

    # Log the complete response being sent
    final_response = {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": tool_result,
    }

    # Mark non-error success explicitly unless this is the strict minimal A2 shape
    if isinstance(final_response.get("result"), dict):
        result_keys = set(final_response["result"].keys())
        is_minimal_a2 = (
            result_keys == {"content"}
            and len(final_response["result"].get("content", [])) == 1
        )
        if ("isError" not in final_response["result"]) and not is_minimal_a2:
            final_response["result"]["isError"] = False

    logger.info(
        "MCP JSON-RPC response",
        method="tools/call",
        tool_name=name,
        response_mode="sse" if is_sse_mode else "json",
        response_size=len(str(final_response))
    )
    return create_response(final_response, is_sse_mode)


@router.post("/sse/")
async def mcp_jsonrpc_handler(
    request: Request,
    payload: dict = Body(...),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db)
):
    """
    MCP JSON-RPC handler with dual-mode support (SSE or JSON based on Accept header).
    Returns proper Server-Sent Events or JSON based on client's Accept header.
    """
    method = payload.get("method")
    req_id = payload.get("id")
    params = payload.get("params", {})
    name_dbg = None
    try:
        name_dbg = (payload.get("params") or {}).get("name") or payload.get("name")
    except Exception:
        name_dbg = None

    # Log request headers for debugging content negotiation
    accept_header = request.headers.get("accept", "")
    user_agent = request.headers.get("user-agent", "")

    # Determine response mode based on Accept header order (JSON first by default)
    response_mode = pick_response_mode(accept_header)
    is_sse_mode = response_mode == "sse"

    logger.info("MCP request headers",
               path="/sse/",
               accept=accept_header,
               mode_chosen=response_mode,
               content_type=request.headers.get("content-type"),
               user_agent=user_agent)

    # Log the inbound request
    logger.info("MCP JSON-RPC",
               method=method,
               name=name_dbg,
               request_id=req_id,
               response_mode=response_mode)

    # Handle notifications (return 202 for notifications as suggested)
    if isinstance(method, str) and method.startswith("notifications/"):
        return await handle_notifications(method, req_id, is_sse_mode)

    # Handle initialization - no auth required
    if method == "initialize":
        return await handle_initialize(params, req_id, is_sse_mode)

    # Handle ping - no auth required
    elif method == "ping":
        return await handle_ping(req_id, is_sse_mode)

    # For tools/list and tools/call, require authentication
    try:
        auth_result = await verify_hybrid_auth(credentials, x_api_key, db)
        logger.info(
            "MCP JSON-RPC authenticated",
            auth_type=auth_result.split(":")[0],
            response_mode=response_mode,
        )
    except HTTPException as e:
        logger.warning(
            "MCP JSON-RPC auth failed",
            error=e.detail,
            response_mode=response_mode,
        )
        error_response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32000,
                "message": f"Authentication required: {e.detail}",
            },
        }
        return create_response(error_response, is_sse_mode)

    if method == "tools/list":
        return await handle_tools_list(req_id, is_sse_mode)

    elif method == "tools/call":
        return await handle_tools_call(
            params,
            payload,
            req_id,
            is_sse_mode,
            auth_result,
        )

    else:
        # Return JSON-RPC error
        error_response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}",
            },
        }
        logger.error(
            "MCP unknown method",
            method=method,
            response_mode=response_mode,
            request_id=req_id,
        )
        return create_response(error_response, is_sse_mode)
