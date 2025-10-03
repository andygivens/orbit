# Orbit – Extensible Calendar Sync Platform

Orbit is a provider-extensible calendar orchestration service. It keeps calendars in sync across pluggable adapters, starting with Apple iCloud (CalDAV) and Skylight frames, while leaving room for future providers to be dropped in without touching the core. The backend is a FastAPI application with a scheduler, adapter registry, and operations tooling; the frontend is a Vite + React dashboard packaged with the same service.

## What Orbit Provides
- Two-way calendar synchronisation with configurable direction, date windows, and conflict handling.
- A web dashboard for managing providers, sync definitions, and manual actions.
- A versioned REST API and MCP tools for automation, assistants, and observability.
- Structured logging, readiness checks, and per-run metrics for operations teams.
- An adapter SDK so additional calendar systems can be integrated behind a stable contract.

## Getting Started

### 1. Clone & enter the repo
```bash
git clone https://github.com/your-org/orbit.git
cd orbit
```

### 2. Create your env file
```bash
cp .env.example .env
```

The template ships with commented examples. Runtime secrets (admin password, OAuth client secret, API key) are created on boot and surfaced once in the logs/Admin UI. Uncomment only the settings you need to override (logging level, database location, scheduler cadence, etc.).

### 3. Start the local stack
```bash
docker compose up --build orbit-dev
```

That command builds the images (including the frontend assets) and starts the main API container with live reload enabled. Add `-d` to detach or include additional services as needed.

### 4. Explore the app
- API root: `http://localhost:8080`
- API docs: `http://localhost:8080/docs`
- Admin UI: `http://localhost:8080/`

On first startup the service seeds an `admin` user and prints the one-time password in the boot banner. Capture it from the logs, sign in, then rotate the credential.

### Common Development Tasks
- `docker compose run --rm orbit-dev bash -c "pytest -q"` – backend tests inside the container.
- `docker compose run --rm orbit-dev bash -c "ruff check"` – backend linting (adjust command if you pin another tool).
- `npm --prefix ui run lint` – frontend linting from the host.
- `docker compose up --build orbit-dev` – rebuild images and restart the stack.

## Environment Configuration

Orbit now generates its sensitive credentials (admin password, OAuth client secret, API key) on startup and prints them once to the logs/Admin UI. Copy `.env.example` to `.env` and only uncomment overrides you actually need:

- `LOG_LEVEL` – adjust the root logger level (default `INFO`).
- `DATABASE_URL` – point to a different database engine/host (default SQLite file in the repo).
- `POLL_INTERVAL_SEC` – change the default scheduler cadence between sync runs.
- `SYNC_WINDOW_DAYS_PAST` / `SYNC_WINDOW_DAYS_FUTURE` – tune historical and future windows for event ingestion.
- `ORBIT_API_KEY` – optional: pre-provision the admin API key for automated deployments; otherwise generate and manage it from the Admin UI.

Leave provider credentials out of `.env`; add real adapters via the UI or API so secrets live in Orbit’s store instead of environment variables.

## Architecture at a Glance
- **Adapters** (`adapters/`): Implement the Orbit provider SDK and register capabilities.
- **Core Services** (`app/`): FastAPI routers, scheduler, sync orchestration, and persistence.
- **UI** (`ui/`): Vite + React dashboard bundled into `app/static/ui` for production.
- **Operations & Observability**: Readiness and health endpoints, structured logging, and per-operation metrics.
- **MCP Tools**: Expose Orbit capabilities (listing providers, triggering syncs, checking status) to assistants.

## Documentation
- `docs/reference/overview.md` – high-level product and capability summary.
- `docs/reference/api-and-model-reference.md` – REST resources and data contracts.
- `docs/reference/sdk-and-adapters.md` – Adapter SDK expectations and examples.
- `docs/reference/operations.md` – Deployments, runbooks, and rotation procedures.
- `docs/reference/roadmap-index.md` – Active initiatives and planning notes.

## Project Layout
```
orbit/
├── adapters/              # Provider adapters built on the Orbit SDK
├── app/                   # FastAPI application, domain models, services, scheduler
├── docs/                  # Reference guides, plans, architecture notes
├── tests/                 # Pytest suites (unit + integration)
├── ui/                    # React admin interface
├── docker-compose.yml     # Local service definitions
├── pyproject.toml         # Python project configuration
└── package.json           # Frontend tooling configuration
```

## Status & Next Steps
- Current focus: productionising the sync scheduler, broadening provider support, and hardening operations tooling.
- Near-term priorities: improved error handling, metrics surfacing, adapter contract tests.
- For the latest plans, check the roadmap index and docs under `docs/plan/`.

## Contributing
1. Fork the repo and create a feature branch.
2. Run `docker compose run --rm orbit-dev bash -c "pytest -q"` and `npm --prefix ui run lint` before opening a PR.
3. Include documentation updates when you add or change behaviour.

Issues, feature requests, and adapter ideas are welcome—open a discussion in the tracker so we can collaborate on the roadmap.
