# Tests Directory

- `unit/` – fast pytest suites and fixtures that require no external services.
- `integration/` – MCP and API integration suites that expect running backing services.

Manual CLI helpers now live in `scripts/test_tools/` to keep pytest discovery focused.
