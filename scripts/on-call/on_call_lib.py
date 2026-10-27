"""What the On-call tools share: where their tokens come from, the environment
they hand a child process (flyctl or gh), and argument parsing that never
repeats an argument back.

In GitHub Actions the tokens are never in the agent's environment, where its
shell could expand one into an argument: an earlier step writes each to a 0600
file in the directory ON_CALL_TOKENS names, which the agent's file tools are
denied. Run locally, a token can come from the environment instead.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import NoReturn

# Every token the workflow uses, and the ones the Actions runner and the tools
# themselves read.
SECRETS = {
    "FLY_API_TOKEN",
    "FLY_ACCESS_TOKEN",
    "FLY_DEV_API_TOKEN",
    "FLY_PROD_API_TOKEN",
    "GRAFANA_VIEWER_TOKEN",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "ACTIONS_RUNTIME_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
}
# gh reads these to pick another repository or host: never let them through.
REDIRECTS = {"GH_REPO", "GH_HOST"}


def tokens_dir() -> Path | None:
    directory = os.environ.get("ON_CALL_TOKENS")
    return Path(directory) if directory else None


def token(name: str) -> str:
    """The token NAME: from the environment, else from its file in ON_CALL_TOKENS."""
    if value := os.environ.get(name):
        return value
    directory = tokens_dir()
    try:
        return (directory / name).read_text().strip() if directory else ""
    except OSError:
        return ""


def known_secrets() -> list[str]:
    """Every token value this process can see, in its environment or the token files."""
    values = [os.environ[name] for name in SECRETS if os.environ.get(name)]
    if (directory := tokens_dir()) and directory.is_dir():
        for path in directory.iterdir():
            try:
                values.append(path.read_text().strip())
            except OSError:
                pass
    return [value for value in values if value]


def child_env(**keep: str) -> dict[str, str]:
    """This process's environment without any token, plus the ones in `keep`."""
    env = {k: v for k, v in os.environ.items() if k not in SECRETS | REDIRECTS | {"ON_CALL_TOKENS"}}
    env.update(keep)
    return env


class QuietParser(argparse.ArgumentParser):
    """An ArgumentParser whose errors never quote what it was handed: an
    argument could carry a token into the public run log."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: refused: those arguments don't fit the usage above\n")
