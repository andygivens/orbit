MARKERS = {
    "unit": "Unit tests (fast, isolated)",
    "integration": "Integration tests (touch external services)",
    "e2e": "End-to-end tests exercising full flows",
    "slow": "Slow running tests",
    "auth": "Authentication related tests",
    "sync": "Sync service tests",
    "caldav": "CalDAV client tests",
    "skylight": "Skylight API tests",
    "database": "Database tests",
    "mcp": "MCP server tests",
    "contract": "OpenAPI contract tests",
}


def pytest_configure(config):
    for name, description in MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {description}")
