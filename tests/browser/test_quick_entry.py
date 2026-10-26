from uuid import uuid4

from playwright.sync_api import Page, expect


def test_keyboard_quick_entry_on_todays_daily_log(page: Page):
    # The stack's journal outlives test runs, so the Task needs unique text.
    text = f"buy milk {uuid4().hex[:8]}"
    page.goto("/")
    quick_entry = page.get_by_label("New entry")
    expect(quick_entry).to_be_focused()

    page.keyboard.type(text)
    page.keyboard.press("Enter")

    new_task = page.get_by_role("listitem").filter(has_text=text)
    expect(new_task).to_have_count(1)
    expect(quick_entry).to_have_value("")
    expect(quick_entry).to_be_focused()

    page.reload()

    expect(new_task).to_have_count(1)
