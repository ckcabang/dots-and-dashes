from playwright.sync_api import Page, expect


def test_logging_in_opens_todays_daily_log_and_logging_out_ends_it(
    page: Page, base_url: str, user: str, password: str
):
    page.context.clear_cookies()

    page.goto("/")
    expect(page).to_have_url(f"{base_url}/login")
    expect(page.get_by_label("Email")).to_be_focused()
    page.keyboard.type(user)
    page.keyboard.press("Tab")
    page.keyboard.type(password)
    page.keyboard.press("Enter")

    expect(page).to_have_url(f"{base_url}/")
    expect(page.get_by_label("New entry")).to_be_focused()

    # Enter, not a click: clicks time out under headless Chromium here.
    page.get_by_role("button", name="Log out").press("Enter")

    expect(page).to_have_url(f"{base_url}/login")
    page.goto("/")
    expect(page).to_have_url(f"{base_url}/login")


def test_the_local_user_the_readme_documents_logs_in_on_the_compose_stack(
    page: Page, base_url: str
):
    # The test stack is docker-compose.yml, which creates this User on startup.
    page.context.clear_cookies()

    page.goto("/login")
    page.get_by_label("Email").fill("me@example.com")
    page.get_by_label("Password").fill("dots-and-dashes")
    page.get_by_label("Password").press("Enter")

    expect(page).to_have_url(f"{base_url}/")
    expect(page.get_by_label("New entry")).to_be_focused()


def test_a_wrong_password_is_refused_on_the_login_page(page: Page, base_url: str, user: str):
    page.context.clear_cookies()

    page.goto("/login")
    page.get_by_label("Email").fill(user)
    page.get_by_label("Password").fill("wrong password")
    page.get_by_label("Password").press("Enter")

    expect(page.get_by_role("alert")).to_have_text("That email and password don't match.")
    expect(page).to_have_url(f"{base_url}/login")
