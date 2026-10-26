from uuid import uuid4

from playwright.sync_api import Page, expect


def _log_tasks(page: Page, *texts: str) -> None:
    quick_entry = page.get_by_label("New entry")
    for text in texts:
        quick_entry.fill(text)
        quick_entry.press("Enter")
        expect(page.get_by_role("listitem").filter(has_text=text)).to_have_count(1)


def test_acting_on_tasks_from_the_keyboard(page: Page):
    # The stack's journal outlives test runs, so Entries need unique text.
    run = uuid4().hex[:8]
    first, second, third = (f"{name} {run}" for name in ("call mum", "pay rent", "oops"))
    page.goto("/")
    _log_tasks(page, first, second, third)

    def entry(text: str):
        return page.get_by_role("listitem").filter(has_text=text)

    # From the quick-entry box, the arrow keys reach the Entries; j/k move.
    page.keyboard.press("Escape")
    expect(page.get_by_role("listitem").last).to_be_focused()
    page.keyboard.press("k")
    page.keyboard.press("k")
    expect(entry(first)).to_be_focused()
    page.keyboard.press("j")
    expect(entry(second)).to_be_focused()
    page.keyboard.press("k")

    # x completes the selected Task, and the selection stays on it.
    page.keyboard.press("x")
    expect(entry(first)).to_have_attribute("data-state", "completed")
    expect(entry(first).locator(".state-marker")).to_have_text("×")
    expect(entry(first)).to_be_focused()

    # o reopens it.
    page.keyboard.press("o")
    expect(entry(first)).to_have_attribute("data-state", "open")

    # c Cancels the next Task, striking it through.
    page.keyboard.press("j")
    page.keyboard.press("c")
    expect(entry(second)).to_have_attribute("data-state", "cancelled")
    expect(entry(second).locator(".entry-text")).to_have_css(
        "text-decoration-line", "line-through"
    )

    # e edits the selected Entry's text in place; Enter saves it.
    page.keyboard.press("k")
    page.keyboard.press("e")
    editor = page.get_by_label("Edit entry")
    expect(editor).to_be_focused()
    expect(editor).to_have_value(first)
    editor.fill(f"call dad {run}")
    editor.press("Enter")
    expect(entry(f"call dad {run}")).to_be_focused()

    # Delete removes the selected Entry for good, after confirming.
    page.once("dialog", lambda dialog: dialog.accept())
    page.keyboard.press("j")
    page.keyboard.press("j")
    expect(entry(third)).to_be_focused()
    page.keyboard.press("Delete")
    expect(entry(third)).to_have_count(0)

    page.reload()

    expect(entry(f"call dad {run}")).to_have_attribute("data-state", "open")
    expect(entry(second)).to_have_attribute("data-state", "cancelled")
    expect(entry(third)).to_have_count(0)


def test_escape_abandons_an_edit(page: Page):
    text = f"water plants {uuid4().hex[:8]}"
    page.goto("/")
    _log_tasks(page, text)

    page.keyboard.press("Escape")
    page.keyboard.press("e")
    page.get_by_label("Edit entry").fill("something else")
    page.keyboard.press("Escape")

    task = page.get_by_role("listitem").filter(has_text=text)
    expect(task).to_be_focused()
    expect(page.get_by_label("Edit entry")).to_have_count(0)
