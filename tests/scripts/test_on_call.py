"""The On-call agent's tools in scripts/on-call/ and its workflow do only what
ADR-0002 allows: read telemetry and the Fly release history, and apply one of
three remedies.

Not a seam (docs/architecture/README.md): the scripts run in GitHub Actions
against Fly and Grafana, so these run them against a fake `flyctl` and a
local HTTP server instead.
"""

import json
import os
import re
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "on-call"
RUNBOOK = ROOT / "docs" / "runbooks" / "README.md"

# Every token the On-call workflow writes to a file in ON_CALL_TOKENS, each set
# to a value the tests can look for.
SECRETS = {
    "FLY_DEV_API_TOKEN": "dev-token-1a2b3c",
    "FLY_PROD_API_TOKEN": "prod-token-4d5e6f",
    "GRAFANA_VIEWER_TOKEN": "viewer-token-7a8b9c",
    "ANTHROPIC_API_KEY": "anthropic-key-0d1e2f",
    "GH_TOKEN": "github-token-3a4b5c",
}
SECRET_NAMES = {*SECRETS, "FLY_API_TOKEN", "FLY_ACCESS_TOKEN", "GITHUB_TOKEN", "ON_CALL_TOKENS"}

# A fake command on PATH: logs its arguments and every secret value its
# environment holds, and prints the canned output for its first argument.
FAKE_COMMAND = """#!/usr/bin/env python3
import json, os, sys
secrets = json.loads(os.environ["FAKE_SECRETS"])
held = sorted(name for name, value in os.environ.items() if value in secrets)
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({
        "args": sys.argv[1:], "token": os.environ.get("FLY_API_TOKEN"), "held": held,
    }) + "\\n")
print(json.loads(os.environ["FAKE_OUTPUT"]).get(" ".join(sys.argv[1:3]), ""))
"""


