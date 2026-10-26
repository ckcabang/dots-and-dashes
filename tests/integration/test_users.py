"""Each User's journal is theirs alone, and Users come only from the CLI."""

import pytest
from fastapi.testclient import TestClient

from dots_and_dashes import cli
from dots_and_dashes.web import create_app


@pytest.fixture
def app(settings, clock):
    return create_app(settings, clock=clock)


def _log(client, text: str) -> int:
    response = client.post("/api/entries", json={"text": text})
    assert response.status_code == 201
    return response.json()["id"]


def _texts(client) -> list[str]:
    return [e["text"] for e in client.get("/api/daily-logs/today").json()["entries"]]


def test_a_user_never_sees_another_users_entries(app, create_user, logged_in):
    other = create_user("other@example.com")
    with logged_in(app) as mine:
        _log(mine, "buy milk")
    with logged_in(app, email=other) as theirs:
        _log(theirs, "walk the dog")

        assert _texts(theirs) == ["walk the dog"]
    with logged_in(app) as mine:
        assert _texts(mine) == ["buy milk"]


def test_a_user_cannot_read_change_or_delete_another_users_entry(app, create_user, logged_in):
    other = create_user("other@example.com")
    with logged_in(app) as mine:
        task = _log(mine, "buy milk")

    with logged_in(app, email=other) as theirs:
        attempts = [
            theirs.post(f"/api/entries/{task}/complete"),
            theirs.patch(f"/api/entries/{task}", json={"text": "hijacked"}),
            theirs.post(f"/api/entries/{task}/migrate", json={"to": "month"}),
            theirs.delete(f"/api/entries/{task}"),
            theirs.post(f"/entries/{task}/cancel"),
        ]

    assert [attempt.status_code for attempt in attempts] == [404] * 5
    with logged_in(app) as mine:
        [entry] = mine.get("/api/daily-logs/today").json()["entries"]
    assert (entry["text"], entry["state"]) == ("buy milk", "open")


def test_the_canary_users_journal_is_isolated_from_the_users(app, create_user, logged_in):
    canary = create_user("canary@example.com", canary=True)
    with logged_in(app) as mine:
        _log(mine, "buy milk")
        _log(mine, "o 14:00 dentist")

    with logged_in(app, email=canary) as canary_client:
        _log(canary_client, "canary check")
        assert _texts(canary_client) == ["canary check"]
        calendar = canary_client.get("/api/monthly-logs/2026-10").json()["calendar"]
        assert [day["events"] for day in calendar if day["events"]] == []
        migration = canary_client.get("/api/daily-migration").json()
        assert [
            task["text"]
            for day in migration["days"]
            for group in day["groups"]
            for task in group["tasks"]
        ] == ["canary check"]
    with logged_in(app) as mine:
        assert "canary check" not in _texts(mine)


def test_creating_a_user_twice_with_one_email_is_refused(create_user):
    create_user("me@example.com")

    with pytest.raises(SystemExit, match="already exists"):
        create_user("ME@example.com")


def test_a_user_needs_an_iana_timezone(create_user):
    with pytest.raises(SystemExit):
        create_user("me@example.com", timezone="Mars/Olympus_Mons")


def test_without_a_password_secret_the_cli_prompts_for_one(
    settings, monkeypatch, logged_in, app
):
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.delenv("USER_PASSWORD", raising=False)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "correct horse battery staple")

    cli.main(["create-user", "--email", "prompted@example.com", "--timezone", "UTC"])

    with logged_in(app, email="prompted@example.com") as client:
        assert client.get("/api/daily-logs/today").status_code == 200


def test_the_cli_refuses_an_empty_password(settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.delenv("USER_PASSWORD", raising=False)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "")

    with pytest.raises(SystemExit, match="empty"):
        cli.main(["create-user", "--email", "me@example.com", "--timezone", "UTC"])


def test_creating_a_user_if_missing_leaves_an_existing_user_alone(
    settings, monkeypatch, app, capsys
):
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    local_user = ["create-user", "--email", "local@example.com", "--timezone", "UTC"]
    monkeypatch.setenv("USER_PASSWORD", "the first password")
    cli.main([*local_user, "--if-missing"])
    monkeypatch.setenv("USER_PASSWORD", "a second password")

    cli.main([*local_user, "--if-missing"])

    assert "already exists" in capsys.readouterr().out
    with TestClient(app) as client:
        second = {"email": "local@example.com", "password": "a second password"}
        assert client.post("/login", data=second).status_code == 401
        first = {"email": "local@example.com", "password": "the first password"}
        assert client.post("/login", data=first, follow_redirects=False).status_code == 303
