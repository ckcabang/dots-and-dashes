"""The environment an On-call tool hands its child process (flyctl or gh).

The On-call workflow puts every token the tools need in the agent's
environment. Each tool passes its child only the one token that child needs,
so no command's output, log or error can carry another (docs/runbooks).
"""

import os

# Every token the workflow sets, and the ones the Actions runner and the tools
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


def child_env(**keep: str) -> dict[str, str]:
    """This process's environment without any token, plus the ones in `keep`."""
    env = {k: v for k, v in os.environ.items() if k not in SECRETS | REDIRECTS}
    env.update(keep)
    return env