class Fake:
    """Fake flyctl and gh on PATH that record each call, and the environment
    a script runs in: as in the workflow, every token in its own file in
    ON_CALL_TOKENS and none in the environment."""

    def __init__(self, tmp_path: Path) -> None:
        tokens = tmp_path / "on-call-tokens"
        tokens.mkdir()
        for name, value in SECRETS.items():
            (tokens / name).write_text(value)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name in ["flyctl", "gh"]:
            command = bin_dir / name
            command.write_text(
                FAKE_COMMAND.replace("python3", sys.executable.replace("\\", "/"), 1)
            )
            command.chmod(command.stat().st_mode | stat.S_IEXEC)
        self.log = tmp_path / "calls.log"
        self.log.touch()
        self.releases: list[dict[str, Any]] = []
        # The secrets listing: a list as JSON, or a string printed as it is.
        self.secrets: list[dict[str, Any]] | str = []
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_LOG": str(self.log),
            "FAKE_SECRETS": json.dumps(sorted(SECRETS.values())),
            "ON_CALL_TOKENS": str(tokens),
        }

    def run(
        self, script: str, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        listing = self.secrets if isinstance(self.secrets, str) else json.dumps(self.secrets)
        output = {
            "releases -a": json.dumps(self.releases),
            "secrets list": listing,
            "issue list": "[]",
        }
        environ = {k: v for k, v in os.environ.items() if k not in SECRET_NAMES}
        environ |= {**self.env, "FAKE_OUTPUT": json.dumps(output), **(env or {})}
        return subprocess.run(
            [str(SCRIPTS / script), *args], env=environ, capture_output=True, text=True, cwd=ROOT
        )

    def run_with_tokens_in_env(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        """Run as a human does locally: tokens in the environment, no token files."""
        return self.run(script, *args, env={**SECRETS, "ON_CALL_TOKENS": ""})

    def calls(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def changes(self) -> list[list[str]]:
        """The calls that change an app: everything but reading its releases or secrets."""
        reads = (["releases"], ["secrets", "list"])
        return [
            call["args"]
            for call in self.calls()
            if not any(call["args"][: len(read)] == read for read in reads)
        ]


@pytest.fixture
def fly(tmp_path: Path) -> Fake:
    return Fake(tmp_path)


DEV = "registry.fly.io/dots-and-dashes-dev"


def release(version: int, sha: str, status: str = "complete") -> dict[str, Any]:
    return {"Version": version, "Status": status, "ImageRef": f"{DEV}:{sha}"}


def test_a_rollback_deploys_the_image_before_the_one_the_alert_names(fly):
    fly.releases = [release(7, "bad"), release(6, "good"), release(5, "older")]

    result = fly.run("remedy", "rollback", "dev", "--from", f"{DEV}:bad")

    assert result.returncode == 0, result.stderr
    assert fly.changes() == [["deploy", "--config", "fly.dev.toml", "--image", f"{DEV}:good"]]
    assert {call["token"] for call in fly.calls()} == {SECRETS["FLY_DEV_API_TOKEN"]}
    assert f"{DEV}:good" in result.stdout


def test_a_rollback_skips_failed_releases_and_ones_of_the_same_image(fly):
    fly.releases = [
        release(9, "bad"),
        release(8, "bad"),  # a secrets change: same image
        release(7, "broken", status="failed"),
        release(6, "good"),
    ]

    result = fly.run("remedy", "rollback", "dev", "--from", f"{DEV}:bad")

    assert result.returncode == 0, result.stderr
    assert fly.changes() == [["deploy", "--config", "fly.dev.toml", "--image", f"{DEV}:good"]]


def test_a_rollback_matches_the_alerts_image_with_or_without_its_digest(fly):
    fly.releases = [release(2, "bad"), release(1, "good")]

    result = fly.run("remedy", "rollback", "dev", "--from", f"{DEV}:bad@sha256:abc123")

    assert result.returncode == 0, result.stderr
    assert fly.changes() == [["deploy", "--config", "fly.dev.toml", "--image", f"{DEV}:good"]]


def test_a_rollback_refuses_when_the_app_no_longer_runs_the_alerts_image(fly):
    """Run twice, a rollback would otherwise go back to the bad image."""
    fly.releases = [release(8, "good"), release(7, "bad"), release(6, "good")]

    result = fly.run("remedy", "rollback", "dev", "--from", f"{DEV}:bad")

    assert result.returncode != 0
    assert fly.changes() == []
    assert "nothing rolled back" in result.stderr


def test_a_prod_rollback_uses_prods_config_and_token_only(fly):
    prod = "registry.fly.io/dots-and-dashes"
    fly.releases = [
        {"Version": 4, "Status": "complete", "ImageRef": f"{prod}:bad"},
        {"Version": 3, "Status": "complete", "ImageRef": f"{prod}:good"},
    ]

    result = fly.run("remedy", "rollback", "prod", "--from", f"{prod}:bad")

    assert result.returncode == 0, result.stderr
    assert fly.calls()[0]["args"][:3] == ["releases", "-a", "dots-and-dashes"]
    assert fly.changes() == [["deploy", "--config", "fly.prod.toml", "--image", f"{prod}:good"]]
    assert {call["token"] for call in fly.calls()} == {SECRETS["FLY_PROD_API_TOKEN"]}


def test_turning_a_flag_off_sets_its_secret_off(fly):
    result = fly.run("remedy", "flag-off", "dev", "FLAG_MONTHLY_REVIEW")

    assert result.returncode == 0, result.stderr
    assert fly.changes() == [
        ["secrets", "set", "-a", "dots-and-dashes-dev", "FLAG_MONTHLY_REVIEW=off"]
    ]


@pytest.mark.parametrize("name", ["FLAG_NO_SUCH_FEATURE", "CHAOS_SAVE_ERROR_RATE", "DB_POOL_SIZE"])
def test_only_a_feature_flag_the_app_reads_can_be_turned_off(fly, name):
    result = fly.run("remedy", "flag-off", "dev", name)

    assert result.returncode != 0
    assert fly.changes() == []


def test_raising_the_pool_sets_its_size_above_the_exhausted_maximum_and_redeploys(fly):
    result = fly.run("remedy", "raise-pool", "prod", "20", "--above", "15")

    assert result.returncode == 0, result.stderr
    # Setting a secret makes a new release: Fly redeploys every Machine with it.
    assert fly.changes() == [["secrets", "set", "-a", "dots-and-dashes", "DB_POOL_SIZE=20"]]


def test_the_staged_one_connection_pool_is_raised_to_ten(fly):
    """The runbook's staged incident: DB_POOL_SIZE=1 is set on dev."""
    fly.secrets = [{"Name": "DB_POOL_SIZE", "Digest": "abc"}]

    result = fly.run("remedy", "raise-pool", "dev", "10", "--above", "1")

    assert result.returncode == 0, result.stderr
    assert fly.changes() == [["secrets", "set", "-a", "dots-and-dashes-dev", "DB_POOL_SIZE=10"]]


@pytest.mark.parametrize(
    ("size", "above"),
    [("15", "15"), ("3", "15"), ("41", "15"), ("x", "1"), ("²", "1"), ("1", "-1")],
)
def test_the_pool_is_only_ever_raised_and_kept_under_postgres_connections(fly, size, above):
    fly.secrets = [{"Name": "DB_POOL_SIZE", "Digest": "abc"}]

    result = fly.run("remedy", "raise-pool", "dev", size, "--above", above)

    assert result.returncode == 2, result.stderr
    assert "Traceback" not in result.stderr
    assert fly.changes() == []


def test_with_no_pool_size_set_the_pool_is_never_set_below_the_default_15(fly):
    """Unset, SQLAlchemy allows 15 connections, whatever --above says."""
    result = fly.run("remedy", "raise-pool", "prod", "1", "--above", "0")

    assert result.returncode == 2
    assert fly.changes() == []
    assert "15" in result.stderr


@pytest.mark.parametrize("size", ["5", "4"])
def test_a_set_pool_size_is_never_raised_to_the_default_pools_5_or_less(fly, size):
    fly.secrets = [{"Name": "DB_POOL_SIZE", "Digest": "abc"}]

    result = fly.run("remedy", "raise-pool", "dev", size, "--above", "1")

    assert result.returncode == 2
    assert fly.changes() == []


def test_the_pool_is_left_alone_when_the_secrets_listing_cant_be_read(fly):
    """A listing that isn't JSON must never read as "DB_POOL_SIZE unset"."""
    fly.secrets = "Error: not authorized"

    result = fly.run("remedy", "raise-pool", "dev", "20", "--above", "15")

    assert result.returncode == 2
    assert fly.changes() == []


@pytest.mark.parametrize(
    "args",
    [
        ["rollback", "dev", "--from", f"{DEV}:bad"],
        ["flag-off", "dev", "FLAG_MONTHLY_REVIEW"],
        ["raise-pool", "prod", "20", "--above", "15"],
    ],
)
def test_a_remedys_flyctl_holds_only_its_own_environments_deploy_token(fly, args):
    fly.releases = [release(2, "bad"), release(1, "good")]

    result = fly.run("remedy", *args)

    assert result.returncode == 0, result.stderr
    env = args[1]
    for call in fly.calls():
        assert set(call["held"]) == {"FLY_API_TOKEN"}, call
        assert call["token"] == SECRETS[f"FLY_{env.upper()}_API_TOKEN"]
    for value in SECRETS.values():
        assert value not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["scale", "dev", "count", "0"],
        ["rollback", "staging", "--from", f"{DEV}:bad"],
        ["flag-off", "dev"],
    ],
)
def test_anything_but_the_three_remedies_is_refused(fly, args):
    result = fly.run("remedy", *args)

    assert result.returncode != 0
    assert fly.calls() == []


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["releases", "dev"], ["releases", "-a", "dots-and-dashes-dev", "--image"]),
        (["status", "prod"], ["status", "-a", "dots-and-dashes"]),
        (["secrets", "dev"], ["secrets", "list", "-a", "dots-and-dashes-dev"]),
        (["logs", "prod"], ["logs", "-a", "dots-and-dashes", "--no-tail"]),
    ],
)
def test_the_agent_reads_fly_through_four_read_only_commands(fly, args, expected):
    result = fly.run("fly", *args)

    assert result.returncode == 0, result.stderr
    assert [call["args"] for call in fly.calls()] == [expected]
    token_name = f"FLY_{args[1].upper()}_API_TOKEN"
    assert {call["token"] for call in fly.calls()} == {SECRETS[token_name]}
    # No other secret reaches flyctl, whose logs the agent reads back.
    assert [call["held"] for call in fly.calls()] == [["FLY_API_TOKEN"]]


