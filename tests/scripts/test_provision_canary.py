"""scripts/provision-canary stops before its first prompt when it can't save to .env.

The wizard asks for passwords and calls Fly and Grafana, so these tests load its
functions without running it (every line but the last, `run_wizard "$@"; exit`)
and call env_preflight alone, from a directory standing in for the checkout.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIZARD = ROOT / "scripts" / "provision-canary"
LAST_LINE = 'run_wizard "$@"; exit'


def env_preflight(checkout: Path) -> subprocess.CompletedProcess[str]:
    lines = WIZARD.read_text().splitlines()
    assert lines[-1] == LAST_LINE, "the wizard's last line runs it; keep it the only one that does"
    functions = "\n".join(lines[:-1])
    return subprocess.run(
        ["bash", "-c", f'{functions}\nenv_preflight\necho "passed the pre-flight"'],
        cwd=checkout,
        capture_output=True,
        text=True,
    )


def test_a_read_only_env_file_stops_the_wizard_up_front(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("")
    env.chmod(0o444)

    result = env_preflight(tmp_path)

    assert result.returncode == 1
    assert ".env isn't writable" in result.stdout
    assert "chmod 600 .env" in result.stdout
    assert "passed the pre-flight" not in result.stdout
    assert env.read_text() == ""
    assert env.stat().st_mode & 0o777 == 0o444


def test_a_writable_env_file_passes(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("GRAFANA_URL='https://example.grafana.net'\n")
    env.chmod(0o600)

    result = env_preflight(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "passed the pre-flight"
