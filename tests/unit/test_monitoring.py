"""The alert rules and dashboard in monitoring/ say what the issue and the
runbook say, so a slip shows here rather than as an alert that never fires.

A build check like test_templates.py, not a seam: Grafana evaluates these
files, and scripts/provision-canary imports them.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

MONITORING = Path(__file__).parents[2] / "monitoring"
RUNBOOK = Path(__file__).parents[2] / "docs" / "runbooks" / "README.md"
RUNBOOK_URL = "https://github.com/ckcabang/dots-and-dashes/blob/main/docs/runbooks/README.md"


def _rules() -> dict[str, dict[str, Any]]:
    group = json.loads((MONITORING / "alert-rules.json").read_text())
    return {rule["uid"]: rule for rule in group["rules"]}


def _dashboard() -> dict[str, Any]:
    return json.loads((MONITORING / "dashboard.json").read_text())


def _query(rule: dict[str, Any]) -> str:
    (query,) = [d for d in rule["data"] if d["datasourceUid"] != "__expr__"]
    return query["model"]["expr"]


def _threshold(rule: dict[str, Any]) -> tuple[str, float]:
    (condition,) = [d for d in rule["data"] if d["refId"] == rule["condition"]]
    (evaluator,) = [c["evaluator"] for c in condition["model"]["conditions"]]
    (value,) = evaluator["params"]
    return evaluator["type"], value


SAVE_ALERTS = ["save-failures", "save-latency"]


@pytest.mark.parametrize("alert", SAVE_ALERTS)
def test_each_save_alert_has_a_dev_rule_differing_only_in_environment(alert):
    rules = _rules()
    prod, dev = rules[f"dnd-{alert}-prod"], rules[f"dnd-{alert}-dev"]

    assert 'job="prod/dots-and-dashes"' in _query(prod)
    assert "dev" not in json.dumps(prod)
    assert json.loads(json.dumps(prod).replace("prod", "dev")) == dev


@pytest.mark.parametrize("env", ["prod", "dev"])
def test_the_failure_alert_fires_above_5_percent_of_saves_failed_over_10_minutes(env):
    rule = _rules()[f"dnd-save-failures-{env}"]

    assert _threshold(rule) == ("gt", 0.05)
    query = _query(rule)
    assert 'entry_saves_total{job="%s/dots-and-dashes", outcome="failed"}[10m]' % env in query
    # Refused saves are the User's doing: neither success nor failure.
    assert 'outcome=~"saved|failed"}[10m]' in query


@pytest.mark.parametrize("env", ["prod", "dev"])
def test_the_latency_alert_fires_above_a_1s_p95(env):
    rule = _rules()[f"dnd-save-latency-{env}"]

    assert _threshold(rule) == ("gt", 1)
    assert _query(rule).startswith("histogram_quantile(0.95,")
    assert f'entry_save_duration_seconds_bucket{{job="{env}/dots-and-dashes"' in _query(rule)


ALERTS = [*SAVE_ALERTS, "canary-failing"]


@pytest.mark.parametrize("alert", ALERTS)
def test_every_alert_has_a_prod_and_a_dev_rule(alert):
    rules = _rules()

    assert {f"dnd-{alert}-prod", f"dnd-{alert}-dev"} <= set(rules)
    assert {uid.rsplit("-", 1)[0].removeprefix("dnd-") for uid in rules} == set(ALERTS)


def test_the_canary_alert_fires_when_prods_canary_fails_or_stops_reporting():
    rule = _rules()["dnd-canary-failing-prod"]

    assert 'probe_success{job="dots-and-dashes-canary-prod"}[5m]' in _query(rule)
    assert _threshold(rule) == ("lt", 0.8)
    assert rule["noDataState"] == "Alerting"


def test_the_dev_canary_rule_differs_from_prods_only_in_job_and_window():
    """Dev's canary runs every 15 minutes, prod's every minute, so dev's window
    is 35m, always holding two runs or more, where prod's 5m would often hold
    none. A dev canary that stops reporting resolves rather than firing for
    good. Their descriptions say so; nothing else differs."""
    prod, dev = _rules()["dnd-canary-failing-prod"], _rules()["dnd-canary-failing-dev"]

    expected = json.loads(json.dumps(prod).replace("prod", "dev").replace("[5m]", "[35m]"))
    expected["data"][0]["relativeTimeRange"]["from"] = 35 * 60
    expected["noDataState"] = "OK"
    for rule in (expected, dev):
        rule["annotations"].pop("description")
    assert dev == expected
    assert 'probe_success{job="dots-and-dashes-canary-dev"}[35m]' in _query(dev)
    assert 'entry_saves_total{job="dev/dots-and-dashes"}[35m]' in _query(dev)
    description = _rules()["dnd-canary-failing-dev"]["annotations"]["description"]
    assert "every 15 minutes" in description and "35 minutes" in description


def _runbook_anchors() -> set[str]:
    """GitHub's anchor for each heading: lowercased, punctuation dropped, spaces to dashes."""
    prose = re.sub(r"^```.*?^```", "", RUNBOOK.read_text(), flags=re.MULTILINE | re.DOTALL)
    headings = re.findall(r"^#+ (.+)$", prose, flags=re.MULTILINE)
    return {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings}


