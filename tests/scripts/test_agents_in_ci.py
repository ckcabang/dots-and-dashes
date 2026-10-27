"""No step that runs an agent in CI holds a secret in its environment
("Agents in CI" in CODING_STANDARDS.md).

The agent's shell could expand any variable in its environment into an
argument, so a token reaches it only through a file a wrapper script reads.
Not a seam (docs/architecture/README.md): a build check over every workflow in
.github/workflows/, like tests/unit/test_templates.py.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

# `claude` as a command: not `@anthropic-ai/claude-code` or a path under .claude/.
RUNS_CLAUDE = re.compile(r"(?:^|[\s;&|(`])claude(?:\s|$)", re.MULTILINE)
# What a step's environment can take a secret from.
SECRET = re.compile(r"\$\{\{[^}]*\b(?:secrets\.|github\.token\b)")


def steps_running_claude_with_a_secret(path: Path) -> list[str]:
    """Each step whose run: invokes claude while a secret is in its environment:
    the workflow's env:, its job's or its own."""
    flow: dict[str, Any] = yaml.safe_load(path.read_text())
    found = []
    for job_id, job in flow.get("jobs", {}).items():
        for index, step in enumerate(job.get("steps", [])):
            if not RUNS_CLAUDE.search(step.get("run", "")):
                continue
            env = {**flow.get("env", {}), **job.get("env", {}), **step.get("env", {})}
            if any(SECRET.search(str(value)) for value in env.values()):
                found.append(f"{path.name}: {job_id}: {step.get('name', index)}")
    return found


def steps_running_claude(path: Path) -> list[str]:
    flow: dict[str, Any] = yaml.safe_load(path.read_text())
    return [
        step.get("name", "")
        for job in flow.get("jobs", {}).values()
        for step in job.get("steps", [])
        if RUNS_CLAUDE.search(step.get("run", ""))
    ]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_no_step_that_runs_claude_holds_a_secret(path: Path) -> None:
    assert steps_running_claude_with_a_secret(path) == []


def test_the_check_finds_the_on_call_agents_step() -> None:
    """The check above would pass vacuously if it missed how claude is run."""
    on_call = ROOT / ".github" / "workflows" / "on-call.yml"

    assert steps_running_claude(on_call) == ["Run the On-call agent"]


AGENT_RUN = 'claude --print --bare --agent on-call < "$RUNNER_TEMP/prompt.md"'


def fixture_workflow(tmp_path: Path, flow: dict[str, Any]) -> Path:
    path = tmp_path / "agent.yml"
    path.write_text(yaml.safe_dump(flow))
    return path


@pytest.mark.parametrize(
    "secret",
    ["${{ secrets.ANTHROPIC_API_KEY }}", "${{ github.token }}", "Bearer ${{secrets.GH_PAT}}"],
)
def test_a_step_running_claude_with_a_secret_in_its_env_is_found(
    tmp_path: Path, secret: str
) -> None:
    step = {"name": "Run the agent", "env": {"TOKEN": secret}, "run": AGENT_RUN}
    path = fixture_workflow(tmp_path, {"jobs": {"respond": {"steps": [step]}}})

    assert steps_running_claude_with_a_secret(path) == ["agent.yml: respond: Run the agent"]


@pytest.mark.parametrize("level", ["workflow", "job"])
def test_a_secret_a_claude_step_inherits_is_found(tmp_path: Path, level: str) -> None:
    env = {"ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}"}
    job: dict[str, Any] = {"steps": [{"name": "Run the agent", "run": f"set -e\n{AGENT_RUN}"}]}
    flow: dict[str, Any] = {"jobs": {"respond": job}}
    (flow if level == "workflow" else job)["env"] = env
    path = fixture_workflow(tmp_path, flow)

    assert steps_running_claude_with_a_secret(path) == ["agent.yml: respond: Run the agent"]


def test_a_secret_in_a_step_that_doesnt_run_claude_is_allowed(tmp_path: Path) -> None:
    steps = [
        {
            "name": "Keep the tokens in files",
            "env": {"ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}"},
            "run": 'printf %s "$ANTHROPIC_API_KEY" > "$RUNNER_TEMP/key"',
        },
        {"name": "Install", "run": "npm install -g @anthropic-ai/claude-code@2.1.311"},
        {"name": "Run the agent", "env": {"URL": "${{ vars.GRAFANA_URL }}"}, "run": AGENT_RUN},
    ]
    path = fixture_workflow(tmp_path, {"jobs": {"respond": {"steps": steps}}})

    assert steps_running_claude_with_a_secret(path) == []