def test_run_locally_the_scripts_take_their_tokens_from_the_environment(fly):
    result = fly.run_with_tokens_in_env("fly", "status", "prod")

    assert result.returncode == 0, result.stderr
    assert [call["token"] for call in fly.calls()] == [SECRETS["FLY_PROD_API_TOKEN"]]
    assert [call["held"] for call in fly.calls()] == [["FLY_API_TOKEN"]]


@pytest.mark.parametrize(
    "args", [["deploy", "dev"], ["secrets", "dev", "set", "X=1"], ["releases", "staging"]]
)
def test_any_other_fly_command_is_refused(fly, args):
    result = fly.run("fly", *args)

    assert result.returncode != 0
    assert fly.calls() == []


# Text the agent's shell could put in an argument, standing in for a token.
ECHOED = "sk-not-really-a-key-ECHOED-1234"


@pytest.mark.parametrize(
    ("script", "args"),
    [
        ("fly", ["status", ECHOED]),
        ("fly", [ECHOED, "dev"]),
        ("remedy", ["flag-off", "dev", ECHOED]),
        ("remedy", ["raise-pool", "dev", ECHOED, "--above", "1"]),
        ("remedy", ["rollback", ECHOED, "--from", "x"]),
        ("remedy", ["rollback", "dev", "--from", ECHOED]),
        ("remedy", [f"--{ECHOED}"]),
        ("incident", ["create", "--title", "t", f"--{ECHOED}", "b"]),
        ("incident", ["view", ECHOED]),
        ("incident", ["comment", ECHOED, "--body", "b"]),
    ],
)
def test_no_script_repeats_an_argument_back_in_its_errors(fly, script, args):
    fly.releases = [release(2, "bad"), release(1, "good")]

    result = fly.run(script, *args)

    assert result.returncode != 0
    assert ECHOED not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_the_open_incidents_are_listed_through_the_wrapper(fly):
    result = fly.run("incident", "open")

    assert result.returncode == 0, result.stderr
    assert [call["args"] for call in fly.calls()] == [
        ["issue", "list", "--label", "incident", "--state", "open",
         "--json", "number,title,url,labels,createdAt"],
    ]  # fmt: skip


