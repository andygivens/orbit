"""
Production-ready FastMCP-style testing integration for Orbit MCP Server

This module provides a FastMCP-compatible client that works with your
authentication system, plus pytest integration examples.
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
import pytest

if os.getenv("ORBIT_RUN_MCP_TESTS") != "1":
    pytest.skip(
        "Skipping Orbit MCP integration tests (set ORBIT_RUN_MCP_TESTS=1 to run)",
        allow_module_level=True,
    )


@dataclass
class ToolInfo:
    """Tool information structure compatible with FastMCP"""
    name: str
    description: str
    inputSchema: Dict[str, Any]  # noqa: N815 - mirrors external schema


@dataclass
class CallResult:
    """Tool call result structure compatible with FastMCP"""
    content: List[Dict[str, Any]]
    error: Optional[str] = None

    @property
    def text(self) -> str:
        """Get text content (FastMCP compatibility)"""
        if self.content and self.content[0].get('text'):
            return self.content[0]['text']
        return ""


class OrbitMCPClient:
    """
    FastMCP-style client for Orbit MCP server with authentication support.

    This provides the same interface as FastMCP Client but handles your
    custom authentication requirements.
    """

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Async context manager entry"""
        self.client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.client:
            await self.client.aclose()

    async def list_tools(self) -> List[ToolInfo]:
        """List available tools (FastMCP compatible)"""
        if not self.client:
            raise RuntimeError("Client not initialized. Use async with context manager.")

        response = await self.client.get(
            f"{self.base_url}/tools",
            headers=self.headers
        )
        response.raise_for_status()

        data = response.json()
        tools = []

        for tool_data in data.get("tools", []):
            tools.append(ToolInfo(
                name=tool_data["name"],
                description=tool_data["description"],
                inputSchema=tool_data["inputSchema"]
            ))

        return tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> CallResult:
        """Call a tool (FastMCP compatible)"""
        if not self.client:
            raise RuntimeError("Client not initialized. Use async with context manager.")

        call_data = {
            "name": tool_name,
            "arguments": arguments
        }

        response = await self.client.post(
            f"{self.base_url}/call",
            headers=self.headers,
            json=call_data
        )
        response.raise_for_status()

        data = response.json()

        if data.get("error"):
            return CallResult(content=[], error=data["error"])

        # Convert to FastMCP-style content format
        content = data.get("content", [])
        if not content and data.get("result"):
            # If no content but has result, create content from result
            result = data["result"]
            if isinstance(result, dict) and "text" in result:
                content = [{"type": "text", "text": result["text"]}]
            else:
                content = [{"type": "text", "text": str(result)}]

        return CallResult(content=content, error=None)


# Pytest integration
class TestOrbitMCPWithCustomClient:
    """
    Test suite using custom FastMCP-style client.

    Usage:
        pytest tests/integration/test_orbit_mcp_integration.py -v
    """

    @pytest.fixture
    def mcp_client(self):
        """Fixture providing MCP client"""
        server_url = os.getenv("ORBIT_MCP_URL", "http://localhost:8080/mcp")
        api_key = os.getenv("ORBIT_API_KEY", "supersecret")
        return OrbitMCPClient(server_url, api_key)

    @pytest.mark.asyncio
    async def test_tools_discovery(self, mcp_client):
        """Test tool discovery works"""
        async with mcp_client as client:
            tools = await client.list_tools()
            assert len(tools) > 0

            tool_names = [t.name for t in tools]
            assert "search" in tool_names
            assert "echo" in tool_names
            assert "create_event" in tool_names

    @pytest.mark.asyncio
    async def test_echo_functionality(self, mcp_client):
        """Test echo tool"""
        async with mcp_client as client:
            result = await client.call_tool("echo", {"text": "pytest test"})
            assert result.error is None
            assert "pytest test" in result.text

    @pytest.mark.asyncio
    async def test_search_functionality(self, mcp_client):
        """Test search tool"""
        async with mcp_client as client:
            result = await client.call_tool("search", {"query": "today"})
            assert result.error is None
            assert len(result.text) > 0
            # Should contain either events or "No events found"
            assert "event" in result.text.lower() or "no events" in result.text.lower()

    @pytest.mark.asyncio
    async def test_event_listing(self, mcp_client):
        """Test event listing"""
        async with mcp_client as client:
            result = await client.call_tool("list_events", {"period": "today"})
            assert result.error is None
            assert len(result.text) > 0

    @pytest.mark.asyncio
    async def test_event_creation(self, mcp_client):
        """Test event creation"""
        import time
        test_id = int(time.time())

        event_data = {
            "title": f"Pytest Test Event {test_id}",
            "start_at": "2025-09-10 15:00:00",
            "notes": "Created by pytest"
        }

        async with mcp_client as client:
            result = await client.call_tool("create_event", event_data)
            assert result.error is None
            # Should indicate success
            assert "success" in result.text.lower() or "created" in result.text.lower()

    @pytest.mark.asyncio
    async def test_sync_operations(self, mcp_client):
        """Test sync functionality"""
        async with mcp_client as client:
            # Test sync status
            status_result = await client.call_tool("get_sync_status", {})
            assert status_result.error is None
            assert "status" in status_result.text.lower()

            # Test manual sync
            sync_result = await client.call_tool("sync_now", {})
            assert sync_result.error is None

    @pytest.mark.asyncio
    async def test_integration_workflow(self, mcp_client):
        """Test complete workflow"""
        import time
        workflow_id = int(time.time())

        async with mcp_client as client:
            # Create event
            event_data = {
                "title": f"Integration Test {workflow_id}",
                "start_at": "2025-09-11 10:00:00"
            }
            create_result = await client.call_tool("create_event", event_data)
            assert create_result.error is None

            # Brief pause
            await asyncio.sleep(1)

            # Search for event
            search_result = await client.call_tool("search", {"query": f"Integration Test {workflow_id}"})
            assert search_result.error is None

            # Trigger sync
            sync_result = await client.call_tool("sync_now", {})
            assert sync_result.error is None


# Usage examples
async def example_basic_usage():
    """Example: Basic usage of the custom client"""
    async with OrbitMCPClient("http://localhost:8080/mcp", "supersecret") as client:
        # List tools
        tools = await client.list_tools()
        print(f"Available tools: {[t.name for t in tools]}")

        # Call echo
        result = await client.call_tool("echo", {"text": "Hello World"})
        print(f"Echo result: {result.text}")


async def example_testing_workflow():
    """Example: Testing a complete workflow"""
    async with OrbitMCPClient("http://localhost:8080/mcp", "supersecret") as client:
        # Create event
        event = {
            "title": "Example Event",
            "start_at": "2025-09-08 14:00:00"
        }
        result = await client.call_tool("create_event", event)
        print(f"Created event: {result.text}")

        # Search for it
        search = await client.call_tool("search", {"query": "Example Event"})
        print(f"Search found: {search.text[:100]}...")


async def example_error_handling():
    """Example: Error handling"""
    async with OrbitMCPClient("http://localhost:8080/mcp", "supersecret") as client:
        try:
            # Try invalid tool
            result = await client.call_tool("nonexistent_tool", {})
            if result.error:
                print(f"Expected error: {result.error}")
        except Exception as e:
            print(f"Exception handled: {e}")


if __name__ == "__main__":
    # Run examples
    async def main():
        print("🚀 FastMCP-style Client Examples")
        print("=" * 40)

        await example_basic_usage()
        print()
        await example_testing_workflow()
        print()
        await example_error_handling()

        print("\n💡 To run pytest tests:")
        print("   pytest tests/integration/test_orbit_mcp_integration.py -v")

    asyncio.run(main())
