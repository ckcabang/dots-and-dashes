import re
import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from dots_and_dashes.web import SESSION_CLOCK_HOLD, create_app

# A value for each path parameter, so every route can be asked for.
PATH_VALUES = {
    "entry_id": "1",
    "capture_id": "1",
    "day": "2026-10-25",
    "month": "2026-10",
    "change": "complete",
}
PUBLIC = {"/login", "/logout", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _journal_routes(settings, clock) -> list[tuple[str, str]]:
    # Flagged features on, so their routes are checked too.
    app = create_app(replace(settings, monthly_review=True), clock=clock)
    return [
        (method, re.sub(r"{(\w+)}", lambda m: PATH_VALUES[m[1]], route.path))
        for route in app.routes
        if isinstance(route, APIRoute) and route.path not in PUBLIC
        for method in route.methods or ()
    ]


@pytest.fixture
def anonymous(settings, clock):
    app = create_app(replace(settings, monthly_review=True), clock=clock)
    with TestClient(app, follow_redirects=False) as client:
        yield client


def test_without_a_session_pages_send_you_to_log_in_and_the_api_refuses(anonymous):
    page = anonymous.get("/")
    api = anonymous.get("/api/daily-logs/today")

    assert page.status_code == 303
    assert page.headers["location"] == "/login"
    assert api.status_code == 401


def test_every_journal_page_and_api_route_refuses_access_without_a_session(
    settings, clock, anonymous
):
    routes = _journal_routes(settings, clock)
    assert len(routes) > 30

    refused = {
        (method, path): anonymous.request(method, path).status_code for method, path in routes
    }

    assert {
        route: status
        for route, status in refused.items()
        if status != (401 if route[1].startswith("/api/") else 303)
    } == {}


def test_htmx_without_a_session_is_redirected_to_log_in_rather_than_swapped(anonymous):
    response = anonymous.post(
        "/entries", data={"text": "buy milk"}, headers={"HX-Request": "true"}
    )

    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/login"


def test_there_is_no_sign_up_route(settings, clock):
    paths = {path for _, path in _journal_routes(settings, clock)}

    assert not any(re.search(r"sign-?up|register|users", path) for path in paths)


def test_logging_in_sets_a_signed_session_cookie_lasting_30_days(settings, clock, user):
    with TestClient(create_app(settings, clock=clock), follow_redirects=False) as client:
        logged_in = client.post(
            "/login", data={"email": user, "password": "correct horse battery staple"}
        )
        todays_daily_log = client.get("/api/daily-logs/today")

    assert logged_in.status_code == 303
    assert logged_in.headers["location"] == "/"
    cookie = logged_in.headers["set-cookie"]
    assert "max-age=2592000" in cookie.lower()
    assert "httponly" in cookie.lower()
    assert todays_daily_log.status_code == 200


def test_the_email_is_matched_whatever_its_case(settings, clock, user, logged_in):
    with logged_in(create_app(settings, clock=clock), email=user.upper()) as client:
        assert client.get("/api/daily-logs/today").status_code == 200


@pytest.mark.parametrize(
    "email, password",
    [("me@example.com", "wrong password"), ("nobody@example.com", "correct horse battery staple")],
)
def test_a_wrong_email_or_password_is_refused_and_logs_nothing_in(
    settings, clock, user, email, password
):
    with TestClient(create_app(settings, clock=clock)) as client:
        refused = client.post("/login", data={"email": email, "password": password})
        todays_daily_log = client.get("/api/daily-logs/today")

    assert refused.status_code == 401
    assert "don't match" in refused.text
    assert "set-cookie" not in refused.headers
    assert todays_daily_log.status_code == 401


@pytest.mark.unauthorized_requests
def test_a_forged_session_cookie_is_refused(settings, clock, user, logged_in):
    with logged_in(create_app(settings, clock=clock)) as client:
        signed = client.cookies["session"]
        client.cookies.set("session", signed[:-4] + "AAAA")
        forged = client.get("/api/daily-logs/today")

    assert forged.status_code == 401


def test_a_session_signed_by_another_secret_is_refused(settings, clock, logged_in):
    with logged_in(create_app(settings, clock=clock)) as client:
        signed = client.cookies["session"]
    other = replace(settings, session_secret="another secret")

    with TestClient(create_app(other, clock=clock), cookies={"session": signed}) as client:
        assert client.get("/api/daily-logs/today").status_code == 401


def test_a_session_survives_the_host_clock_stepping_backwards(
    settings, clock, logged_in, monkeypatch
):
    # A WSL2 host's wall clock steps back by up to half a second (issue #52).
    # Across a whole second, a cookie signed by the wall clock looks signed in
    # the future and is refused. The session is timed by the app's clock instead.
    host_clock = {"now": 1_800_000_000.2}
    monkeypatch.setattr(time, "time", lambda: host_clock["now"])

    with logged_in(create_app(settings, clock=clock)) as client:
        host_clock["now"] -= 0.459
        after_the_step = client.get("/api/daily-logs/today")

    assert after_the_step.status_code == 200, after_the_step.text


@pytest.fixture
def host_clock(monkeypatch):
    """The host's wall clock, which the app's system clock reads: held still until moved."""
    host_clock = {"now": 1_800_000_000.2}
    monkeypatch.setattr(time, "time", lambda: host_clock["now"])
    return host_clock


def test_a_session_on_the_system_clock_survives_it_stepping_backwards(
    settings, host_clock, logged_in
):
    # As in prod, dev and the browser suite's app container (issue #64).
    with logged_in(create_app(settings)) as client:
        host_clock["now"] -= 0.459
        after_the_step = client.get("/api/daily-logs/today")
        host_clock["now"] += 2
        after_catching_up = client.get("/api/daily-logs/today")

    assert after_the_step.status_code == 200, after_the_step.text
    assert after_catching_up.status_code == 200, after_catching_up.text


def _present(settings, signed: str):
    """Ask for today's Daily Log with a session cookie, as a client that never expires it."""
    with TestClient(create_app(settings), cookies={"session": signed}) as client:
        return client.get("/api/daily-logs/today")


def _signed_at(settings, signed: str) -> int:
    """The whole second a session cookie was signed at, by its own timestamp."""
    _, signed_at = TimestampSigner(settings.session_secret).unsign(signed, return_timestamp=True)
    return int(signed_at.timestamp())


def test_a_session_on_the_system_clock_survives_it_stepping_back_by_the_hold(
    settings, host_clock, logged_in
):
    with logged_in(create_app(settings)) as client:
        host_clock["now"] -= SESSION_CLOCK_HOLD
        after_the_step = client.get("/api/daily-logs/today")

    assert after_the_step.status_code == 200, after_the_step.text


@pytest.mark.parametrize(
    "jump, correction",
    [
        pytest.param(24 * 60 * 60, -24 * 60 * 60, id="a day forward, then corrected"),
        pytest.param(0, -(SESSION_CLOCK_HOLD + 1), id="a second further back than the hold"),
        pytest.param(0, -60, id="a minute back"),
    ],
)
def test_a_session_signed_after_the_system_clock_is_corrected_is_dated_by_it(
    settings, host_clock, logged_in, password, user, jump, correction
):
    # A bad NTP sync, say, then its correction (issue #71). Logging in again
    # once the clock is corrected must not sign the cookie at the bad time.
    with logged_in(create_app(settings)) as client:
        host_clock["now"] += jump
        during_the_jump = client.get("/api/daily-logs/today")
        host_clock["now"] += correction
        logged_in_again = client.post("/login", data={"email": user, "password": password})
        signed = client.cookies["session"]

    # A process that never read the bad time: another Machine, or the app restarted.
    in_a_fresh_process = _present(settings, signed)

    assert during_the_jump.status_code == 200, during_the_jump.text
    assert logged_in_again.status_code == 200, logged_in_again.text
    assert _signed_at(settings, signed) == int(host_clock["now"])
    assert in_a_fresh_process.status_code == 200, in_a_fresh_process.text


def test_a_session_on_the_system_clock_expires_after_30_days(settings, host_clock, logged_in):
    with logged_in(create_app(settings)) as client:
        signed = client.cookies["session"]

    host_clock["now"] += 30 * 24 * 60 * 60
    on_its_last_second = _present(settings, signed)
    host_clock["now"] += 1
    expired = _present(settings, signed)

    assert on_its_last_second.status_code == 200, on_its_last_second.text
    assert expired.status_code == 401, expired.text


@pytest.mark.unauthorized_requests
def test_a_tampered_session_on_the_system_clock_is_refused(settings, host_clock, logged_in):
    with logged_in(create_app(settings)) as client:
        signed = client.cookies["session"]
        client.cookies.set("session", signed[:-4] + "AAAA")
        tampered = client.get("/api/daily-logs/today")

    assert tampered.status_code == 401, tampered.text


def test_a_session_dated_after_the_system_clock_is_refused(settings, host_clock, logged_in):
    with logged_in(create_app(settings)) as client:
        signed = client.cookies["session"]
    host_clock["now"] -= 60

    # A process that never read the later time: another Machine, or the app restarted.
    future_dated = _present(settings, signed)

    assert future_dated.status_code == 401, future_dated.text


@pytest.mark.unauthorized_requests
def test_logging_out_ends_the_session(settings, clock, logged_in):
    with logged_in(create_app(settings, clock=clock)) as client:
        page = client.get("/")
        logged_out = client.post("/logout", follow_redirects=False)
        after = client.get("/api/daily-logs/today")

    assert "Log out" in page.text
    assert logged_out.status_code == 303
    assert logged_out.headers["location"] == "/login"
    assert after.status_code == 401


def test_todays_daily_log_follows_the_users_timezone(settings, create_user, logged_in):
    # 23:30 UTC on 25 Oct is already 26 Oct in Tokyo, and still 25 Oct in Los Angeles.
    app = create_app(settings, clock=lambda: datetime(2026, 10, 25, 23, 30, tzinfo=UTC))
    tokyo = create_user("tokyo@example.com", timezone="Asia/Tokyo")

    with logged_in(app) as los_angeles_client:
        los_angeles = los_angeles_client.get("/api/daily-logs/today").json()
    with logged_in(app, email=tokyo) as tokyo_client:
        tokyo_today = tokyo_client.get("/api/daily-logs/today").json()

    assert los_angeles["date"] == "2026-10-25"
    assert tokyo_today["date"] == "2026-10-26"


def test_with_secure_cookies_on_the_session_cookie_is_sent_over_https_only(
    settings, clock, user
):
    app = create_app(replace(settings, secure_cookies=True), clock=clock)
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as client:
        logged_in = client.post(
            "/login", data={"email": user, "password": "correct horse battery staple"}
        )

    assert "secure" in logged_in.headers["set-cookie"].lower()
