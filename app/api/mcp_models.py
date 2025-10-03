"""MCP-over-HTTP models and request/response types."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MCPToolType(str, Enum):
    """MCP tool types"""
    FUNCTION = "function"


class MCPTool(BaseModel):
    """MCP tool definition"""

    name: str
    description: str
    inputSchema: Dict[str, Any]  # noqa: N815 - external schema contract
    type: MCPToolType = MCPToolType.FUNCTION


class MCPToolCallRequest(BaseModel):
    """Request to call an MCP tool"""

    name: str = Field(..., description="Name of the tool to call")
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments to pass to the tool",
    )


class MCPToolCallResponse(BaseModel):
    """Response from an MCP tool call"""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    content: List[Dict[str, str]] = Field(default_factory=list)


class MCPListToolsResponse(BaseModel):
    """Response listing all available MCP tools"""
    tools: List[MCPTool]


class MCPErrorResponse(BaseModel):
    """Error response for MCP calls"""
    error: str
    details: Optional[str] = None
