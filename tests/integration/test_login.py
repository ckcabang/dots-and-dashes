import re
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from dots_and_dashes.web import create_app

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
