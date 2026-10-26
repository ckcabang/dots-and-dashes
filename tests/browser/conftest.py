"""The browser suite drives the app at BASE_URL.

`make test` starts the test Compose stack and points BASE_URL at its app.
"""

import os

import pytest


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get("BASE_URL")
    if not url:
        pytest.exit("Set BASE_URL, or run the tests with `make test`")
    return url
