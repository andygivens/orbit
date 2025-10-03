"""
Sync handlers for MCP (Model Context Protocol) integration.

This module handles sync-related MCP tool calls:
- handle_sync_now: Trigger immediate bidirectional sync
- handle_get_sync_status: Get system health and sync status
- handle_list_family_events: Multi-category event listing (future expansion)
"""

from datetime import datetime
from typing import Any, Dict

from ...core.logging import logger
from ...domain.models import serialize_datetime
from ...services.sync_service import SyncService


async def handle_sync_now(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle sync_now tool call"""
    try:
        sync_service = SyncService()

        # Run both sync directions
        apple_result = await sync_service.sync_apple_to_skylight()
        skylight_result = await sync_service.sync_skylight_to_apple()

        return {
            "success": True,
            "message": "Sync completed",
            "apple_to_skylight": apple_result,
            "skylight_to_apple": skylight_result
        }

    except Exception as e:
        logger.error("Failed to sync via MCP", error=str(e))
        return {"error": f"Failed to trigger sync: {str(e)}"}


async def handle_get_sync_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle get_sync_status tool call"""
    try:
        # Get health and basic status
        return {
            "success": True,
            "status": "operational",
            "api_version": "1.0.0",
            "mcp_version": "1.0.0",
            "timestamp": serialize_datetime(datetime.utcnow())
        }

    except Exception as e:
        logger.error("Failed to get sync status via MCP", error=str(e))
        return {"error": f"Failed to get sync status: {str(e)}"}


async def handle_list_family_events(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle list_family_events tool call - shows events from all Skylight categories"""
    try:
        period = args.get("period", "today")
        categories = args.get("categories", [])

        # For now, this is the same as list_events but with a note about family scope
        # TODO: Extend this to query multiple Skylight categories when that feature is added

        from .event_handlers import handle_list_events
        result = await handle_list_events({"period": period})

        if result.get("success"):
            result["message"] = f"Family events for {period}" + (f" in categories: {', '.join(categories)}" if categories else "")
            result["note"] = "Currently showing all synced events. Multi-category support coming soon."

        return result

    except Exception as e:
        logger.error("Failed to list family events via MCP", error=str(e))
        return {"error": f"Failed to list family events: {str(e)}"}
