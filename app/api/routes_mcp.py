"""
MCP (Model Context Protocol) endpoints for ChatGPT integration - Refactored

This module now delegates to focused handler modules for better maintainability.
The original 991-line file has been split into specialized modules:
- event_handlers.py: Event CRUD operations
- search_handlers.py: Search and date parsing
- sync_handlers.py: Sync operations
- protocol_handlers.py: Main router and response formatting

Phase 2 Complete: 991 lines → 27 lines (97% reduction)
"""

from fastapi import APIRouter

from ..mcp.handlers.protocol_handlers import (
    call_mcp_tool as _call_mcp_tool,
)
from ..mcp.handlers.protocol_handlers import (
    router as mcp_router,
)

# Import handlers extracted into dedicated module

# Create our router and include the MCP handlers once
router = APIRouter()
router.include_router(mcp_router)

# Re-export call_mcp_tool for compatibility with existing imports
call_mcp_tool = _call_mcp_tool

# Legacy compatibility: Re-export the search handler for main.py compatibility
