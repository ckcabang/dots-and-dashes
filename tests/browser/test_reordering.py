from uuid import uuid4

from playwright.sync_api import Locator, Page, expect


def _log(page: Page, *texts: str) -> None:
    quick_entry = page.get_by_label("New entry")
    for text in texts:
        quick_entry.fill(text)
        quick_entry.press("Enter")
        expect(page.get_by_role("listitem").filter(has_text=text)).to_have_count(1)


def _entries(page: Page, run: str) -> Locator:
    """This run's Entries, in the order the Daily Log shows them."""
    return page.get_by_role("listitem").filter(has_text=run)


def test_an_untimed_entry_reordered_by_keyboard_stays_put_after_a_reload(page: Page):
    # The stack's journal outlives test runs, so the Entries need unique text.
    run = uuid4().hex[:8]
    first, second = f"buy milk {run}", f"call mom {run}"
    page.goto("/")
    _log(page, first, second)

    page.get_by_role("listitem").filter(has_text=second).focus()
    page.keyboard.press("Alt+ArrowUp")

    expect(_entries(page, run)).to_contain_text([second, first])
    expect(page.get_by_role("listitem").filter(has_text=second)).to_be_focused()
    page.reload()
    expect(_entries(page, run)).to_contain_text([second, first])


def test_an_untimed_entry_dragged_below_another_stays_there(page: Page):
    run = uuid4().hex[:8]
    first, second = f"buy milk {run}", f"call mom {run}"
    page.goto("/")
    _log(page, first, second)

    # Dispatch the drag events directly: a synthesised mouse drag waits on
    # animation frames, which headless Chromium here doesn't reliably run.
    entry = page.get_by_role("listitem").filter(has_text=first)
    target = page.get_by_role("listitem").filter(has_text=second)
    box = target.bounding_box()
    assert box is not None
    below = {"clientY": box["y"] + box["height"] - 1}
    data = page.evaluate_handle("new DataTransfer()")
    entry.dispatch_event("dragstart", {"dataTransfer": data})
    target.dispatch_event("dragover", {"dataTransfer": data, **below})
    target.dispatch_event("drop", {"dataTransfer": data, **below})
    entry.dispatch_event("dragend", {"dataTransfer": data})

    expect(_entries(page, run)).to_contain_text([second, first])
    page.reload()
    expect(_entries(page, run)).to_contain_text([second, first])
