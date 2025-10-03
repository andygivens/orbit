"""Validate legacy environment variable name compatibility for Settings."""
import importlib


def test_legacy_env_var_mapping(monkeypatch):
    # Ensure only legacy env vars (upper snake) are set, not the new attribute names
    monkeypatch.delenv('orbit_api_key', raising=False)
    monkeypatch.delenv('database_url', raising=False)
    monkeypatch.setenv('ORBIT_API_KEY', 'legacy-secret')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///./legacy.db')

    # Reload settings module to force re-instantiation
    if 'app.core.settings' in importlib.sys.modules:
        importlib.reload(importlib.import_module('app.core.settings'))
    else:
        importlib.import_module('app.core.settings')

    from app.core.settings import settings  # type: ignore

    assert settings.orbit_api_key == 'legacy-secret'
    assert settings.database_url.endswith('legacy.db')
