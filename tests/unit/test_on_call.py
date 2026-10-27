"""The On-call agent's tools in scripts/on-call/ and its workflow do only what
ADR-0002 allows: read telemetry and the Fly release history, and apply one of
three remedies.

A build check like test_monitoring.py, not a seam: the scripts run in GitHub
Actions against Fly and Grafana, so these run them against a fake `flyctl`
and a local HTTP server instead.
"""

import json
import os
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "on-call"

FAKE_FLYCTL = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_FLY_LOG"], "a") as log:
    log.write(json.dumps({"args": sys.argv[1:], "token": os.environ.get("FLY_API_TOKEN")}) + "\\n")
if sys.argv[1:2] == ["releases"]:
    print(os.environ.get("FAKE_FLY_RELEASES", "[]"))
"""


class Fly:
    """A fake flyctl on PATH that records each call and serves a release history."""

    def __init__(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        flyctl = bin_dir / "flyctl"
        flyctl.write_text(FAKE_FLYCTL.replace("python3", sys.executable.replace("\\", "/"), 1))
        flyctl.chmod(flyctl.stat().st_mode | stat.S_IEXEC)
        self.log = tmp_path / "fly.log"
        self.log.touch()
        self.releases: list[dict[str, Any]] = []
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_FLY_LOG": str(self.log),
            "FLY_DEV_API_TOKEN": "dev-token",
            "FLY_PROD_API_TOKEN": "prod-token",
        }

    def run(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, **self.env, "FAKE_FLY_RELEASES": json.dumps(self.releases)}
        env.pop("FLY_API_TOKEN", None)
        return subprocess.run(
            [str(SCRIPTS / script), *args], env=env, capture_output=True, text=True, cwd=ROOT
        )

    def calls(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def changes(self) -> list[list[str]]:
        """The calls that change an app: everything but reading its releases."""
        return [call["args"] for call in self.calls() if call["args"][0] != "releases"]


@pytest.fixture
def fly(tmp_path: Path) -> Fly:
    return Fly(tmp_path)


DEV = "registry.fly.io/dots-and-dashes-dev"


def release(version: int, sha: str, status: str = "complete") -> dict[str, Any]:
    return {"Version": version, "Status": status, "ImageRef": f"{DEV}:{sha}"}


def test_a_rollback_deploys_the_image_before_the_one_the_alert_names(fly):
    fly.releases = [release(7, "bad"), release(6, "good"), release(5, "older")]

    result = fly.run("remedy", "rollback", "dev", "--from", f"{DEV}:bad")

    assert result.returncode == 0, result.stderr
    assert fly.changes() == [["deploy", "--config", "fly.dev.toml", "--image", f"{DEV}:good"]]
    assert {call["token"] for call in fly.calls()} == {"dev-token"}
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
    assert {call["token"] for call in fly.calls()} == {"prod-token"}


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


@pytest.mark.parametrize(("size", "above"), [("15", "15"), ("3", "15"), ("41", "15"), ("x", "1")])
def test_the_pool_is_only_ever_raised_and_kept_under_postgres_connections(fly, size, above):
    result = fly.run("remedy", "raise-pool", "dev", size, "--above", above)

    assert result.returncode != 0
    assert fly.changes() == []


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
    assert {call["token"] for call in fly.calls()} == {f"{args[1]}-token"}


@pytest.mark.parametrize(
    "args", [["deploy", "dev"], ["secrets", "dev", "set", "X=1"], ["releases", "staging"]]
)
def test_any_other_fly_command_is_refused(fly, args):
    result = fly.run("fly", *args)

    assert result.returncode != 0
    assert fly.calls() == []


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
    environ = {k: v for k, v in os.environ.items() if not k.startswith("GRAFANA_")}
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
