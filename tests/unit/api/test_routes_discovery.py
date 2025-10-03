import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_discovery import router as discovery_router
from app.main import root


@pytest.fixture
def discovery_client():
    app = FastAPI()
    app.include_router(discovery_router)

    with TestClient(app) as client:
        yield client


def test_mcp_discovery_reports_versioned_endpoints(discovery_client):
    response = discovery_client.get(
        "/.well-known/mcp",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "orbit.example",
        },
    )
    assert response.status_code == 200
    data = response.json()
    endpoints = data["endpoints"]
    assert endpoints["sse"] == "https://orbit.example/api/v1/integrations/sse/"
    assert endpoints["tools"] == "https://orbit.example/api/v1/integrations/mcp/tools"
    assert endpoints["call"] == "https://orbit.example/api/v1/integrations/mcp/call"


@pytest.mark.asyncio
async def test_root_metadata_matches_versioned_paths():
    class DummyRequest:
        headers = {"accept": "application/json"}

    result = await root(DummyRequest(), None)
    endpoints = result["endpoints"]
    assert endpoints["sse"] == "/api/v1/integrations/sse/"
    assert endpoints["mcp_tools"] == "/api/v1/integrations/mcp/tools"
    assert endpoints["mcp_call"] == "/api/v1/integrations/mcp/call"
