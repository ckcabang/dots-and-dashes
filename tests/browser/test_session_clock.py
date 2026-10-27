"""A browser session outlives the host clock stepping backwards (issues #52 and #64).

A WSL2 host's wall clock steps back by up to half a second. The app container
runs on that clock, and no test can step a container's clock, so this test runs
the same app, `create_app()` on the system clock, in-process on the host, where
it can step the clock the system clock reads.
"""

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from dots_and_dashes.settings import Settings
from dots_and_dashes.web import create_app


@dataclass
class HostClock:
    """The host's wall clock, which `time.time()` reads, held still until stepped."""

    now: float

    def step(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class AppOnTheHost:
    base_url: str
    host_clock: HostClock


@pytest.fixture
def app_on_the_host(app_database_url: str, monkeypatch) -> Iterator[AppOnTheHost]:
    # A fifth of a second into a whole second, so a step back of half a second crosses it.
    host_clock = HostClock(now=float(int(time.time())) + 0.2)
    monkeypatch.setattr(time, "time", lambda: host_clock.now)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(Settings(database_url=app_database_url)),
            host="127.0.0.1",
            port=0,
            log_level="warning",
        )
    )
    serving = threading.Thread(target=server.run, daemon=True)
    serving.start()
    started = time.monotonic()
    while not server.started:
        assert serving.is_alive() and time.monotonic() - started < 10, "the app didn't start"
        time.sleep(0.05)
    [listening] = server.servers
    port = listening.sockets[0].getsockname()[1]
    yield AppOnTheHost(f"http://127.0.0.1:{port}", host_clock)
    server.should_exit = True
    serving.join(timeout=10)
    assert not serving.is_alive(), "the app didn't shut down"


def test_a_session_survives_the_host_clock_stepping_back_across_a_second(
    page: Page, app_on_the_host: AppOnTheHost, user: str, password: str
):
    base_url = app_on_the_host.base_url
    page.context.clear_cookies()
    page.goto(f"{base_url}/login")
    page.get_by_label("Email").fill(user)
    page.get_by_label("Password").fill(password)
    page.get_by_label("Password").press("Enter")
    expect(page).to_have_url(f"{base_url}/")

    app_on_the_host.host_clock.step(-0.459)
    page.goto(f"{base_url}/")

    expect(page).to_have_url(f"{base_url}/")
    expect(page.get_by_label("New entry")).to_be_visible()
