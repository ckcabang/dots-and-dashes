"""The four Fly configs hold what a deploy needs and what each environment promises.

Fly refuses a deploy whose app defines [processes] but has a [[services]] entry naming none:
"Service has no processes set but app has 1 processes defined" (#61, fixed in #68).
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ["fly.dev.toml", "fly.prod.toml", "fly.dev-db.toml", "fly.prod-db.toml"]
DB_CONFIGS = ["fly.dev-db.toml", "fly.prod-db.toml"]


def load(name: str) -> dict[str, Any]:
    return tomllib.loads((ROOT / name).read_text())


def process_mismatches(config: dict[str, Any]) -> list[str]:
    """What in the config names no process, or one [processes] doesn't define.

    Every [[services]] entry must name its processes. [mounts] may leave them out,
    since Fly then mounts the volume for every process.
    """
    defined = set(config.get("processes", {}))
    if not defined:
        return []
    problems = []
    for i, service in enumerate(config.get("services", [])):
        named = service.get("processes")
        if not named:
            problems.append(f"[[services]] #{i} names no processes")
        elif unknown := set(named) - defined:
            problems.append(f"[[services]] #{i} names undefined processes {sorted(unknown)}")
    mounts = config.get("mounts", [])
    for i, mount in enumerate(mounts if isinstance(mounts, list) else [mounts]):
        if unknown := set(mount.get("processes", [])) - defined:
            problems.append(f"[mounts] #{i} names undefined processes {sorted(unknown)}")
    return problems


def machine_settings(config: dict[str, Any]) -> list[tuple[Any, Any]]:
    """(auto_stop_machines, min_machines_running) of [http_service] and each [[services]]."""
    sections = config.get("services", []) + (
        [config["http_service"]] if "http_service" in config else []
    )
    return [(s.get("auto_stop_machines"), s.get("min_machines_running")) for s in sections]


@pytest.mark.parametrize("name", CONFIGS)
def test_every_service_names_processes_the_app_defines(name):
    assert process_mismatches(load(name)) == []


def test_a_service_naming_no_processes_is_caught():
    config = tomllib.loads(
        """
        [processes]
          app = "postgres"
        [mounts]
          source = "pgdata"
          destination = "/data"
          processes = ["web"]
        [[services]]
          internal_port = 5432
        """
    )
    assert process_mismatches(config) == [
        "[[services]] #0 names no processes",
        "[mounts] #0 names undefined processes ['web']",
    ]


@pytest.mark.parametrize("name", ["fly.dev.toml", "fly.dev-db.toml"])
def test_dev_stops_when_idle(name):
    settings = machine_settings(load(name))
    assert settings and all(s == ("stop", 0) for s in settings)


@pytest.mark.parametrize("name", ["fly.prod.toml", "fly.prod-db.toml"])
def test_prod_is_always_on(name):
    settings = machine_settings(load(name))
    assert settings and all(s == ("off", 1) for s in settings)


@pytest.mark.parametrize("name", DB_CONFIGS)
def test_the_database_listens_only_on_its_flycast_port(name):
    config = load(name)
    assert "http_service" not in config
    assert [(s["internal_port"], s["ports"]) for s in config["services"]] == [
        (5432, [{"port": 5432}])
    ]