def test_one_issue_is_read_through_the_wrapper(fly):
    result = fly.run("incident", "view", "42")

    assert result.returncode == 0, result.stderr
    assert [call["args"] for call in fly.calls()] == [
        ["issue", "view", "42", "--json", "number,title,body,labels,comments,url"],
    ]


def test_filing_an_incident_creates_its_label_then_the_issue(fly):
    result = fly.run("incident", "create", "--title", "Save failures on dev", "--body", "## Alert")

    assert result.returncode == 0, result.stderr
    # --title=, --body=: each value one word, never read as gh's own option.
    assert [call["args"] for call in fly.calls()] == [
        [
            "label", "create", "incident", "--force",
            "--color", "B60205", "--description", "Filed by the On-call agent",
        ],
        ["issue", "create", "--title=Save failures on dev", "--body=## Alert",
         "--label=incident"],
    ]  # fmt: skip


def test_an_incident_left_to_the_human_is_labelled_ready_for_human(fly):
    result = fly.run("incident", "create", "--title", "t", "--body", "b", "--ready-for-human")

    assert result.returncode == 0, result.stderr
    assert fly.calls()[-1]["args"][-2:] == ["--label=incident", "--label=ready-for-human"]


def test_findings_on_an_open_incident_go_in_a_comment(fly):
    result = fly.run("incident", "comment", "42", "--body", "Still firing", "--ready-for-human")

    assert result.returncode == 0, result.stderr
    assert [call["args"] for call in fly.calls()] == [
        ["issue", "comment", "42", "--body=Still firing"],
        ["issue", "edit", "42", "--add-label=ready-for-human"],
    ]


@pytest.mark.parametrize("name", sorted(SECRETS))
@pytest.mark.parametrize("field", ["--title", "--body"])
def test_an_incident_holding_a_token_is_refused(fly, name, field):
    """The tokens are in files the agent can't read; this catches one that got
    out anyway, before it reaches a public issue."""
    fields = {"--title": "t", "--body": "b"}
    fields[field] = f"Evidence: {SECRETS[name]} (from the logs)"

    result = fly.run("incident", "create", *[x for kv in fields.items() for x in kv])

    assert result.returncode == 2
    assert fly.calls() == []
    assert SECRETS[name] not in result.stdout + result.stderr


def test_a_comment_holding_eight_characters_of_a_token_is_refused(fly):
    run_of_eight = SECRETS["FLY_PROD_API_TOKEN"][3:11]

    result = fly.run("incident", "comment", "42", "--body", f"saw {run_of_eight} in a span")

    assert result.returncode == 2
    assert fly.calls() == []


def test_a_token_in_the_environment_is_refused_too(fly):
    result = fly.run_with_tokens_in_env(
        "incident", "create", "--title", "t", "--body", SECRETS["GRAFANA_VIEWER_TOKEN"]
    )

    assert result.returncode == 2
    assert fly.calls() == []


@pytest.mark.parametrize(
    "shape",
    ["sk-ant-api03-abc", "FlyV1 fm2_lJPECAAA", "fm2_lJPECAAA", "ghs_16C7e42F", "glsa_abcdef"],
)
def test_an_incident_holding_a_token_shaped_string_is_refused(fly, shape):
    """Anthropic, Fly, GitHub and Grafana tokens this script can't see itself."""
    result = fly.run("incident", "create", "--title", "t", "--body", f"found {shape} in a log")

    assert result.returncode == 2
    assert fly.calls() == []


@pytest.mark.parametrize(
    "args",
    [
        ["create", "--title", "t", "--body-file", "/proc/self/environ"],
        ["create", "--title", "t", "-F", "/proc/self/environ"],
        ["create", "--title", "t", "--body", "b", "--repo", "someone/else"],
        ["create", "--title", "t", "--body", "b", "-R", "someone/else"],
        ["create", "--title", "t", "--body", "b", "--label", "deploy"],
        ["create", "--title", "t", "--bod", "b"],
        ["create", "--title", "t"],
        ["comment", "42", "--body-file", "/proc/self/environ"],
        ["comment", "42; rm -rf /", "--body", "b"],
        ["comment", "42", "--body", "b", "--repo", "someone/else"],
        ["view", "42", "--repo", "someone/else"],
        ["open", "--search", "anything"],
        ["close", "42"],
    ],
)
def test_the_incident_wrapper_takes_no_file_repo_or_other_command(fly, args):
    result = fly.run("incident", *args)

    assert result.returncode == 2
    assert fly.calls() == []


