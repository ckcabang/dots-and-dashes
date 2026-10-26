.PHONY: setup up test typecheck

# Install dependencies and the browser Playwright drives.
setup:
	uv sync
	uv run playwright install chromium

# Start the app and Postgres at http://localhost:8000.
up:
	docker compose up --build

# Run the unit, integration and browser suites. They use the Compose `db`
# service unless TEST_DATABASE_URL points at another Postgres.
test:
	@if [ -z "$$TEST_DATABASE_URL" ]; then docker compose up -d --wait db; fi
	uv run pytest

typecheck:
	uv run mypy
