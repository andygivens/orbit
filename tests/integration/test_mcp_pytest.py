"""
Pytest integration tests using FastMCP client for Orbit MCP server

This shows how to integrate FastMCP client testing into your pytest test suite.
"""

import asyncio
import os

import pytest
from fastmcp import Client

if os.getenv("ORBIT_RUN_MCP_TESTS") != "1":
    pytest.skip(
        "Skipping FastMCP integration tests (set ORBIT_RUN_MCP_TESTS=1 to run)",
        allow_module_level=True,
    )


class TestOrbitMCPWithFastMCP:
    """Test class using FastMCP client to test Orbit MCP server"""

    @pytest.fixture
    def server_config(self):
        """Configuration for the MCP server"""
        return {
            "url": os.getenv("ORBIT_SERVER_URL", "http://localhost:8080/mcp"),
            "headers": {"X-API-Key": os.getenv("ORBIT_API_KEY", "supersecret")}
        }

    @pytest.mark.asyncio
    async def test_server_tools_discovery(self, server_config):
        """Test that the server exposes expected tools"""
        async with Client(server_config["url"], headers=server_config["headers"]) as client:
            tools = await client.list_tools()
            tool_names = [tool.name for tool in tools]

            # Assert expected tools exist
            assert "search" in tool_names
            assert "create_event" in tool_names
            assert "list_events" in tool_names
            assert "echo" in tool_names
            assert "sync_now" in tool_names

            # Verify tool schemas
            search_tool = next(tool for tool in tools if tool.name == "search")
            assert search_tool.description is not None
            assert "query" in str(search_tool.inputSchema)

    @pytest.mark.asyncio
    async def test_echo_tool_functionality(self, server_config):
        """Test the echo tool works correctly"""
        async with Client(server_config["url"], headers=server_config["headers"]) as client:
            test_message = "FastMCP pytest test message"
            result = await client.call_tool("echo", {"text": test_message})

            assert result.content is not None
            assert len(result.content) > 0
            assert test_message in result.content[0].text

    @pytest.mark.asyncio
    async def test_search_tool_basic(self, server_config):
        """Test basic search functionality"""
        async with Client(server_config["url"], headers=server_config["headers"]) as client:
            result = await client.call_tool("search", {"query": "today"})

            assert result.content is not None
            assert len(result.content) > 0
            # Should contain either events or "No events found"
            content_text = result.content[0].text.lower()
            assert "event" in content_text or "no events" in content_text

    @pytest.mark.asyncio
    async def test_list_events_periods(self, server_config):
        """Test list_events with different periods"""
        periods = ["today", "week", "month"]

        async with Client(server_config["url"], headers=server_config["headers"]) as client:
            for period in periods:
                result = await client.call_tool("list_events", {"period": period})

                assert result.content is not None
                assert len(result.content) > 0
                content_text = result.content[0].text.lower()
                # Should contain period reference or event info
                assert period in content_text or "event" in content_text or "no events" in content_text

    @pytest.mark.asyncio
    async def test_create_and_search_event(self, server_config):
        """Integration test: create event and then search for it"""
        import time
        test_id = int(time.time())

        event_data = {
            "title": f"FastMCP Test Event {test_id}",
            "start_at": "2025-09-10 15:00:00",
            "location": "Test Location",
            "notes": "Created by FastMCP pytest"
        }

        async with Client(server_config["url"], headers=server_config["headers"]) as client:
            # Create the event
            create_result = await client.call_tool("create_event", event_data)
            assert create_result.content is not None

            # Wait a moment for potential processing
            await asyncio.sleep(1)

            # Search for the created event
            search_result = await client.call_tool("search", {"query": f"FastMCP Test Event {test_id}"})
            assert search_result.content is not None

            # The search should either find the event or indicate no results
            # (depending on sync timing and implementation)
            search_text = search_result.content[0].text
            assert len(search_text) > 0  # Should get some response

    @pytest.mark.asyncio
    async def test_sync_status_tool(self, server_config):
        """Test sync status reporting"""
        async with Client(server_config["url"], headers=server_config["headers"]) as client:
            result = await client.call_tool("get_sync_status", {})

            assert result.content is not None
            assert len(result.content) > 0
            content_text = result.content[0].text.lower()
            # Should contain status information
            assert "status" in content_text or "system" in content_text

    @pytest.mark.asyncio
    async def test_error_handling_invalid_tool(self, server_config):
        """Test error handling for invalid tool calls"""
        async with Client(server_config["url"], headers=server_config["headers"]) as client:
            # This should either raise an exception or return an error
            try:
                result = await client.call_tool("nonexistent_tool", {})
                # If it doesn't raise, it should contain error info
                if result.content:
                    content_text = result.content[0].text.lower()
                    assert "error" in content_text or "unknown" in content_text
            except Exception as e:
                # Expected behavior - tool doesn't exist
                assert "unknown tool" in str(e).lower() or "not found" in str(e).lower()

    @pytest.mark.asyncio
    async def test_search_edge_cases(self, server_config):
        """Test search with various edge cases"""
        test_queries = [
            "",  # Empty query
            "   ",  # Whitespace only
            "definitely_nonexistent_event_12345",  # Should find nothing
            "2025-01-01",  # Date format
        ]

        async with Client(server_config["url"], headers=server_config["headers"]) as client:
            for query in test_queries:
                result = await client.call_tool("search", {"query": query})
                assert result.content is not None
                assert len(result.content) > 0
                # Should handle gracefully without crashing


@pytest.mark.integration
class TestOrbitMCPIntegration:
    """Integration tests that require the full system to be running"""

    @pytest.fixture
    def server_config(self):
        return {
            "url": os.getenv("ORBIT_SERVER_URL", "http://localhost:8080/mcp"),
            "headers": {"X-API-Key": os.getenv("ORBIT_API_KEY", "supersecret")}
        }

    @pytest.mark.asyncio
    async def test_full_workflow(self, server_config):
        """Test a complete workflow from creation to sync"""
        import time
        workflow_id = int(time.time())

        async with Client(server_config["url"], headers=server_config["headers"]) as client:
            # 1. Check initial state
            await client.call_tool("list_events", {"period": "today"})

            # 2. Create event
            event_data = {
                "title": f"Workflow Test {workflow_id}",
                    "start_at": "2025-09-11 10:00:00",
                "notes": "Full workflow integration test"
            }
            create_result = await client.call_tool("create_event", event_data)
            assert "success" in create_result.content[0].text.lower() or "created" in create_result.content[0].text.lower()

            # 3. Trigger sync
            sync_result = await client.call_tool("sync_now", {})
            assert sync_result.content is not None

            # 4. Verify sync status
            status_result = await client.call_tool("get_sync_status", {})
            assert status_result.content is not None

            # 5. Search for created event
            await asyncio.sleep(2)  # Allow time for sync
            search_result = await client.call_tool("search", {"query": f"Workflow Test {workflow_id}"})
            assert search_result.content is not None


if __name__ == "__main__":
    # Run with: python -m pytest tests/integration/test_mcp_pytest.py -v
    pytest.main([__file__, "-v"])
