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
def test_head_provider_operation_present(openapi_spec):
    paths = openapi_spec["paths"]
    assert "/providers/{provider_id}" in paths, "Provider path missing"
    provider_path = paths["/providers/{provider_id}"]
    assert "head" in provider_path, "HEAD operation not defined for /providers/{provider_id}"
    head_op = provider_path["head"]
    # Basic contract: summary and responses
    assert head_op.get("summary", "").lower().startswith("head provider"), "Unexpected summary for HEAD provider"
    responses = head_op.get("responses", {})
    assert "200" in responses, "200 response missing on HEAD provider"
    two_hundred = responses["200"]
    headers = two_hundred.get("headers", {})
    assert "ETag" in headers, "ETag header missing in 200 HEAD provider response"
    # Ensure no content body schema (HEAD typically omits) or if present is empty
    assert "content" not in two_hundred, "HEAD 200 response should not define a content body"
    # Auth error responses still present
    for code in ("401", "403", "404"):
        assert code in responses, f"{code} response expected for HEAD provider"
