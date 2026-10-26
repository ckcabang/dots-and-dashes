.PHONY: setup up test test-unit test-integration test-browser test-logs test-down lint typecheck check

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
TEST_STACK = COMPOSE_PROJECT_NAME=$(TEST_PROJECT) DB_PORT=0 APP_PORT=0 FLAG_MONTHLY_REVIEW=on
# The host port the test stack published for a service's container port.
test_port = $$($(TEST_STACK) docker compose port $(1) $(2) | sed 's/.*://')

# Start the test stack, then run pytest on $(1) against it.
define stack_pytest
	$(TEST_STACK) COMPOSE_PROGRESS=quiet docker compose up -d --build --wait
	TEST_DATABASE_URL=postgresql+psycopg://dots:dots@localhost:$(call test_port,db,5432)/dots_and_dashes_test \
	BASE_URL=http://localhost:$(call test_port,app,8000) \
	uv run pytest $(1)
endef

test:
	$(call stack_pytest,$(T))

# The unit suite needs no stack, so it also runs inside the sandbox.
test-unit:
	uv run pytest tests/unit

test-integration:
	$(call stack_pytest,tests/integration)

test-browser:
	$(call stack_pytest,tests/browser)

test-logs:
	$(TEST_STACK) docker compose logs

# Stop the test stack and delete its volume.
test-down:
	$(TEST_STACK) docker compose down -v

# Ruff, and one Alembic head: two migrations off the same parent leave two heads.
lint:
	uv run ruff check
	@test "$$(uv run alembic heads | wc -l)" -eq 1 || { uv run alembic heads; echo "More than one Alembic head: re-point a down_revision." >&2; exit 1; }

typecheck:
	uv run mypy

# Everything CI should gate on.
check: lint typecheck test
