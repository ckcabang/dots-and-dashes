from datetime import date, timedelta
from uuid import uuid4

from playwright.sync_api import Page, expect


def _log(page: Page, text: str) -> None:
    quick_entry = page.get_by_label("New entry")
    quick_entry.fill(text)
    quick_entry.press("Enter")
    expect(quick_entry).to_have_value("")


def test_daily_migration_decides_each_open_task_with_one_key(page: Page):
    # The stack's journal outlives test runs, so the Entries need unique text.
    run = uuid4().hex[:8]
    completed, cancelled, carried, later = (
        f"{name} {run}" for name in ["file taxes", "learn banjo", "write report", "renew passport"]
    )
    page.goto("/")
    today = date.fromisoformat(page.locator("body").get_attribute("data-today") or "")
    earlier = today - timedelta(days=3)
    page.goto(f"/days/{earlier}")
    for task in [completed, cancelled, carried, later]:
        _log(page, f". {task}")

    page.goto("/migration")
    planning = page.locator("[data-planning]").get_attribute("data-planning")

    # p plans the other day instead (today in the evening, tomorrow otherwise),
    # and the keys then act for that day.
    page.keyboard.press("p")
    expect(page.locator("[data-planning]")).not_to_have_attribute("data-planning", planning or "")
    planning = page.locator("[data-planning]").get_attribute("data-planning")
    review = page.locator("#daily-migration")

    def entry(text: str):
        return review.get_by_role("listitem").filter(has_text=text)

    for task in [completed, cancelled, carried, later]:
        expect(entry(task)).to_have_attribute("data-state", "open")

    # x completes and c cancels; the decided Task stays in view, marked.
    entry(completed).focus()
    page.keyboard.press("x")
    expect(entry(completed)).to_have_attribute("data-state", "completed")
    page.keyboard.press("j")
    expect(entry(cancelled)).to_be_focused()
    page.keyboard.press("c")
    expect(entry(cancelled)).to_have_attribute("data-state", "cancelled")

    # m Migrates to the day being planned; the Task leaves the review and the
    # selection moves on to the next one.
    page.keyboard.press("j")
    expect(entry(carried)).to_be_focused()
    page.keyboard.press("m")
    expect(entry(carried)).to_have_count(0)
    expect(entry(later)).to_be_focused()

    # s Schedules, asking where to: a month next year, in the Future Log.
    next_year = f"{today.year + 1}-03"
    page.once("dialog", lambda dialog: dialog.accept(next_year))
    page.keyboard.press("s")
    expect(entry(later)).to_have_count(0)

    page.goto(f"/days/{planning}")
    copy = page.get_by_role("listitem").filter(has_text=carried)
    expect(copy).to_have_attribute("data-state", "open")
    expect(copy.locator(".migration-count")).to_have_text(">>1")

    page.goto(f"/days/{earlier}")
    for task, marker in [(completed, "×"), (cancelled, "•"), (carried, ">"), (later, "<")]:
        line = page.get_by_role("listitem").filter(has_text=task)
        expect(line.locator(".state-marker")).to_have_text(marker)

    page.goto("/future")
    expect(page.locator(f"#entries-{next_year}").get_by_role("listitem").filter(has_text=later)).to_have_count(1)
