.PHONY: setup up test test-logs test-down typecheck check

# Install dependencies and the browser Playwright drives.
setup:
	uv sync --locked
	uv run playwright install chromium

# Start the app and Postgres at http://localhost:8000.
up:
	docker compose up --build

# Run the unit, integration and browser suites against a Compose project of
# this checkout's own (own volume, ports the OS picks), so the dev journal is
# never touched and worktrees can test side by side.
# Integration tests use its Postgres; Playwright drives its app container.
# Pass T to run some tests only, e.g. `make test T=tests/unit`.
TEST_PROJECT := dots-and-dashes-test-$(shell printf '%s' '$(CURDIR)' | cksum | cut -d' ' -f1)
TEST_STACK = COMPOSE_PROJECT_NAME=$(TEST_PROJECT) DB_PORT=0 APP_PORT=0
# The host port the test stack published for a service's container port.
test_port = $$($(TEST_STACK) docker compose port $(1) $(2) | sed 's/.*://')

test:
	$(TEST_STACK) docker compose up -d --build --wait
	TEST_DATABASE_URL=postgresql+psycopg://dots:dots@localhost:$(call test_port,db,5432)/dots_and_dashes_test \
	BASE_URL=http://localhost:$(call test_port,app,8000) \
	uv run pytest $(T)

test-logs:
	$(TEST_STACK) docker compose logs

# Stop the test stack and delete its volume.
test-down:
	$(TEST_STACK) docker compose down -v

typecheck:
	uv run mypy

# Everything CI should gate on.
check: typecheck test
