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


def test_a_parent_edited_into_a_note_shows_its_nested_notes_standing_alone(page: Page):
    run = uuid4().hex[:8]
    page.goto("/")
    quick_entry = page.get_by_label("New entry")
    for text in [f". dentist {run}", f"- bring card {run}"]:
        quick_entry.fill(text)
        quick_entry.press("Enter")
        expect(quick_entry).to_have_value("")
    parent = page.get_by_role("listitem").filter(has_text=f"dentist {run}")
    note = page.get_by_role("listitem").filter(has_text=f"bring card {run}")
    note.focus()
    page.keyboard.press("Tab")
    expect(note).to_have_class(NESTED)

    parent.first.focus()
    page.keyboard.press("e")
    editor = page.get_by_label("Edit entry")
    editor.fill(f"- dentist was fine {run}")
    editor.press("Enter")

    expect(page.get_by_role("listitem").filter(has_text=f"dentist was fine {run}")).to_be_focused()
    expect(note).not_to_have_class(NESTED)


def test_tab_off_a_daily_log_keeps_its_usual_meaning(page: Page):
    # Notes nest only on a Daily Log, so Tab there moves the focus on as usual.
    run = uuid4().hex[:8]
    page.goto("/future")
    for text in [f". renew passport {run}", f"- photos first {run}"]:
        quick_entry = page.get_by_label("New entry")
        quick_entry.fill(text)
        quick_entry.press("Enter")
        expect(page.get_by_role("listitem").filter(has_text=text[2:])).to_have_count(1)
    note = page.get_by_role("listitem").filter(has_text=f"photos first {run}")
    note.focus()

    page.keyboard.press("Tab")

    expect(note).not_to_be_focused()
    expect(note).not_to_have_class(NESTED)
