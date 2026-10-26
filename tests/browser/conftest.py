"""The browser suite drives the app container of the test Compose stack.

`make test` starts that stack; BASE_URL points elsewhere if needed.
"""

import os

import pytest


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("BASE_URL", "http://localhost:58000")
