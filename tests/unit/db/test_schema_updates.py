"""Unit tests for ensure_schema_updates lightweight migrations."""

from typing import Dict, List
from unittest.mock import MagicMock

import app.core.bootstrap as bootstrap
from app.core.bootstrap import ensure_schema_updates


class FakeInspector:
    """Minimal inspector stub used to drive schema upgrade decisions."""

    def __init__(self, columns: Dict[str, List[Dict[str, str]]], tables: List[str]):
        self._columns = columns
        self._tables = tables

    def get_columns(self, table_name: str):  # pragma: no cover - simple delegate
        return self._columns.get(table_name, [])

    def get_table_names(self):  # pragma: no cover - simple delegate
        return list(self._tables)


def _make_session_stub() -> MagicMock:
    session = MagicMock()
    session.bind = object()
    # ensure apple provider cleanup short-circuits without work
    session.query.return_value.filter.return_value.all.return_value = []
    return session


def _collect_sql(session: MagicMock) -> List[str]:
    return [str(call.args[0]) for call in session.execute.call_args_list]


def test_schema_updates_adds_phase_one_structures(monkeypatch):
    columns = {
        "oauth_tokens": [{"name": "id"}],
        "sync_runs": [{"name": "id"}],
        "sync_cursors": [{"name": "id"}],
        "providers": [
            {"name": "id"},
            {"name": "type"},
            {"name": "type_id"},
        ],
        "provider_types": [{"name": "id"}],
    }
    tables = ["oauth_tokens", "sync_runs", "sync_cursors", "providers", "provider_types"]

    inspector = FakeInspector(columns, tables)
    monkeypatch.setattr(bootstrap, "inspect", lambda _bind: inspector)

    session = _make_session_stub()

    ensure_schema_updates(session)

    statements = _collect_sql(session)

    assert any(
        "ALTER TABLE providers ADD COLUMN config_schema_version" in sql
        for sql in statements
    ), statements
    assert any(
        "ALTER TABLE providers ADD COLUMN config_fingerprint" in sql
        for sql in statements
    ), statements

    for column_name in [
        "adapter_locator",
        "adapter_version",
        "sdk_min",
        "sdk_max",
        "capabilities",
        "config_schema_hash",
    ]:
        assert any(
            f"ALTER TABLE provider_types ADD COLUMN {column_name}" in sql
            for sql in statements
        ), f"Missing DDL for provider_types.{column_name}"

    assert any("CREATE TABLE secrets" in sql for sql in statements), statements
    assert any("CREATE TABLE secret_versions" in sql for sql in statements), statements


def test_schema_updates_noops_when_schema_current(monkeypatch):
    columns = {
        "oauth_tokens": [{"name": "id"}, {"name": "subject"}],
        "sync_runs": [
            {"name": "id"},
            {"name": "sync_id"},
            {"name": "details"},
        ],
        "sync_cursors": [{"name": "id"}, {"name": "provider_id"}],
        "providers": [
            {"name": "id"},
            {"name": "type"},
            {"name": "type_id"},
            {"name": "config_schema_version"},
            {"name": "config_fingerprint"},
        ],
        "provider_types": [
            {"name": "id"},
            {"name": "adapter_locator"},
            {"name": "adapter_version"},
            {"name": "sdk_min"},
            {"name": "sdk_max"},
            {"name": "capabilities"},
            {"name": "config_schema_hash"},
        ],
    }
    tables = [
        "oauth_tokens",
        "sync_runs",
        "sync_cursors",
        "providers",
        "provider_types",
        "secrets",
        "secret_versions",
    ]

    inspector = FakeInspector(columns, tables)
    monkeypatch.setattr(bootstrap, "inspect", lambda _bind: inspector)

    session = _make_session_stub()

    ensure_schema_updates(session)

    assert session.execute.call_count == 0
