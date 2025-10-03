import pytest

from app.api.mcp_models import MCPToolCallRequest
from app.mcp.handlers import protocol_handlers


def test_format_tool_response_prefers_start_at():
    result = {
        "success": True,
        "events": [
            {
                "id": "evt-1",
                "title": "Morning Sync",
                "start_at": "2025-01-01T09:00:00",
                "end_at": "2025-01-01T10:00:00",
            }
        ],
        "period": "today",
        "count": 1,
    }

    formatted = protocol_handlers.format_tool_response("list_events", result)
    assert "Morning Sync" in formatted
    # 09:00:00 should render in 12-hour clock
    assert "09:00 AM" in formatted


@pytest.mark.asyncio
async def test_call_mcp_tool_search_structured_content(monkeypatch):
    async def fake_search(arguments, req_id=1):
        return {
            "success": True,
            "query": arguments.get("query", ""),
            "results": [
                {
                    "id": "evt-123",
                    "title": "Strategy Review",
                    "start_at": "2025-01-02T14:30:00",
                    "end_at": "2025-01-02T15:30:00",
                    "location": "HQ",
                    "notes": "Quarterly planning",
                }
            ],
            "count": 1,
        }

    monkeypatch.setattr(protocol_handlers, "handle_search", fake_search)

    request = MCPToolCallRequest(name="search", arguments={"query": "strategy"})
    response = await protocol_handlers.call_mcp_tool(request, "token")

    assert response.error is None
    assert response.result is not None
    structured = response.result.get("structuredContent")
    assert structured is not None
    assert structured["results"][0]["start_at"] == "2025-01-02T14:30:00"
    # Legacy key maintained for compatibility
    assert structured["results"][0]["start"] == "2025-01-02T14:30:00"