@pytest.mark.parametrize(
    "args",
    [
        ["create", "--title", "t", "--body", "b"],
        ["comment", "42", "--body", "b", "--ready-for-human"],
        ["open"],
        ["view", "42"],
    ],
)
def test_the_incident_wrappers_gh_holds_the_github_token_and_no_other_secret(fly, args):
    result = fly.run("incident", *args)

    assert result.returncode == 0, result.stderr
    assert [call["held"] for call in fly.calls()] == [["GH_TOKEN"]] * len(fly.calls())


class Grafana:
    """A local stand-in for Grafana's HTTP API, recording each request."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str | None]] = []
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                requests.append((self.command, self.path, self.headers.get("Authorization")))
                body = json.dumps({"path": self.path}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _answer

            def log_message(self, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def grafana() -> Iterator[Grafana]:
    server = Grafana()
    yield server
    server.server.shutdown()


def run_grafana(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    environ = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GRAFANA_") and k not in SECRET_NAMES
    }
    environ["ENV_FILE"] = os.devnull
    return subprocess.run(
        [str(SCRIPTS / "grafana"), *args],
        env={**environ, **env},
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_the_agent_reads_grafana_with_the_viewer_token(grafana):
    env = {"GRAFANA_URL": grafana.url, "GRAFANA_VIEWER_TOKEN": "viewer-token"}

    result = run_grafana(env, "api/prometheus/grafana/api/v1/rules?type=alert")

    assert result.returncode == 0, result.stderr
    assert grafana.requests == [
        ("GET", "/api/prometheus/grafana/api/v1/rules?type=alert", "Bearer viewer-token")
    ]
    assert json.loads(result.stdout) == {"path": "/api/prometheus/grafana/api/v1/rules?type=alert"}


def test_in_the_workflow_grafana_reads_the_viewer_token_from_its_file(grafana, tmp_path):
    (tmp_path / "GRAFANA_VIEWER_TOKEN").write_text("token-from-its-file\n")
    env = {"GRAFANA_URL": grafana.url, "ON_CALL_TOKENS": str(tmp_path)}

    result = run_grafana(env, "api/folders")

    assert result.returncode == 0, result.stderr
    assert grafana.requests == [("GET", "/api/folders", "Bearer token-from-its-file")]


def test_a_refused_path_isnt_repeated_back(grafana):
    env = {"GRAFANA_URL": grafana.url, "GRAFANA_VIEWER_TOKEN": "viewer-token"}

    result = run_grafana(env, f"https://example.com/{ECHOED}")

    assert result.returncode == 2
    assert ECHOED not in result.stdout + result.stderr


def test_a_token_in_grafanas_answer_is_redacted(grafana, tmp_path):
    """Grafana's answer echoes the path asked for; were a token in it, the
    run log would show it."""
    (tmp_path / "FLY_PROD_API_TOKEN").write_text(SECRETS["FLY_PROD_API_TOKEN"])
    env = {"GRAFANA_URL": grafana.url, "GRAFANA_VIEWER_TOKEN": "v", "ON_CALL_TOKENS": str(tmp_path)}

    result = run_grafana(env, f"api/search?query={SECRETS['FLY_PROD_API_TOKEN']}")

    assert result.returncode == 0, result.stderr
    assert SECRETS["FLY_PROD_API_TOKEN"] not in result.stdout
    assert "[redacted]" in result.stdout


def test_a_local_agent_reads_the_url_and_viewer_token_from_the_env_file(grafana, tmp_path):
    """The wizard writes both there, single-quoted, for agents in the sandbox."""
    env_file = tmp_path / ".env"
    env_file.write_text(f"OTHER=1\nGRAFANA_URL='{grafana.url}'\nGRAFANA_VIEWER_TOKEN='from-file'\n")

    result = run_grafana({"ENV_FILE": str(env_file)}, "api/folders")

    assert result.returncode == 0, result.stderr
    assert grafana.requests == [("GET", "/api/folders", "Bearer from-file")]


@pytest.mark.parametrize(
    "path", ["https://example.com/api/folders", "//example.com/api", "/api/folders", "api/../x"]
)
def test_grafana_is_read_only_at_its_own_url(grafana, path):
    env = {"GRAFANA_URL": grafana.url, "GRAFANA_VIEWER_TOKEN": "viewer-token"}

    result = run_grafana(env, path)

    assert result.returncode != 0
    assert grafana.requests == []


def test_grafana_takes_no_method_or_body(grafana):
    env = {"GRAFANA_URL": grafana.url, "GRAFANA_VIEWER_TOKEN": "viewer-token"}

    result = run_grafana(env, "api/folders", "-X", "POST")

    assert result.returncode != 0
    assert grafana.requests == []


def test_grafana_unreachable_fails_without_a_traceback_or_the_token(grafana):
    grafana.server.shutdown()
    grafana.server.server_close()
    env = {"GRAFANA_URL": grafana.url, "GRAFANA_VIEWER_TOKEN": "viewer-token"}

    result = run_grafana(env, "api/folders")

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "viewer-token" not in result.stdout + result.stderr


def alert(name: str, status: str = "firing") -> dict[str, Any]:
    """One alert as monitoring/on-call-payload.tmpl puts it in the client_payload."""
    return {
        "status": status,
        "labels": {"alertname": name, "env": "dev", "grafana_folder": "Dots & Dashes"},
        "annotations": {"image": f"{DEV}:bad", "runbook_url": "https://example.com/runbook"},
        "startsAt": "2026-10-26T12:00:00Z",
    }


def notification(status: str, *alerts: dict[str, Any]) -> dict[str, Any]:
    """The repository_dispatch event GitHub hands the On-call workflow."""
    return {
        "action": "grafana-alert",
        "client_payload": {"status": status, "alerts": list(alerts), "commonLabels": {}},
    }


def prepare(tmp_path: Path, event: dict[str, Any]) -> tuple[dict[str, str], Path]:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    out = tmp_path / "out"
    output = tmp_path / "github_output"
    output.touch()
    result = subprocess.run(
        [str(SCRIPTS / "prepare"), str(event_path), str(out)],
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return outputs, out


def test_a_firing_alert_wakes_the_agent_with_the_notification_in_its_prompt(tmp_path):
    outputs, out = prepare(tmp_path, notification("firing", alert("Save failures (dev)")))

    assert outputs == {"kind": "firing", "wake": "true"}
    prompt = (out / "prompt.md").read_text()
    assert '"alertname": "Save failures (dev)"' in prompt
    assert f'"image": "{DEV}:bad"' in prompt


def test_grafanas_test_notification_starts_a_run_but_wakes_no_agent(tmp_path):
    """The contact point's Test button sends a TestAlert: it proves the bridge
    without an incident issue."""
    outputs, _ = prepare(tmp_path, notification("firing", alert("TestAlert")))

    assert outputs == {"kind": "test", "wake": "false"}


def test_a_resolved_notification_wakes_no_agent(tmp_path):
    outputs, _ = prepare(
        tmp_path, notification("resolved", alert("Save failures (dev)", status="resolved"))
    )

    assert outputs == {"kind": "resolved", "wake": "false"}


AGENT = SCRIPTS / "agent.md"


def test_the_agent_runs_as_the_on_call_agent_definition(tmp_path):
    """agents.json is built from scripts/on-call/agent.md, a file Builders can
    write (the sandbox masks .claude/ in worktrees)."""
    _, out = prepare(tmp_path, notification("firing", alert("Save latency (dev)")))

    _, _, body = AGENT.read_text().split("---\n", 2)
    assert json.loads((out / "agents.json").read_text()) == {
        "on-call": {
            "description": (
                "Responds to a production alert, diagnoses it from telemetry, applies one"
                " of three fixed remedies, and files an incident issue. Use when a Grafana"
                " alert fires."
            ),
            "prompt": body.strip(),
            "model": "opus",
            "tools": ["Read", "Grep", "Glob", "Bash"],
        }
    }
    assert body.strip().startswith("You are the On-call agent.")


WORKFLOWS = ROOT / ".github" / "workflows"


def workflow(name: str) -> dict[Any, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def triggers(flow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the key `on` as True.
    return flow[True]


def on_call_step(name: str) -> dict[str, Any]:
    (job,) = workflow("on-call.yml")["jobs"].values()
    (step,) = [s for s in job["steps"] if s.get("name") == name]
    return step


AGENT_STEP = "Run the On-call agent"


def test_a_grafana_alert_dispatch_is_the_on_call_workflows_only_trigger():
    payload = (ROOT / "monitoring" / "on-call-payload.tmpl").read_text()

    dispatch = {"repository_dispatch": {"types": ["grafana-alert"]}}
    assert triggers(workflow("on-call.yml")) == dispatch
    assert '"event_type" "grafana-alert"' in payload
    assert '"client_payload"' in payload


def test_the_workflow_token_can_read_the_code_and_write_issues_only():
    flow = workflow("on-call.yml")

    assert flow["permissions"] == {"contents": "read", "issues": "write"}
    assert all("permissions" not in job for job in flow["jobs"].values())


ALLOWED_TOOLS = [
    "Read(./**)",
    "Grep(./**)",
    "Glob(./**)",
    "Bash(scripts/on-call/grafana *)",
    "Bash(scripts/on-call/fly *)",
    "Bash(scripts/on-call/remedy *)",
    "Bash(scripts/on-call/incident *)",
    # Waiting between checks that the alert's signal recovered.
    "Bash(sleep *)",
]

# Read rules apply to Grep and Glob too, and a deny beats any allow. These keep
# the agent off the process environment (/proc/<pid>/environ holds the tokens)
# and the system and temp dirs outside the checkout. Not ~/**: the checkout is
# under it.
DENIED_TOOLS = [
    "Read(//proc/**)",
    "Read(//sys/**)",
    "Read(//dev/**)",
    "Read(//etc/**)",
    "Read(//tmp/**)",
    "Read(//root/**)",
]

# A fake claude on PATH: records its arguments.
FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "w") as log:
    json.dump(sys.argv[1:], log)
"""


