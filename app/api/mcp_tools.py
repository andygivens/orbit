"""
MCP tool definitions for Orbit calendar operations.
Defines the tools that can be called via MCP-over-HTTP.
"""

from typing import List

from .mcp_models import MCPTool


def _long_description(*segments: str) -> str:
    """Join description fragments while keeping line lengths manageable."""

    return " ".join(segment.strip() for segment in segments)


MCP_TOOLS: List[MCPTool] = [
    MCPTool(
        name="search",
        description=_long_description(
            "Search calendar events using natural language queries.",
            "Supports date ranges, specific dates, and keyword searches.",
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": _long_description(
                        "Search query (e.g., 'today', 'this week', 'September 2025',",
                        " 'soccer', '2025-09-06').",
                    ),
                }
            },
            "required": ["query"],
        },
    ),
    MCPTool(
        name="echo",
        description="Echo text back for testing",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to echo back",
                }
            },
            "required": ["text"],
        },
    ),
    MCPTool(
        name="create_event",
        description=_long_description(
            "Create a new calendar event that will sync to both Apple Calendar",
            "and Skylight frame.",
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title/summary",
                },
                "start_at": {
                    "type": "string",
                    "description": (
                        "Start date/time in format YYYY-MM-DD HH:MM or "
                        "YYYY-MM-DD HH:MM:SS"
                    ),
                },
                "end_at": {
                    "type": "string",
                    "description": (
                        "End date/time (optional, defaults to 1 hour after start)"
                    ),
                },
                "start": {
                    "type": "string",
                    "description": (
                        "Deprecated. Use start_at. Retained for backward compatibility."
                    ),
                },
                "end": {
                    "type": "string",
                    "description": (
                        "Deprecated. Use end_at. Retained for backward compatibility."
                    ),
                },
                "location": {
                    "type": "string",
                    "description": "Event location (optional)",
                },
                "notes": {
                    "type": "string",
                    "description": "Event notes/description (optional)",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of attendee names (optional, will be added to notes)"
                    ),
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": _long_description(
                        "Skylight categories/people (e.g.,",
                        "['Person A', 'Person B'], ['Person C']).",
                        "If includes 'Dad' or empty, syncs to both Apple and Skylight.",
                        "Other categories only go to Skylight.",
                    ),
                },
                "category": {
                    "type": "string",
                    "description": _long_description(
                        "Single Skylight category (deprecated;",
                        "use categories instead).",
                        "Provided for backward compatibility.",
                    ),
                },
            },
            "required": ["title", "start_at"],
        },
    ),
    MCPTool(
        name="list_events",
        description="List calendar events for a specified time period",
        inputSchema={
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "month"],
                    "description": "Time period to show events for",
                    "default": "today",
                }
            },
        },
    ),
    MCPTool(
        name="update_event",
        description="Update an existing calendar event",
        inputSchema={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID of the event to update",
                },
                "updates": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start_at": {"type": "string"},
                        "end_at": {"type": "string"},
                        "start": {
                            "type": "string",
                            "description": "Deprecated. Use start_at instead."
                        },
                        "end": {
                            "type": "string",
                            "description": "Deprecated. Use end_at instead."
                        },
                        "location": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "description": "Fields to update",
                },
            },
            "required": ["event_id", "updates"],
        },
    ),
    MCPTool(
        name="delete_event",
        description="Delete a calendar event from both Apple Calendar and Skylight",
        inputSchema={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "ID of the event to delete",
                }
            },
            "required": ["event_id"],
        },
    ),
    MCPTool(
        name="sync_now",
        description="Trigger an immediate sync between Apple Calendar and Skylight",
        inputSchema={"type": "object", "properties": {}},
    ),
    MCPTool(
        name="get_sync_status",
        description="Get the current sync status, health, and configuration",
        inputSchema={"type": "object", "properties": {}},
    ),
    MCPTool(
        name="list_family_events",
        description=_long_description(
            "List events from all Skylight categories (not just Dad) to see",
            "what the whole family has going on.",
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "month"],
                    "description": "Time period to show events for",
                    "default": "today",
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": _long_description(
                        "Skylight categories to include (optional,",
                        "defaults to all available).",
                    ),
                    "default": [],
                },
            },
        },
    ),
]


def get_tool_by_name(name: str) -> MCPTool:
    """Get a tool definition by name"""
    for tool in MCP_TOOLS:
        if tool.name == name:
            return tool
    raise ValueError(f"Tool not found: {name}")


def get_all_tools() -> List[MCPTool]:
    """Get all available tools"""
    return MCP_TOOLS
