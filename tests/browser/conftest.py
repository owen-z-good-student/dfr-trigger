import pytest
from playwright.sync_api import sync_playwright


CHROME = (
    "/home/opencode/.cache/ms-playwright/chromium_headless_shell-1228/"
    "chrome-headless-shell-linux64/chrome-headless-shell"
)


@pytest.fixture
def page():
    """Keep Playwright's event loop inside one browser test.

    A session-scoped browser remains alive while backend asyncio tests replace
    ``asyncio.sleep`` for deterministic maintenance checks.  Function scope
    closes Playwright before those monkeypatches run, preventing cross-suite
    event-loop pollution.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=CHROME,
            headless=True,
            args=["--no-sandbox", "--disable-gpu"],
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        yield page
        context.close()
        browser.close()
