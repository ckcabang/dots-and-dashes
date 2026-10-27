"""scripts/provision-oncall stops before its first prompt when it can't save to .env.

Like test_provision_canary.py: the wizard asks for tokens and calls GitHub,
Fly and Grafana, so these load its functions without running it (every line
but the last, `run_wizard "$@"; exit`) and call one alone.
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIZARD = ROOT / "scripts" / "provision-oncall"
LAST_LINE = 'run_wizard "$@"; exit'


def run_function(checkout: Path, script: str) -> subprocess.CompletedProcess[str]:
    lines = WIZARD.read_text().splitlines()
    assert lines[-1] == LAST_LINE, "the wizard's last line runs it; keep it the only one that does"
    functions = "\n".join(lines[:-1])
    return subprocess.run(
        ["bash", "-c", f"{functions}\n{script}"],
        cwd=checkout,
        capture_output=True,
        text=True,
    )


def test_a_read_only_env_file_stops_the_wizard_up_front(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("")
    env.chmod(0o444)

    result = run_function(tmp_path, 'env_preflight\necho "passed the pre-flight"')

    assert result.returncode == 1
    assert ".env isn't writable" in result.stdout
    assert "chmod 600 .env" in result.stdout
    assert "passed the pre-flight" not in result.stdout
    assert env.read_text() == ""


def test_a_writable_env_file_passes(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("GRAFANA_URL='https://example.grafana.net'\n")
    env.chmod(0o600)

    result = run_function(tmp_path, 'env_preflight\necho "passed the pre-flight"')

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "passed the pre-flight"


def test_the_contact_point_carries_the_dispatch_url_token_and_the_repos_payload(
    tmp_path: Path,
) -> None:
    """The token comes from the environment, never the command line, and the
    payload is monitoring/on-call-payload.tmpl as it is in the repo."""
    (tmp_path / "monitoring").mkdir()
    template = (ROOT / "monitoring" / "on-call-payload.tmpl").read_text()
    (tmp_path / "monitoring" / "on-call-payload.tmpl").write_text(template)

    result = run_function(tmp_path, 'DISPATCH_TOKEN=github_pat_x contact_point_json "abc"')

    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["name"] == "dots-and-dashes-on-call"
    assert body["uid"] == "abc"
    assert body["type"] == "webhook"
    assert body["settings"] == {
        "url": "https://api.github.com/repos/ckcabang/dots-and-dashes/dispatches",
        "httpMethod": "POST",
        "authorization_scheme": "Bearer",
        "authorization_credentials": "github_pat_x",
        "payload": {"template": template},
    }
