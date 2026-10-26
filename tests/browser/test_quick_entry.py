from playwright.sync_api import Page, expect


def test_keyboard_quick_entry_on_todays_daily_log(page: Page, live_server: str):
    page.goto(live_server)
    quick_entry = page.get_by_label("New entry")
    expect(quick_entry).to_be_focused()

    page.keyboard.type("buy milk")
    page.keyboard.press("Enter")

    expect(page.get_by_role("listitem")).to_contain_text(["buy milk"])
    expect(quick_entry).to_have_value("")
    expect(quick_entry).to_be_focused()

    page.reload()

    expect(page.get_by_role("listitem")).to_contain_text(["buy milk"])
