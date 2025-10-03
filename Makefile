# Simple Makefile for development tasks

.PHONY: help dev build run test clean logs


help:
	@echo "Orbit Development Commands:"
	@echo "  make dev     - Start development container with shell"
	@echo "  make build   - Build the Docker image"
	@echo "  make run     - Run the API server"
	@echo "  make test    - Run tests (when implemented)"
	@echo "  make contract-tests - Run OpenAPI contract suite"
	@echo "  make logs    - View container logs"
	@echo "  make clean   - Clean up containers and images"
	@echo ""
	@echo "Inside Container Commands:"
	@echo "  make spike      - Run auth spike test"
	@echo "  make check-env  - Check environment variables"
	@echo "  make calendars  - List available calendars"
	@echo "  make server     - Start API server"

dev:
	docker compose up --build orbit-dev

build:
	docker compose build

run:
	docker compose up orbit-dev

# Run test suite inside Docker (override command). Pass ARGS="<pytest args>" to filter.
test:
	@echo "Running tests inside docker compose..."
	docker compose run --rm \
		-e ORBIT_API_KEY=$${ORBIT_API_KEY:-testkey} \
		orbit-dev bash -c "python -c 'from app.infra.db import create_tables; create_tables()' && pytest -q $${ARGS}"

test-skylight:
	python test_skylight.py

show-categories:
	python show_categories.py

show-skylight:
	python show_skylight_events.py

show-apple:
	python show_apple_events.py

test-full-sync:
	python test_full_sync.py

contract-tests:
	bash scripts/run-contract-tests.sh -q

logs:
	docker compose logs -f orbit-dev

clean:
	docker compose down
	docker compose down --volumes
	docker system prune -f

# Quick commands for running inside container
spike:
	python spike_auth.py

check-env:
	python scripts/test_tools/check_env.py

calendars:
	python list_calendars.py

server:
	uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
