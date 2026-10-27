"""No step that runs an agent in CI is handed a secret ("Agents in CI" in
CODING_STANDARDS.md): not in its environment, not written into its script, not
as an action's input.

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

# `claude` as a command word, however it's started: bare, by path, quoted for
# `bash -c`, in `$(...)`. Not `claude-code` (a package) or `.claude/` (a path).
RUNS_CLAUDE = re.compile(r"""(?:^|[\s;&|(`'"/])claude(?=$|[\s;&|)`'"])""", re.MULTILINE)
# The package run straight from the registry, as npx and its kin do.
RUNS_CLAUDE_PACKAGE = re.compile(
    r"\b(?:npx|bunx|pnpm\s+dlx|yarn\s+dlx|npm\s+exec)\b[^\n]*@anthropic-ai/claude-code\b"
)
# A Claude Code action, such as anthropics/claude-code-action.
CLAUDE_ACTION = re.compile(r"claude", re.IGNORECASE)
# Each `${{ ... }}` expression, up to its closing `}}` (an expression may hold `}`).
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
# The secrets context in any form (secrets.X, secrets['X'], toJSON(secrets)),
# and the run's GitHub token.
SECRET_CONTEXT = re.compile(r"""\bsecrets\b|\bgithub\s*(?:\.\s*token\b|\[\s*['"]token['"]\s*\])""")


def holds_a_secret(value: object) -> bool:
    """Whether workflow text hands over a secret: Actions substitutes every
    expression before the step sees it, in env:, with: and run: alike."""
    return any(SECRET_CONTEXT.search(expression) for expression in EXPRESSION.findall(str(value)))


def runs_claude(step: dict[str, Any]) -> bool:
    run = str(step.get("run", ""))
    return bool(
        RUNS_CLAUDE.search(run)
        or RUNS_CLAUDE_PACKAGE.search(run)
        or CLAUDE_ACTION.search(str(step.get("uses", "")))
    )


def steps_running_claude_with_a_secret(path: Path) -> list[str]:
    """Each step that runs claude and is handed a secret: in the workflow's,
    its job's or its own env:, in its run: script, or in an action's with:."""
    flow: dict[str, Any] = yaml.safe_load(path.read_text())
    found = []
    for job_id, job in flow.get("jobs", {}).items():
        for index, step in enumerate(job.get("steps", [])):
            if not runs_claude(step):
                continue
            env = {**flow.get("env", {}), **job.get("env", {}), **step.get("env", {})}
            handed = [*env.values(), step.get("run", ""), *step.get("with", {}).values()]
            if any(holds_a_secret(value) for value in handed):
                found.append(f"{path.name}: {job_id}: {step.get('name', index)}")
    return found


def steps_running_claude(path: Path) -> list[str]:
    flow: dict[str, Any] = yaml.safe_load(path.read_text())
    return [
        step.get("name", "")
        for job in flow.get("jobs", {}).values()
        for step in job.get("steps", [])
        if runs_claude(step)
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


SECRET_KEY = {"ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}"}


@pytest.mark.parametrize(
    "secret",
    [
        "${{ secrets['ANTHROPIC_API_KEY'] }}",
        "${{ toJSON(secrets) }}",
        "${{ format('{0}', secrets.ANTHROPIC_API_KEY) }}",
        "${{ github['token'] }}",
    ],
)
def test_a_secret_in_any_expression_shape_is_found(tmp_path: Path, secret: str) -> None:
    step = {"name": "Run the agent", "env": {"TOKEN": secret}, "run": AGENT_RUN}
    path = fixture_workflow(tmp_path, {"jobs": {"respond": {"steps": [step]}}})

    assert steps_running_claude_with_a_secret(path) == ["agent.yml: respond: Run the agent"]


def test_a_secret_written_into_the_script_that_runs_claude_is_found(tmp_path: Path) -> None:
    # Actions substitutes the expression before bash runs, so claude holds the key.
    run = 'ANTHROPIC_API_KEY="${{ secrets.ANTHROPIC_API_KEY }}" claude --print < prompt.md'
    step = {"name": "Run the agent", "run": run}
    path = fixture_workflow(tmp_path, {"jobs": {"respond": {"steps": [step]}}})

    assert steps_running_claude_with_a_secret(path) == ["agent.yml: respond: Run the agent"]


@pytest.mark.parametrize(
    "run",
    [
        "/usr/local/bin/claude --print < prompt.md",
        'bash -c "claude --print < prompt.md"',
        "bash -c 'claude --print'",
        "npx @anthropic-ai/claude-code --print < prompt.md",
        "npx -y @anthropic-ai/claude-code@2.1.311 --print",
        "out=$(claude --print)",
    ],
)
def test_claude_started_any_way_is_found(tmp_path: Path, run: str) -> None:
    step = {"name": "Run the agent", "env": SECRET_KEY, "run": run}
    path = fixture_workflow(tmp_path, {"jobs": {"respond": {"steps": [step]}}})

    assert steps_running_claude_with_a_secret(path) == ["agent.yml: respond: Run the agent"]


@pytest.mark.parametrize("field", ["with", "env"])
def test_a_claude_code_action_given_a_secret_is_found(tmp_path: Path, field: str) -> None:
    key = (
        {"anthropic_api_key": "${{ secrets.ANTHROPIC_API_KEY }}"} if field == "with" else SECRET_KEY
    )
    step = {"name": "Run the agent", "uses": "anthropics/claude-code-action@v1", field: key}
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
        {
            "name": "Install",
            "env": SECRET_KEY,
            "run": "npm install -g @anthropic-ai/claude-code@2.1.311",
        },
        {
            "name": "Read the agent's definition",
            "env": SECRET_KEY,
            "run": "cat .claude/agents/on-call.md scripts/claude.json",
        },
        {"name": "Run the agent", "env": {"URL": "${{ vars.GRAFANA_URL }}"}, "run": AGENT_RUN},
        {
            "name": "Check out",
            "uses": "actions/checkout@v7",
            "with": {"token": "${{ github.token }}"},
        },
    ]
    path = fixture_workflow(tmp_path, {"jobs": {"respond": {"steps": steps}}})

    assert steps_running_claude_with_a_secret(path) == []