def allowed_tools() -> list[str]:
    return on_call_step(AGENT_STEP)["env"]["ON_CALL_TOOLS"].strip().splitlines()


def run_agent_step(tmp_path: Path, runner_temp: Path) -> list[str]:
    """Run the agent step's script as the runner does, against a fake claude,
    and return the arguments claude got."""
    step = on_call_step(AGENT_STEP)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text(FAKE_CLAUDE.replace("python3", sys.executable.replace("\\", "/"), 1))
    claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
    (runner_temp / "on-call").mkdir(parents=True)
    (runner_temp / "on-call" / "prompt.md").write_text("prompt\n")
    log = tmp_path / "claude.json"
    env = {k: v for k, v in step["env"].items() if "${{" not in v}
    env |= {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_LOG": str(log),
        "RUNNER_TEMP": str(runner_temp),
        "ON_CALL_TOKENS": str(runner_temp / "on-call-tokens"),
        "GRAFANA_URL": "https://grafana.invalid",
    }
    # GitHub runs a `shell: bash` step as `bash --noprofile --norc -eo pipefail`.
    subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
        env=env,
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return json.loads(log.read_text())


def option(args: list[str], name: str) -> list[str]:
    """A comma-separated option's entries, as claude splits them."""
    return [entry for entry in args[args.index(name) + 1].split(",") if entry]


