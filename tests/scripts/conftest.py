"""Fixtures for the helper-script tests.

The scripts run on the host, as a human or agent runs them, so these tests need
git and bash but no Compose stack: `uv run pytest tests/scripts` runs them anywhere.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def not_root() -> None:
    """Root ignores file modes, and these tests stand in for a sandbox with them."""
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")


@pytest.fixture(autouse=True)
def writable_again(tmp_path: Path) -> Iterator[None]:
    """Give back write permission a test took away, so tmp_path can be deleted."""
    yield
    subprocess.run(["chmod", "-R", "u+w", str(tmp_path)], check=False)


@pytest.fixture
def git_env(tmp_path: Path) -> dict[str, str]:
    """An environment where git ignores the user's and the system's config."""
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[init]\n\tdefaultBranch = main\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env |= {
        "GIT_CONFIG_GLOBAL": str(gitconfig),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    return env
