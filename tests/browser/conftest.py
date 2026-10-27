"""The browser suite drives the app at BASE_URL, logged in as a User of its own.

`make test` starts the test Compose stack and points BASE_URL at its app, and
TEST_DATABASE_URL at a database on the same Postgres as the app's.

Under headless Chromium here, `.click()` waits forever for the element to be
stable, so submit and press buttons with Enter. A page from a second
`browser.new_context()` never gets focus; a test that starts logged out uses
`page` and `page.context.clear_cookies()` instead.
"""

import os
import subprocess
import sys
from uuid import uuid4

import pytest
from playwright.sync_api import Playwright
from sqlalchemy import make_url

PASSWORD = "correct horse battery staple"
# The app container's database, named in docker-compose.yml.
APP_DATABASE = "dots_and_dashes"


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get("BASE_URL")
    if not url:
        pytest.exit("Set BASE_URL, or run the tests with `make test`")
    return url


@pytest.fixture(scope="session")
def app_database_url() -> str:
    """The app container's database, reached from the host."""
    test_database = os.environ.get("TEST_DATABASE_URL")
    if not test_database:
        pytest.exit("Set TEST_DATABASE_URL, or run the tests with `make test`")
    return make_url(test_database).set(database=APP_DATABASE).render_as_string(
        hide_password=False
    )


@pytest.fixture(scope="session")
def create_user(app_database_url):
    """Create a User in the app's database the way the operator does: with the CLI."""

    def create(*, timezone: str = "UTC") -> str:
        # The stack's journal outlives test runs, so each run has a User of its own.
        email = f"browser-{uuid4().hex[:8]}@example.com"
        subprocess.run(
            [sys.executable, "-m", "dots_and_dashes.cli", "create-user"]
            + ["--email", email, "--timezone", timezone],
            env={
                **os.environ,
                "DATABASE_URL": app_database_url,
                "USER_PASSWORD": PASSWORD,
            },
            check=True,
        )
        return email

    return create


@pytest.fixture(scope="session")
def password() -> str:
    return PASSWORD


@pytest.fixture(scope="session")
def user(create_user) -> str:
    """The User every page starts logged in as: their email."""
    return create_user()


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, playwright: Playwright, base_url, user):
    """Start every page logged in, with the session cookie from logging in once."""
    request = playwright.request.new_context(base_url=base_url)
    response = request.post("/login", form={"email": user, "password": PASSWORD})
    assert response.ok, response.status
    logged_in = request.storage_state()
    request.dispose()
    return {**browser_context_args, "storage_state": logged_in}
