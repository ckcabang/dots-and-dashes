import re
from uuid import uuid4

from playwright.sync_api import Page, expect


def test_keyboard_moves_between_days_and_logs_on_the_day_being_viewed(page: Page):
    # The stack's journal outlives test runs, so the Task needs unique text.
    text = f"pack bags {uuid4().hex[:8]}"
    page.goto("/days/2026-10-31")
    heading = page.get_by_role("heading", level=1)

    # Leave the quick entry input, so keys are shortcuts rather than text.
    page.keyboard.press("Escape")
    page.keyboard.press("]")
    expect(page).to_have_url(re.compile(r"/days/2026-11-01$"))
    expect(heading).to_have_text("Sunday, 1 November 2026")

    page.keyboard.press("Escape")
    page.keyboard.press("[")
    expect(heading).to_have_text("Saturday, 31 October 2026")
    page.keyboard.press("Escape")
    page.keyboard.press("[")
    expect(page).to_have_url(re.compile(r"/days/2026-10-30$"))

    quick_entry = page.get_by_label("New entry")
    expect(quick_entry).to_be_focused()
    page.keyboard.type(text)
    page.keyboard.press("Enter")
    expect(page.get_by_role("listitem").filter(has_text=text)).to_have_count(1)

    page.goto("/days/2026-10-31")
    expect(page.get_by_role("listitem").filter(has_text=text)).to_have_count(0)
    page.goto("/days/2026-10-30")
    expect(page.get_by_role("listitem").filter(has_text=text)).to_have_count(1)


def test_brackets_typed_into_quick_entry_stay_in_the_text(page: Page):
    page.goto("/days/2026-10-31")
    quick_entry = page.get_by_label("New entry")
    expect(quick_entry).to_be_focused()

    page.keyboard.type("[draft] ]")

    expect(quick_entry).to_have_value("[draft] ]")
    expect(page).to_have_url(re.compile(r"/days/2026-10-31$"))


def test_any_date_can_be_opened_from_the_date_picker(page: Page):
    page.goto("/")

    page.get_by_label("Go to date").fill("2026-12-25")
    page.get_by_role("button", name="Go").click()

    expect(page).to_have_url(re.compile(r"/days/2026-12-25$"))
    expect(page.get_by_role("heading", level=1)).to_have_text("Friday, 25 December 2026")