def test_the_agent_may_read_telemetry_apply_a_remedy_and_file_an_issue_and_nothing_else(
    tmp_path,
):
    step = on_call_step(AGENT_STEP)
    run = step["run"]
    runner_temp = tmp_path / "runner" / "_temp"

    args = run_agent_step(tmp_path, runner_temp)

    assert allowed_tools() == ALLOWED_TOOLS
    assert option(args, "--allowedTools") == ALLOWED_TOOLS
    # The runner's own temp dir (the token files, the prompt, the transcript)
    # is denied wherever RUNNER_TEMP puts it.
    assert option(args, "--disallowedTools") == [*DENIED_TOOLS, f"Read(/{runner_temp}/**)"]
    assert "/home/runner" not in step["env"]["ON_CALL_DENIED"]
    # The built-in tools it has at all: no Write, Edit, WebFetch or subagents.
    assert "--tools Read,Grep,Glob,Bash" in run
    # Anything not allowed above is refused, never asked about.
    assert "--permission-mode dontAsk" in run
    # The repo's own settings (allow rules, hooks) and MCP servers don't apply.
    assert "--setting-sources user" in run
    assert "--strict-mcp-config" in run
    assert "--bare" in run


def test_no_file_tool_reaches_outside_the_checkout():
    """A bare Read, Grep or Glob would reach /proc/self/environ and its tokens."""
    for tool in allowed_tools():
        name, _, scope = tool.partition("(")
        if name in {"Read", "Grep", "Glob"}:
            assert scope == "./**)", tool


def test_no_gh_command_can_post_a_file_or_reach_another_repo():
    """Only scripts/on-call/incident reaches issues, with text arguments only:
    the agent may run no raw gh at all."""
    for tool in allowed_tools():
        assert "gh " not in tool, tool
        assert "create" not in tool and "comment" not in tool and "label" not in tool, tool


AGENT_TOKENS = {
    "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
    "GRAFANA_VIEWER_TOKEN": "${{ secrets.GRAFANA_VIEWER_TOKEN }}",
    "FLY_DEV_API_TOKEN": "${{ secrets.FLY_API_TOKEN }}",
    "FLY_PROD_API_TOKEN": "${{ secrets.FLY_PROD_API_TOKEN }}",
    "GH_TOKEN": "${{ github.token }}",
}
TOKEN_STEP = "Keep the tokens in files only the scripts read"


