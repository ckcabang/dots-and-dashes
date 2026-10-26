import re
from datetime import date, timedelta
from uuid import uuid4

from playwright.sync_api import Page, expect


def _today(page: Page) -> date:
    return date.fromisoformat(page.locator("body").get_attribute("data-today") or "")


def _log(page: Page, text: str) -> None:
    quick_entry = page.get_by_label("New entry")
    quick_entry.fill(text)
    quick_entry.press("Enter")
    expect(quick_entry).to_have_value("")


def test_migrating_and_scheduling_a_task_from_the_keyboard(page: Page):
    # The stack's journal outlives test runs, so the Entries need unique text.
    run = uuid4().hex[:8]
    task, note = f"write report {run}", f"draft is in the shared folder {run}"
    page.goto("/")
    today = _today(page)
    page.goto(f"/days/{today - timedelta(days=1)}")
    _log(page, f". {task}")
    _log(page, f"- {note}")

    def entry(text: str):
        return page.get_by_role("listitem").filter(has_text=text)

    # Tab nests the Note under the Task, so it moves with the Task.
    page.keyboard.press("Escape")
    page.keyboard.press("Tab")
    # The server redraws the Daily Log, then selects the Note again; a key
    # pressed before that lands on the old list.
    expect(entry(note)).to_have_class(re.compile(r"\bentry--nested\b"))
    expect(entry(note)).to_be_focused()
    page.keyboard.press("k")
    expect(entry(task)).to_be_focused()

    # m Migrates the selected Task to the day being planned, which the server
    # decides: today, or tomorrow the night before.
    page.keyboard.press("m")
    expect(entry(task)).to_have_attribute("data-state", "migrated")
    expect(entry(task).locator(".state-marker")).to_have_text(">")
    expect(entry(task).locator(".migration-count")).to_have_text(">>1")
    expect(entry(note)).to_have_count(0)
    expect(entry(task)).to_be_focused()

    page.goto("/migration")
    planning = page.locator("[data-planning]").get_attribute("data-planning")
    page.goto(f"/days/{planning}")
    expect(entry(task)).to_have_attribute("data-state", "open")
    expect(entry(task).locator(".migration-count")).to_have_text(">>1")
    expect(entry(note)).to_have_count(1)

    # s Schedules it, asking where to: a month next year, in the Future Log.
    later = f"{today.year + 1}-03"
    page.once("dialog", lambda dialog: dialog.accept(later))
    entry(task).focus()
    page.keyboard.press("s")
    expect(entry(task)).to_have_attribute("data-state", "scheduled")
    expect(entry(task).locator(".state-marker")).to_have_text("<")
    expect(entry(task).locator(".migration-count")).to_have_text(">>2")

    page.goto("/future")
    march = page.locator(f"#entries-{later}")
    expect(march.get_by_role("listitem").filter(has_text=task)).to_have_attribute(
        "data-state", "open"
    )
    expect(march.get_by_role("listitem").filter(has_text=note)).to_have_count(1)
