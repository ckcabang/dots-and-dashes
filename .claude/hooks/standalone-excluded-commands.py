#!/usr/bin/env python3
"""PreToolUse hook (Bash): run the sandbox-excluded commands on their own.

Only the bare forms in .claude/settings.json's sandbox.excludedCommands run
outside the sandbox. Piped, chained, redirected or env-prefixed, they run
sandboxed, can't reach Docker, and fail with a misleading error
("open .env: permission denied"). This blocks those forms up front.

Only a command in command position counts: text that mentions one, in quotes
or a heredoc, is left alone.
"""

import json
import re
import shlex
import sys

# Keep in step with sandbox.excludedCommands in .claude/settings.json.
MAKE_TARGETS = {"test", "check", "test-logs", "test-down", "test-integration", "test-browser"}
COMPOSE_SUBCOMMANDS = {"up", "down", "ps", "logs", "build", "stop", "restart"}
BARE = re.compile(
    r"make (test|check|test-logs|test-down|test-integration|test-browser)"
    r"|docker compose (up|down|ps|logs|build|stop|restart)( [^|&;<>`$()\n]*)?"
    r"|docker ps( [^|&;<>`$()\n]*)?"
)
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;"}
ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")


def without_heredoc_bodies(command: str) -> str:
    lines, delimiter = [], None
    for line in command.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        lines.append(line)
        if match := HEREDOC.search(line):
            delimiter = match[2]
    return " ; ".join(lines)


def excluded_command(command: str) -> str | None:
    """The first excluded command in command position, if any."""
    lexer = shlex.shlex(without_heredoc_bodies(command), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None  # unparseable: let the command through
    segment: list[str] = []
    for token in [*tokens, ";"]:
        if token not in SEPARATORS:
            segment.append(token)
            continue
        words = segment
        while words and ASSIGNMENT.match(words[0]):
            words = words[1:]
        if words[:1] == ["make"] and len(words) > 1 and words[1] in MAKE_TARGETS:
            return f"make {words[1]}"
        if words[:2] == ["docker", "compose"] and len(words) > 2 and words[2] in COMPOSE_SUBCOMMANDS:
            return f"docker compose {words[2]}"
        if words[:2] == ["docker", "ps"]:
            return "docker ps"
        segment = []
    return None


command = json.load(sys.stdin).get("tool_input", {}).get("command", "").strip()
found = excluded_command(command)
if found and not BARE.fullmatch(command):
    print(
        f"Run `{found}` as a command of its own: no pipe, &&, ;, redirect, "
        "env-var prefix or extra arguments. Only the bare form is excluded from the "
        "sandbox (AGENTS.md, Running commands); `make test T=…` can't reach Docker at "
        "all, so use make test-unit, make test-integration or make test-browser.",
        file=sys.stderr,
    )
    sys.exit(2)