def test_no_token_is_in_the_agents_environment():
    """The agent's shell could expand any variable in its environment into an
    argument: no token is ever there."""
    env = on_call_step(AGENT_STEP)["env"]

    assert set(env) == {"GRAFANA_URL", "ON_CALL_TOKENS", "ON_CALL_TOOLS", "ON_CALL_DENIED"}
    assert not any("secrets." in value or "github.token" in value for value in env.values())
    assert env["ON_CALL_TOKENS"] == "${{ runner.temp }}/on-call-tokens"


def test_an_earlier_step_writes_each_token_to_a_file_only_its_owner_reads(tmp_path):
    step = on_call_step(TOKEN_STEP)
    runner_temp = tmp_path / "runner" / "_temp"

    assert step["env"] == AGENT_TOKENS
    assert step["run"].startswith("umask 077\n")
    assert 'printf \'%s\' "${!name}" > "$RUNNER_TEMP/on-call-tokens/$name"' in step["run"]
    for name in AGENT_TOKENS:
        assert name in step["run"]
    # The token files sit in the runner's temp dir, which the file tools are denied.
    denied = option(run_agent_step(tmp_path, runner_temp), "--disallowedTools")
    assert f"Read(/{runner_temp}/**)" in denied


def test_claude_code_reads_its_api_key_through_a_helper_not_the_environment():
    run = on_call_step(AGENT_STEP)["run"]

    assert (
        'api_key_helper=$(printf \'{"apiKeyHelper": "cat %s/ANTHROPIC_API_KEY"}\' '
        '"$ON_CALL_TOKENS")'
    ) in run
    assert '--settings "$api_key_helper"' in run


def test_the_token_files_are_removed_however_the_run_ends():
    step = on_call_step("Remove the token files")

    assert step["if"] == "always()"
    assert step["run"] == 'rm -rf "$RUNNER_TEMP/on-call-tokens"'


def test_the_checkout_keeps_no_github_token_in_git_config():
    (job,) = workflow("on-call.yml")["jobs"].values()
    (checkout,) = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout")]

    assert checkout["with"]["persist-credentials"] is False


def test_the_agent_runs_with_the_on_call_definition_only_for_a_firing_alert():
    step = on_call_step(AGENT_STEP)

    assert step["if"] == "steps.notification.outputs.wake == 'true'"
    assert '--agents "$RUNNER_TEMP/on-call/agents.json" --agent on-call' in step["run"]
    assert '< "$RUNNER_TEMP/on-call/prompt.md"' in step["run"]
    assert on_call_step("Read the notification")["run"] == (
        'scripts/on-call/prepare "$GITHUB_EVENT_PATH" "$RUNNER_TEMP/on-call"'
    )


def test_the_agent_gets_the_grafana_url_and_its_tokens_through_files():
    env = on_call_step(AGENT_STEP)["env"]

    assert env["GRAFANA_URL"] == "${{ vars.GRAFANA_URL }}"
    assert on_call_step(TOKEN_STEP)["env"] == AGENT_TOKENS


def test_the_workflow_reads_no_secret_but_the_documented_ones():
    text = (WORKFLOWS / "on-call.yml").read_text()
    runbook = RUNBOOK.read_text()

    secrets = set(re.findall(r"secrets\.([A-Z_]+)", text))
    assert secrets == {
        "ANTHROPIC_API_KEY",
        "GRAFANA_VIEWER_TOKEN",
        "FLY_API_TOKEN",
        "FLY_PROD_API_TOKEN",
    }
    for name in [*secrets, "GRAFANA_URL", "dots-and-dashes-on-call-dispatch"]:
        assert f"`{name}`" in runbook


def test_dev_can_be_deployed_from_a_branch_to_stage_a_bad_deploy():
    flow = workflow("deploy-dev.yml")
    (job,) = flow["jobs"].values()
    (checkout,) = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout")]

    assert "ref" in triggers(flow)["workflow_dispatch"]["inputs"]
    assert checkout["with"]["ref"] == "${{ inputs.ref || github.sha }}"
    # The image is tagged with the commit it was built from, not main's.
    assert "SHA" not in job.get("env", {})
    assert any('echo "SHA=$(git rev-parse HEAD)"' in s.get("run", "") for s in job["steps"])


def test_the_runbook_says_how_to_stage_each_scenario_and_what_the_agent_runs():
    runbook = RUNBOOK.read_text()

    assert "gh workflow run deploy-dev.yml -f ref=" in runbook
    assert "scripts/on-call/remedy rollback dev --from" in runbook
    assert "CHAOS_SAVE_ERROR_FLAG=FLAG_MONTHLY_REVIEW" in runbook
    assert "scripts/on-call/remedy flag-off" in runbook
    assert "scripts/on-call/remedy raise-pool" in runbook
