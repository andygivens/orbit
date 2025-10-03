from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import routes_mcp, routes_mcp_sse
from app.api.mcp_models import MCPTool


@pytest.fixture
def mcp_sse_client(monkeypatch):
    app = FastAPI()
    app.include_router(routes_mcp_sse.router, prefix="/integrations")

    async def fake_verify_hybrid_auth(credentials, x_api_key, db):
        return "token"

    monkeypatch.setattr(routes_mcp_sse, "verify_hybrid_auth", fake_verify_hybrid_auth)

    @contextmanager
    def fake_get_db():
        yield SimpleNamespace()

    app.dependency_overrides[routes_mcp_sse.get_db] = fake_get_db

    client = TestClient(app)
    return client


def test_initialize_returns_json_payload(mcp_sse_client):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18"},
    }

    response = mcp_sse_client.post("/integrations/sse/", json=payload)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["result"]["protocolVersion"] == "2025-06-18"


def test_tools_call_streams_events(monkeypatch, mcp_sse_client):
    async def fake_call_mcp_tool(request, auth_result):
        return SimpleNamespace(error=None, content=[{"type": "text", "text": "hello"}], result={"content": []})

    monkeypatch.setattr(routes_mcp, "call_mcp_tool", fake_call_mcp_tool)
    monkeypatch.setattr("app.mcp.handlers.protocol_handlers.call_mcp_tool", fake_call_mcp_tool)

    payload = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"query": "today"}},
    }

    with mcp_sse_client.stream(
        "POST",
        "/integrations/sse/",
        json=payload,
        headers={"Accept": "text/event-stream"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = b"".join(response.iter_bytes())

    assert b"event: message" in body
    assert b"hello" in body


def test_tools_list_requires_auth(monkeypatch, mcp_sse_client):
    async def fake_verify_hybrid_auth(credentials, x_api_key, db):
        raise HTTPException(status_code=401, detail="invalid token")

    monkeypatch.setattr(routes_mcp_sse, "verify_hybrid_auth", fake_verify_hybrid_auth)

    payload = {
        "jsonrpc": "2.0",
        "id": "req-2",
        "method": "tools/list",
    }

    response = mcp_sse_client.post("/integrations/sse/", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["error"]["message"].startswith("Authentication required")


def test_notifications_endpoint_returns_202_stream(mcp_sse_client):
    payload = {
        "jsonrpc": "2.0",
        "method": "notifications/tool-updated",
    }

    with mcp_sse_client.stream(
        "POST",
        "/integrations/sse/",
        json=payload,
        headers={"Accept": "text/event-stream"},
    ) as response:
        assert response.status_code == 202
        assert response.headers["content-type"].startswith("text/event-stream")


def test_default_accept_header_returns_json(monkeypatch, mcp_sse_client):
    async def fake_call_mcp_tool(request, auth_result):
        return SimpleNamespace(error=None, content=[{"type": "text", "text": "json"}], result={"content": []})

    monkeypatch.setattr(routes_mcp, "call_mcp_tool", fake_call_mcp_tool)
    monkeypatch.setattr("app.mcp.handlers.protocol_handlers.call_mcp_tool", fake_call_mcp_tool)

    payload = {
        "jsonrpc": "2.0",
        "id": "req-3",
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"query": "week"}},
    }

    response = mcp_sse_client.post("/integrations/sse/", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    data = response.json()
    assert data["result"]["content"][0]["text"] == "json"


def test_accept_header_prefers_highest_q_sse(monkeypatch, mcp_sse_client):
    async def fake_call_mcp_tool(request, auth_result):
        return SimpleNamespace(error=None, content=[{"type": "text", "text": "sse"}], result={"content": []})

    monkeypatch.setattr(routes_mcp, "call_mcp_tool", fake_call_mcp_tool)
    monkeypatch.setattr("app.mcp.handlers.protocol_handlers.call_mcp_tool", fake_call_mcp_tool)

    payload = {
        "jsonrpc": "2.0",
        "id": "req-q-sse",
        "method": "tools/call",
        "params": {"name": "search"},
    }

    with mcp_sse_client.stream(
        "POST",
        "/integrations/sse/",
        json=payload,
        headers={"Accept": "application/json;q=0.6, text/event-stream;q=0.9"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")


def test_accept_header_prefers_json_with_higher_q(monkeypatch, mcp_sse_client):
    async def fake_call_mcp_tool(request, auth_result):
        return SimpleNamespace(error=None, content=[{"type": "text", "text": "json"}], result={"content": []})

    monkeypatch.setattr(routes_mcp, "call_mcp_tool", fake_call_mcp_tool)
    monkeypatch.setattr("app.mcp.handlers.protocol_handlers.call_mcp_tool", fake_call_mcp_tool)

    payload = {
        "jsonrpc": "2.0",
        "id": "req-q-json",
        "method": "tools/call",
        "params": {"name": "search"},
    }

    response = mcp_sse_client.post(
        "/integrations/sse/",
        json=payload,
        headers={"Accept": "text/event-stream;q=0.5, application/json;q=0.8"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_accept_header_wildcard_defaults_to_json(monkeypatch, mcp_sse_client):
    async def fake_call_mcp_tool(request, auth_result):
        return SimpleNamespace(error=None, content=[{"type": "text", "text": "wild"}], result={"content": []})

    monkeypatch.setattr(routes_mcp, "call_mcp_tool", fake_call_mcp_tool)
    monkeypatch.setattr("app.mcp.handlers.protocol_handlers.call_mcp_tool", fake_call_mcp_tool)

    payload = {
        "jsonrpc": "2.0",
        "id": "req-q-wild",
        "method": "tools/call",
        "params": {"name": "search"},
    }

    response = mcp_sse_client.post(
        "/integrations/sse/",
        json=payload,
        headers={"Accept": "text/plain, */*;q=0.5"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_notifications_with_id_acknowledged(mcp_sse_client):
    payload = {
        "jsonrpc": "2.0",
        "id": "notif-1",
        "method": "notifications/provider",
    }

    response = mcp_sse_client.post("/integrations/sse/", json=payload)
    assert response.status_code == 200
    assert response.headers["x-orbit-mode"] == "json"
    body = response.json()
    assert body == {"jsonrpc": "2.0", "id": "notif-1", "result": {}}


def test_tools_list_streams_sse_payload(monkeypatch, mcp_sse_client):
    tool = MCPTool(name="sample", description="demo", inputSchema={"type": "object"})

    monkeypatch.setattr("app.api.mcp_tools.get_all_tools", lambda: [tool])

    with mcp_sse_client.stream(
        "POST",
        "/integrations/sse/",
        json={"jsonrpc": "2.0", "id": "req-tools", "method": "tools/list"},
        headers={"Accept": "text/event-stream"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["x-orbit-mode"] == "sse"
        body = b"".join(response.iter_bytes())

    assert b"sample" in body
    assert b"event: message" in body


def test_tools_call_unknown_tool_returns_error(mcp_sse_client):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-missing",
        "method": "tools/call",
        "params": {"name": "not-real"},
    }

    response = mcp_sse_client.post("/integrations/sse/", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["content"][0]["text"].startswith("Error: Unknown tool")
    assert body["result"]["content"][0]["type"] == "text"


def test_auth_failure_sse_returns_event_stream(monkeypatch, mcp_sse_client):
    async def fake_verify_hybrid_auth(credentials, x_api_key, db):
        raise HTTPException(status_code=401, detail="invalid token")

    monkeypatch.setattr(routes_mcp_sse, "verify_hybrid_auth", fake_verify_hybrid_auth)

    with mcp_sse_client.stream(
        "POST",
        "/integrations/sse/",
        json={"jsonrpc": "2.0", "id": "auth", "method": "tools/list"},
        headers={"Accept": "text/event-stream"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["x-orbit-mode"] == "sse"
        body = b"".join(response.iter_bytes())

    assert b"Authentication required" in body
    assert b"event: message" in body
