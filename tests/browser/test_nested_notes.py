import re
from uuid import uuid4

from playwright.sync_api import Page, expect

NESTED = re.compile(r"\bentry--nested\b")


def test_a_key_nests_the_selected_note_under_the_task_above_and_another_un_nests_it(
    page: Page,
):
    # The stack's journal outlives test runs, so the Entries need unique text.
    run = uuid4().hex[:8]
    page.goto("/")
    quick_entry = page.get_by_label("New entry")
    for text in [f". dentist {run}", f"- bring card {run}"]:
        quick_entry.fill(text)
        quick_entry.press("Enter")
        expect(quick_entry).to_have_value("")

    note = page.get_by_role("listitem").filter(has_text=f"bring card {run}")
    note.focus()
    page.keyboard.press("Tab")

    expect(note).to_have_class(NESTED)
    expect(note).to_be_focused()

    page.reload()
    expect(note).to_have_class(NESTED)

    note.focus()
    page.keyboard.press("Shift+Tab")

    expect(note).not_to_have_class(NESTED)
