"""Browser tests for DFR Trigger UI shell geometry and interactions."""
from playwright.sync_api import Page, expect


def test_navigation_expands_and_moves_panel(page: Page, live_server_url: str):
    page.goto(live_server_url)
    rail = page.locator("#nav-rail")
    panel = page.locator("#functional-panel")
    expect(rail).to_have_css("width", "49px")
    collapsed_left = panel.bounding_box()["x"]
    page.get_by_role("button", name="Expand navigation").click()
    expect(rail).to_have_css("width", "131px")
    expect(page.get_by_text("Configuration", exact=True)).to_be_visible()
    assert panel.bounding_box()["x"] == collapsed_left + 82


def test_map_click_populates_coordinates(page: Page, live_server_url: str):
    page.goto(live_server_url)
    page.locator("#map").click(position={"x": 400, "y": 300})
    expect(page.locator("#latitude")).not_to_have_value("")
    expect(page.locator("#longitude")).not_to_have_value("")


def test_dispatch_defaults_and_optional_fields(page: Page, live_server_url: str):
    page.goto(live_server_url)
    expect(page.locator("#priority")).to_have_value("5")
    expect(page.locator("#incident-type")).to_be_visible()
    expect(page.locator("#description")).to_be_visible()
    page.locator("#incident-type").select_option("Other")
    expect(page.locator("#custom-incident-type")).to_be_visible()


def test_configuration_never_renders_saved_token(page: Page, live_server_url: str):
    page.goto(live_server_url)
    page.get_by_role("button", name="Configuration").click()
    expect(page.locator("#token-status")).to_contain_text("Configured")
    expect(page.locator("#user-token")).to_have_value("")


def test_single_click_locks_dispatch_button(page: Page, live_server_url: str):
    page.goto(live_server_url)
    page.locator("#latitude").fill("48.8566")
    page.locator("#longitude").fill("2.3522")
    page.get_by_role("button", name="Dispatch", exact=True).click()
    expect(page.get_by_role("button", name="Dispatching")).to_be_disabled()
