"""
Protocol handlers for MCP (Model Context Protocol) integration.

This module contains the main router logic and response formatting:
- Tool discovery and validation
- Tool execution routing
- Response formatting for different tool types
- Error handling and safety wrappers
"""

import json as jsonlib
from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ...api.auth import require_scope, verify_hybrid_auth
from ...api.mcp_models import (
    MCPListToolsResponse,
    MCPToolCallRequest,
    MCPToolCallResponse,
)
from ...api.mcp_tools import get_all_tools, get_tool_by_name
from ...core.logging import logger
from .event_handlers import (
    handle_create_event,
    handle_delete_event,
    handle_list_events,
    handle_update_event,
)
from .search_handlers import handle_search
from .sync_handlers import (
    handle_get_sync_status,
    handle_list_family_events,
    handle_sync_now,
)

router = APIRouter(prefix="/mcp")


async def safe_tools_call(func, arguments, req_id=1):
    """Safety net to prevent errors from rendering as '0 items'"""
    try:
        return await func(arguments, req_id=req_id)
    except Exception as e:
        fallback = {
            "items": [],
            "count": 0,
            "query": arguments.get("query", ""),
            "success": False,
            "error": str(e),
        }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {"type": "text", "text": f"Error (handled): {e}"},
                    {"type": "text", "text": jsonlib.dumps(fallback)}
                ],
                "structuredContent": fallback,
                "isError": True
            }
        }


