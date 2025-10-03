from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi" / "backend-v1.yaml"


@pytest.fixture(scope="session")
def openapi_spec():
    with SPEC_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.mark.contract
def test_spec_loads(openapi_spec):
    info = openapi_spec.get("info", {})
    assert info.get("title") == "Orbit API v1"
    assert info.get("version") == "0.1.0-draft"


@pytest.mark.contract
def test_required_paths_present(openapi_spec):
    paths = set(openapi_spec.get("paths", {}).keys())
    expected = {
        "/health",
        "/ready",
        "/providers",
        "/providers/{provider_id}",
        "/providers/{provider_id}/events",
        "/syncs",
        "/syncs/{sync_id}",
        "/sync-runs",
        "/sync-runs/summary",
        "/sync-runs/{run_id}",
        "/operations/{operation_id}",
        "/oauth/token",
        "/integrations/mcp/tools",
    }
    missing = expected - paths
    assert not missing, f"Missing paths in OpenAPI draft: {sorted(missing)}"


@pytest.mark.contract
def test_provider_status_enum(openapi_spec):
    provider_schema = openapi_spec["components"]["schemas"]["Provider"]
    status_enum = provider_schema["properties"]["status"]["enum"]
    assert status_enum == ["active", "degraded", "error", "disabled"]


@pytest.mark.contract
def test_examples_present_for_core_schemas(openapi_spec):
    schemas = openapi_spec["components"]["schemas"]
    for name in [
        "ProviderEvent",
        "ProviderEventCreate",
        "ProviderEventUpdate",
        "MergedSyncEvent",
        "Sync",
        "SyncRun",
        "Operation",
        "OperationAccepted",
        "SyncRunAccepted",
        "SyncRunUpsertRequest",
        "SyncRunAggregateSummary",
        "ConfigResponse",
        "LogsResponse",
    ]:
        assert "example" in schemas[name], f"Missing example on schema {name}"


@pytest.mark.contract
def test_operation_example_fields(openapi_spec):
    example = openapi_spec["components"]["schemas"]["Operation"]["example"]
    required = {
        "id",
        "kind",
        "status",
        "resource_type",
        "resource_id",
        "payload",
        "result",
        "error",
        "created_at",
        "started_at",
        "finished_at",
    }
    assert required.issubset(example.keys())
    assert example["status"] in {"queued", "running", "succeeded", "failed"}


@pytest.mark.contract
def test_authorization_responses_present(openapi_spec):
    paths = openapi_spec["paths"]
    public_paths = {
        "/health",
        "/ready",
        "/meta",
        "/oauth/token",
        "/oauth/authorize",
        "/.well-known/oauth-authorization-server",
        "/.well-known/jwks.json",
        "/.well-known/mcp",
    }
    secured_paths = {k: v for k, v in paths.items() if k not in public_paths}
    for path, methods in secured_paths.items():
        for method, operation in methods.items():
            if method not in {"get", "post", "patch", "delete"}:
                continue
            responses = operation.get("responses", {})
            assert "401" in responses, f"401 missing for {path} {method}"
            assert "403" in responses, f"403 missing for {path} {method}"


@pytest.mark.contract
def test_pagination_headers_present(openapi_spec):
    paths = openapi_spec["paths"]
    provider_events_get = paths["/providers/{provider_id}/events"]["get"]
    assert "X-Next-Cursor" in provider_events_get["responses"]["200"].get("headers", {})

    operations_get = paths["/operations"]["get"]
    assert "X-Next-Cursor" in operations_get["responses"]["200"].get("headers", {})

    sync_provider_events_get = paths["/syncs/{sync_id}/providers/{provider_id}/events"]["get"]
    assert "X-Next-Cursor" in sync_provider_events_get["responses"]["200"].get("headers", {})

    sync_runs_get = paths["/sync-runs"]["get"]
    assert "X-Next-Cursor" in sync_runs_get["responses"]["200"].get("headers", {})


@pytest.mark.contract
def test_sync_run_post_contract(openapi_spec):
    paths = openapi_spec["paths"]
    sync_runs = paths["/sync-runs"]
    assert "post" in sync_runs
    request_schema = (
        sync_runs["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    )
    assert request_schema == "#/components/schemas/SyncRunUpsertRequest"
    responses = sync_runs["post"]["responses"]
    assert "201" in responses and "200" in responses


@pytest.mark.contract
def test_sync_run_summary_contract(openapi_spec):
    summary = openapi_spec["paths"]["/sync-runs/summary"]["get"]
    parameters = summary.get("parameters", [])
    assert any(param.get("$ref") == "#/components/parameters/SyncIdParam" for param in parameters)
    assert any(param.get("$ref") == "#/components/parameters/FromParam" for param in parameters)
    assert any(param.get("$ref") == "#/components/parameters/ToParam" for param in parameters)
    response = summary["responses"].get("200")
    assert response is not None
    schema_ref = response["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref == "#/components/schemas/SyncRunAggregateSummary"


@pytest.mark.contract
def test_sync_schema_properties(openapi_spec):
    sync_schema = openapi_spec["components"]["schemas"]["Sync"]
    props = sync_schema["properties"]
    assert props["status"]["enum"] == ["active", "degraded", "error", "disabled"]
    assert "runs" in props
    assert props["runs"]["items"]["$ref"] == "#/components/schemas/SyncRun"