@pytest.mark.parametrize("uid", list(_rules()))
def test_each_notification_carries_the_environment_image_panel_and_runbook(uid):
    rule = _rules()[uid]
    annotations = rule["annotations"]
    env = rule["labels"]["env"]
    panels = {panel["id"]: panel for panel in _dashboard()["panels"]}

    assert env in {"prod", "dev"} and uid.endswith(env)
    assert annotations["environment"] == env
    assert "image" in annotations
    assert annotations["__dashboardUid__"] == _dashboard()["uid"]
    assert int(annotations["__panelId__"]) in panels
    assert annotations["dashboard_url"].startswith(
        "${GRAFANA_URL}/d/%s?" % _dashboard()["uid"]
    )
    assert f"var-env={env}" in annotations["dashboard_url"]
    runbook, _, anchor = annotations["runbook_url"].partition("#")
    assert runbook == RUNBOOK_URL
    assert anchor in _runbook_anchors()


@pytest.mark.parametrize("alert", SAVE_ALERTS)
def test_a_save_alert_names_the_image_whose_saves_it_fired_on(alert):
    rule = _rules()[f"dnd-{alert}-prod"]

    assert "by (image)" in _query(rule) or "by (le, image)" in _query(rule)
    assert rule["annotations"]["image"] == "{{ $labels.image }}"
    assert "var-image={{ $labels.image | urlquery }}" in rule["annotations"]["dashboard_url"]


@pytest.mark.parametrize(("env", "window"), [("prod", "5m"), ("dev", "35m")])
def test_the_canary_alert_names_the_image_its_environment_is_serving(env, window):
    """The probe can't know the image, so the rule joins it with the images
    the app's save metrics carry, and still fires with none (the app down)."""
    rule = _rules()[f"dnd-canary-failing-{env}"]
    probe = f'min(avg_over_time(probe_success{{job="dots-and-dashes-canary-{env}"}}[{window}]))'

    assert _query(rule) == (
        "group by (image) "
        f'(last_over_time(entry_saves_total{{job="{env}/dots-and-dashes"}}[{window}]))'
        f" * 0 + on() group_left() {probe} or on() {probe}"
    )
    assert "{{ $labels.image | urlquery }}" in rule["annotations"]["dashboard_url"]


@pytest.mark.parametrize("uid", list(_rules()))
def test_every_notification_takes_its_image_from_the_alerts_labels(uid):
    assert "{{ $labels.image }}" in _rules()[uid]["annotations"]["image"]


def test_the_rules_read_prometheus_through_the_uid_the_wizard_fills_in():
    for rule in _rules().values():
        (query,) = [d for d in rule["data"] if d["datasourceUid"] != "__expr__"]
        assert query["datasourceUid"] == "${PROMETHEUS_UID}"


def _panel(title: str) -> dict[str, Any]:
    (panel,) = [p for p in _dashboard()["panels"] if p["title"] == title]
    return panel


def test_the_dashboard_filters_by_environment_and_image():
    variables = {v["name"]: v for v in _dashboard()["templating"]["list"]}

    assert [o["value"] for o in variables["env"]["options"]] == ["prod", "dev"]
    assert "label_values(" in variables["image"]["query"]["query"]
    assert ", image)" in variables["image"]["query"]["query"]
    for title in ["Saves by outcome", "Save failure rate", "p95 save latency"]:
        for target in _panel(title)["targets"]:
            assert 'job="$env/dots-and-dashes"' in target["expr"]
            assert 'image=~"$image"' in target["expr"]


def test_the_dashboard_shows_saves_by_outcome_p95_with_exemplars_and_canary_pass_rate():
    (by_outcome,) = _panel("Saves by outcome")["targets"]
    assert "sum by (outcome) (rate(entry_saves_total{" in by_outcome["expr"]
    (p95,) = _panel("p95 save latency")["targets"]
    assert p95["expr"].startswith("histogram_quantile(0.95,")
    assert p95["exemplar"] is True
    (canary,) = _panel("Canary pass rate")["targets"]
    assert 'probe_success{job="dots-and-dashes-canary-$env"}' in canary["expr"]


CANARY = MONITORING / "canary.js"


def test_the_canary_script_has_the_one_line_the_dev_check_changes():
    """scripts/provision-canary makes the dev check's script by changing this
    line's 'prod' to 'dev': it must be there exactly once."""
    assert CANARY.read_text().count("const ENVIRONMENT = __ENV.CANARY_ENV || 'prod';") == 1
    assert "secret: 'canary-password-dev'" in CANARY.read_text()
