"""Mobile Capture and Inbox Triage. Each test logs in as a User of its own, so
its Inbox holds only the Captures it made."""

from datetime import date

import pytest
from playwright.sync_api import Page, ViewportSize, expect

PHONE = ViewportSize(width=390, height=844)
DESK = ViewportSize(width=1280, height=800)


@pytest.fixture
def own_inbox(page: Page, create_user, password: str) -> Page:
    """The page, logged in as a fresh User with an empty Inbox."""
    page.context.clear_cookies()
    response = page.request.post("/login", form={"email": create_user(), "password": password})
    assert response.ok, response.status
    return page


def test_capturing_on_a_phone_saves_raw_text_to_the_inbox(own_inbox: Page):
    page = own_inbox
    page.set_viewport_size(PHONE)
    page.goto("/capture")
    box = page.get_by_label("Capture")
    expect(box).to_be_focused()

    page.keyboard.type("o 9am dentist")
    page.keyboard.press("Enter")

    expect(page.get_by_role("status")).to_have_text("Captured. It's waiting in the Inbox.")
    expect(box).to_have_value("")
    expect(box).to_be_focused()
    page.keyboard.type("call the plumber")
    page.keyboard.press("Enter")
    expect(page.get_by_role("status")).to_be_visible()

    # Back at the desk, the Daily Log shows the Inbox count, and nothing was
    # classified on the way.
    page.set_viewport_size(DESK)
    page.goto("/")
    expect(page.get_by_role("link", name="Inbox (2)")).to_be_visible()
    expect(page.locator("#entries > .entry")).to_have_count(0)


def test_triaging_the_inbox_from_the_keyboard(own_inbox: Page):
    page = own_inbox
    for text in ["*o 9am dentist", "renew passport", "asdfgh", "conference"]:
        assert page.request.post("/api/captures", data={"text": text}).ok
    page.goto("/")
    today = date.fromisoformat(page.locator("body").get_attribute("data-today") or "")
    next_year = f"{today.year + 1}-03"

    # i opens the Inbox from the Daily Log.
    page.keyboard.press("Escape")
    page.keyboard.press("i")
    expect(page.get_by_role("heading", name="Inbox (4)")).to_be_visible()
    entry = page.get_by_label("Entry")

    # The suggestion comes from the Prefix; Enter places it on today's Daily Log.
    expect(page.locator(".suggestion")).to_contain_text("Event, Priority, at 09:00")
    expect(entry).to_have_value("*o 09:00 dentist")
    expect(entry).to_be_focused()
    page.keyboard.press("Enter")

    # The next one is adjusted, Priority added, and placed on the month's task list.
    expect(page.get_by_role("heading", name="Inbox (3)")).to_be_visible()
    expect(entry).to_have_value("renew passport")
    expect(entry).to_be_focused()
    page.keyboard.press("Home")
    page.keyboard.type("* ")
    page.keyboard.press("Tab")
    page.keyboard.press("ArrowDown")
    expect(page.get_by_role("radio", name="task list")).to_be_checked()
    page.keyboard.press("Enter")

    # A throwaway jotting is Deleted.
    expect(page.get_by_role("heading", name="Inbox (2)")).to_be_visible()
    expect(entry).to_have_value("asdfgh")
    page.once("dialog", lambda dialog: dialog.accept())
    page.keyboard.press("Escape")
    page.keyboard.press("Delete")

    # The last becomes an Event in the Future Log, under a later month.
    expect(page.get_by_role("heading", name="Inbox (1)")).to_be_visible()
    expect(entry).to_have_value("conference")
    page.keyboard.press("Home")
    page.keyboard.type("o ")
    page.keyboard.press("Tab")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    expect(page.get_by_role("radio", name="Future Log")).to_be_checked()
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    page.keyboard.type(next_year)
    page.keyboard.press("Enter")

    expect(page.get_by_role("heading", name="Inbox (0)")).to_be_visible()
    expect(page.get_by_text("The Inbox is empty.")).to_be_visible()

    def entry_on(path: str, text: str):
        page.goto(path)
        return page.locator(".entries > .entry").filter(has_text=text)

    dentist = entry_on("/", "dentist")
    expect(dentist).to_have_class("entry entry--event")
    expect(dentist.locator(".signifier--priority")).to_have_count(1)
    expect(dentist.locator("time")).to_have_text("09:00")
    passport = entry_on("/months", "renew passport")
    expect(passport).to_have_attribute("data-state", "open")
    expect(passport.locator(".signifier--priority")).to_have_count(1)
    expect(entry_on("/", "asdfgh")).to_have_count(0)
    page.goto("/future")
    conference = page.locator(f"#entries-{next_year} > .entry").filter(has_text="conference")
    expect(conference).to_have_class("entry entry--event")