@router.get("/tools", response_model=MCPListToolsResponse)
async def list_mcp_tools(_: str = Depends(verify_hybrid_auth)):
    """List all available MCP tools"""
    try:
        tools = get_all_tools()
        return MCPListToolsResponse(tools=tools)
    except Exception as e:
        logger.error("Failed to list MCP tools", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to list tools")


@router.post("/call", response_model=MCPToolCallResponse)
async def call_mcp_tool(
    request: MCPToolCallRequest,
    _: str = Depends(require_scope("read:events"))
):
    """Execute an MCP tool call"""
    try:
        logger.info("MCP tool call", tool=request.name, args=request.arguments)

        # Validate tool exists
        try:
            get_tool_by_name(request.name)
        except ValueError:
            return MCPToolCallResponse(
                error=f"Unknown tool: {request.name}"
            )

        # Route to appropriate handler
        if request.name == "search":
            result = await safe_tools_call(handle_search, request.arguments, req_id=1)
            # Check if this is a direct JSON-RPC response
            if "jsonrpc" in result:
                return MCPToolCallResponse(
                    result=result["result"],
                    content=result["result"].get("content", []),
                    isError=result["result"].get("isError", False)
                )
            # Otherwise it's a normal result
            result = result
        elif request.name == "echo":
            result = await handle_echo(request.arguments)
        elif request.name == "create_event":
            result = await handle_create_event(request.arguments)
        elif request.name == "list_events":
            result = await handle_list_events(request.arguments)
        elif request.name == "update_event":
            result = await handle_update_event(request.arguments)
        elif request.name == "delete_event":
            result = await handle_delete_event(request.arguments)
        elif request.name == "sync_now":
            result = await handle_sync_now(request.arguments)
        elif request.name == "get_sync_status":
            result = await handle_get_sync_status(request.arguments)
        elif request.name == "list_family_events":
            result = await handle_list_family_events(request.arguments)
        else:
            return MCPToolCallResponse(
                error=f"Handler not implemented for tool: {request.name}"
            )

        # Format response
        if isinstance(result, dict) and "error" in result:
            logger.error("MCP tool execution failed", tool=request.name, error=result["error"])
            return MCPToolCallResponse(
                error=result["error"]
            )
        else:
            formatted_text = format_tool_response(request.name, result)

            # Build content array with text content
            content = [{
                "type": "text",
                "text": formatted_text
            }]

            # For search results, also include structured data for ChatGPT
            if request.name == "search" and result.get("success") and result.get("results"):
                # Add structured content for better ChatGPT parsing
                structured_results = []
                for event in result.get("results", []):
                    # Ensure all events have end times
                    start_time = _extract_datetime(event, "start")
                    end_time = _extract_datetime(event, "end")

                    # If no end time, calculate it as 1 hour after start
                    if start_time and not end_time:
                        try:
                            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                            end_dt = start_dt + timedelta(hours=1)
                            end_time = end_dt.isoformat()
                        except Exception:
                            end_time = start_time

                    structured_results.append({
                        "id": event.get("id", ""),
                        "title": event.get("title", ""),
                        "start_at": start_time,
                        "end_at": end_time,
                        # legacy keys retained for adapters expecting previous schema
                        "start": start_time,
                        "end": end_time,
                        "location": event.get("location", ""),
                        "tz": "America/New_York",  # Add timezone as ChatGPT suggested
                        "notes": event.get("notes", "")
                    })

                # Also include structured content field as suggested
                structured_content_data = {
                    "results": structured_results,
                    "count": result.get("count", 0),
                    "query": result.get("query", ""),
                    "success": True
                }
                result["structuredContent"] = structured_content_data

            return MCPToolCallResponse(
                result=result,
                content=content
            )

    except Exception as e:
        logger.error("MCP tool call failed", tool=request.name, error=str(e))
        return MCPToolCallResponse(
            error=f"Tool execution failed: {str(e)}"
        )


async def handle_echo(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle echo tool call for testing"""
    return {
        "success": True,
        "text": args.get("text", "Hello from Orbit MCP!")
    }


def _extract_datetime(event: Dict[str, Any], primary_key: str) -> str:
    """Return ISO datetime string using *_at fields when available."""
    preferred = f"{primary_key}_at"
    value = event.get(preferred) or event.get(primary_key) or ""
    return value or ""


def _format_event_time_display(raw: str) -> str:
    if not raw:
        return "Time TBD"

    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return dt.strftime("%b %d, %I:%M %p")
    except Exception:
        return raw


def format_tool_response(tool_name: str, result: Dict[str, Any]) -> str:
    """Format tool response for human-readable display"""
    if tool_name == "echo":
        return result.get("text", "")

    elif tool_name == "create_event":
        if result.get("success"):
            return f"Event created: {result.get('message', 'Success')}"
        else:
            return f"Failed to create event: {result.get('error', 'Unknown error')}"

    elif tool_name == "list_events" or tool_name == "list_family_events":
        if result.get("success"):
            events = result.get("events", [])
            period = result.get("period", "today")
            count = len(events)

            if count == 0:
                return f"No events found for {period}"

            if count <= 3:
                response = f"{count} event{'s' if count != 1 else ''} for {period}:\n\n"

                for i, event in enumerate(events, 1):
                    title = event.get("title", "Untitled")
                    start_iso = _extract_datetime(event, "start")
                    start_str = _format_event_time_display(start_iso)

                    response += f"{i}. {title} at {start_str}\n"

                return response
            else:
                return f"{count} events for {period}. First 3: " + ", ".join([
                    event.get("title", "Untitled") for event in events[:3]
                ]) + f" (and {count - 3} more)"
        else:
            return f"Failed to list events: {result.get('error', 'Unknown error')}"

    elif tool_name == "update_event":
        if result.get("success"):
            return f"Event updated: {result.get('message', 'Success')}"
        else:
            return f"Failed to update event: {result.get('error', 'Unknown error')}"

    elif tool_name == "delete_event":
        if result.get("success"):
            return f"Event deleted: {result.get('message', 'Success')}"
        else:
            return f"Failed to delete event: {result.get('error', 'Unknown error')}"

    elif tool_name == "sync_now":
        if result.get("success"):
            return f"Sync completed: {result.get('message', 'Success')}"
        else:
            return f"Failed to sync: {result.get('error', 'Unknown error')}"

    elif tool_name == "get_sync_status":
        if result.get("success"):
            status = result.get("status", "unknown")
            timestamp = result.get("timestamp", "")
            return f"System status: {status} (as of {timestamp})"
        else:
            return f"Failed to get status: {result.get('error', 'Unknown error')}"

    elif tool_name == "search":
        if result.get("success"):
            count = result.get("count", 0)
            query = result.get("query", "")

            if count == 0:
                return f"No events found for '{query}'"

            events = result.get("results", [])
            if count <= 3:
                response = f"Found {count} event{'s' if count != 1 else ''} for '{query}':\n\n"

                for i, event in enumerate(events, 1):
                    title = event.get("title", "Untitled")
                    start_iso = _extract_datetime(event, "start")
                    start_str = _format_event_time_display(start_iso)

                    response += f"{i}. {title} - {start_str}\n"

                return response
            else:
                return f"Found {count} events for '{query}'. First 3: " + ", ".join([
                    event.get("title", "Untitled") for event in events[:3]
                ]) + f" (and {count - 3} more)"
        else:
            return f"Search failed: {result.get('error', 'Unknown error')}"

    else:
        # Fallback for unknown tools
        if result.get("success"):
            return f"Tool '{tool_name}' executed successfully"
        else:
            return f"Tool '{tool_name}' failed: {result.get('error', 'Unknown error')}"
