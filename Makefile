.PHONY: setup up test typecheck check

# Install dependencies and the browser Playwright drives.
setup:
	uv sync --locked
	uv run playwright install chromium

# Start the app and Postgres at http://localhost:8000.
up:
	docker compose up --build

# Run the unit, integration and browser suites against a separate Compose
# project (own ports and volume), so the dev journal is never touched.
# Integration tests use its Postgres; Playwright drives its app container.
TEST_STACK = COMPOSE_PROJECT_NAME=dots-and-dashes-test DB_PORT=55432 APP_PORT=58000

test:
	$(TEST_STACK) docker compose up -d --build --wait
	uv run pytest

typecheck:
	uv run mypy

# Everything CI should gate on.
check: typecheck test
