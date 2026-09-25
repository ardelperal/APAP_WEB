"""E2E: reusable form stepper component (issue #821).

Exercises the developer-only stepper preview page
(``GET /devtools/stepper-preview``, registered only when
``Settings.devtools_enabled`` is True) and the vanilla-JS controller
``/static/js/form-stepper.js``:

- preview renders 5 steps, step 1 visible, panels 2-5 hidden;
- "Siguiente" stays disabled while the current required field is invalid;
- filling the required field and advancing marks the step complete
  in the list;
- clicking a previously reached step jumps back with fields preserved;
- the submit button is visible only on the last step and the form
  posts to the no-op confirmation handler.

The route lives behind the default-deny auth middleware (NOT in
``PUBLIC_PATHS``), so the suite authenticates through ``/e2e/login``
and SKIPS cleanly whenever the preview is unavailable — 404 means the
devtools flag is off on the target server (production default).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page

# Sentinel header name shared with app.core.e2e_auth. Duplicated here
# on purpose: tests/e2e/ does not import from app.core to keep the
# Playwright suite transport-agnostic (same convention as test_nav_rail.py).
E2E_SECRET_HEADER = "X-E2E-Secret"

PREVIEW_PATH = "/devtools/stepper-preview"
STEPPER_SCRIPT = Path(__file__).resolve().parents[2] / "app/static/js/form-stepper.js"


@pytest.fixture
def component_page(page: Page) -> Page:
    """Exercise the checked-out controller without depending on a dev server."""
    page.set_content(
        '<form data-stepper="true" data-step-current="1" '
        'data-step-validate=\'[ {"step":1,"selector":"#nombre","required":true},'
        '{"step":2,"selector":"#confirmacion","required":true} ]\'>'
        '<ol data-stepper-list><li data-step="1"><span class="stepper-label" '
        'id="label-1">First</span></li><li data-step="2"><span class="stepper-label" '
        'id="label-2">Final</span></li></ol>'
        '<fieldset data-step-panel="1"><input id="nombre" type="text"></fieldset>'
        '<fieldset data-step-panel="2" hidden><input id="confirmacion" type="checkbox">'
        '<select id="especie" required><option value="">Choose species</option>'
        '<option value="caballo">Horse</option></select></fieldset>'
        '<div data-step-nav><button type="button" data-step-prev>Previous</button>'
        '<button type="button" data-step-next>Next</button>'
        '<button type="submit" data-step-submit hidden>Submit</button></div></form>'
    )
    page.add_script_tag(path=str(STEPPER_SCRIPT))
    return page


def test_next_tracks_current_required_field(component_page: Page) -> None:
    page = component_page
    next_button = page.locator("[data-step-next]")
    assert next_button.is_disabled()
    page.fill("#nombre", "Rocín")
    assert next_button.is_enabled()
    page.fill("#nombre", " ")
    assert next_button.is_disabled()
    page.fill("#nombre", "Rocín")
    next_button.click()
    assert page.locator('[data-step-panel="2"]').is_visible()


def test_submit_returns_to_invalid_earlier_step(component_page: Page) -> None:
    page = component_page
    page.fill("#nombre", "Rocín")
    page.locator("[data-step-next]").click()
    page.check("#confirmacion")
    page.locator("#nombre").evaluate("el => el.value = ''")
    page.locator("[data-step-submit]").click()
    assert page.locator('[data-step-panel="1"]').is_visible()
    assert page.locator("#nombre").get_attribute("aria-invalid") == "true"
    assert page.evaluate("document.activeElement.id") == "nombre"


def test_submit_preserves_native_constraint_for_unlisted_control(
    component_page: Page,
) -> None:
    page = component_page
    page.fill("#nombre", "Rocín")
    page.locator("[data-step-next]").click()
    page.check("#confirmacion")
    page.locator("[data-step-submit]").click()
    assert page.locator('[data-step-panel="2"]').is_visible()
    assert page.locator("#especie").get_attribute("aria-invalid") == "true"
    assert page.evaluate("document.activeElement.id") == "especie"


@pytest.fixture
def devtools_page(browser_context: BrowserContext, base_url: str) -> Page:
    """A Page with a valid session, skipping when the preview is unavailable.

    Same flow as ``tests/e2e/test_nav_rail.py::authenticated_page``: mint a
    session through the E2E mock, then run a preflight against the preview
    route. A 404 means the devtools flag is disabled on the server — the
    suite skips instead of failing (production default is off).
    """
    secret = os.environ.get("APAP_E2E_AUTH_SECRET")
    if secret is None:
        pytest.skip(
            "APAP_E2E_AUTH_SECRET not set — the OAuth mock cannot "
            "authenticate this test. CI sets the variable; local dev "
            "needs to export it to run authenticated E2E flows."
        )

    response = browser_context.request.get(
        f"{base_url}/e2e/login",
        headers={E2E_SECRET_HEADER: secret},
    )
    assert response.status == 200, (
        f"/e2e/login must return 200 in the e2e suite, got {response.status}."
    )
    payload = response.json()
    assert payload.get("authenticated") is True, (
        f"/e2e/login must report authenticated: true, got {payload!r}."
    )

    preflight = browser_context.request.get(f"{base_url}{PREVIEW_PATH}")
    if preflight.status == 404:
        pytest.skip(
            f"{PREVIEW_PATH} returns 404 (devtools_enabled is off on the "
            "target server); stepper preview cannot be observed end-to-end."
        )
    assert preflight.status == 200, (
        f"{PREVIEW_PATH} preflight returned {preflight.status}; expected 200."
    )

    page = browser_context.new_page()
    page.goto(f"{base_url}{PREVIEW_PATH}", wait_until="domcontentloaded")
    return page


def test_preview_shows_five_steps_with_only_step_1_visible(
    devtools_page: Page,
) -> None:
    """The preview renders 5 steps; panel 1 visible, panels 2-5 hidden."""
    page = devtools_page
    items = page.locator("[data-stepper-list] [data-step]")
    items.first.wait_for(state="attached")
    assert items.count() == 5, "the stepper list must render exactly 5 steps"

    assert page.locator("#step-1").is_visible(), "panel 1 must be visible"
    for step in range(2, 6):
        assert not page.locator(f"#step-{step}").is_visible(), (
            f"panel {step} must start hidden"
        )

    # The controller decorates the visible step in the list (a11y contract).
    page.wait_for_selector('[data-stepper-list] [data-step="1"][aria-current="step"]')


def test_next_on_empty_step_is_disabled_and_stays(
    devtools_page: Page,
) -> None:
    """Empty required field disables Next and cannot advance."""
    page = devtools_page
    assert page.locator("[data-step-nav] [data-step-next]").is_disabled()

    assert page.locator("#step-1").is_visible(), "must stay on step 1"
    assert not page.locator("#step-2").is_visible(), "must not reach step 2"



def test_fill_required_and_next_advances_and_marks_complete(
    devtools_page: Page,
) -> None:
    """Valid input: "Siguiente" shows step 2 and marks step 1 complete."""
    page = devtools_page
    page.fill("#nombre", "Rocín")
    page.click("[data-step-nav] [data-step-next]")

    page.wait_for_selector("#step-2", state="visible")
    assert not page.locator("#step-1").is_visible(), (
        "panel 1 must be hidden after advancing"
    )

    item_classes = page.locator('[data-stepper-list] [data-step="1"]').get_attribute(
        "class"
    ) or ""
    assert "is-complete" in item_classes, "step 1 must be marked complete"
    page.wait_for_selector(
        '[data-stepper-list] [data-step="2"][aria-current="step"]'
    )


def test_clicking_a_reached_step_jumps_back_with_fields_preserved(
    devtools_page: Page,
) -> None:
    """Clicking step 1 in the list goes back; the filled field is preserved."""
    page = devtools_page
    page.fill("#nombre", "Rocín")
    page.click("[data-step-nav] [data-step-next]")
    page.wait_for_selector("#step-2", state="visible")

    page.click('[data-stepper-list] [data-step="1"]')
    page.wait_for_selector("#step-1", state="visible")
    assert not page.locator("#step-2").is_visible(), "panel 2 must be hidden"

    assert page.locator("#nombre").input_value() == "Rocín", (
        "fields must be preserved when jumping back"
    )


def test_submit_only_on_last_step_and_noop_confirmation(devtools_page: Page) -> None:
    """Submit is gated to the last step; posting renders the confirmation."""
    page = devtools_page
    submit = page.locator("[data-step-nav] [data-step-submit]")
    assert not submit.is_visible(), "submit must start hidden"

    steps_and_fields = {
        1: ("#nombre", "Rocín"),
        2: ("#especie", "caballo"),
        3: ("#origen", "Madrid"),
        4: ("#estado_salud", "Sano"),
    }
    for step, (selector, value) in steps_and_fields.items():
        if selector == "#especie":
            page.select_option(selector, value)
        else:
            page.fill(selector, value)
        page.click("[data-step-nav] [data-step-next]")
        page.wait_for_selector(f"#step-{step + 1}", state="visible")
        if step < 4:
            assert not submit.is_visible(), (
                f"submit must stay hidden on step {step + 1}"
            )

    assert submit.is_visible(), "submit must be visible on the last step"
    assert submit.is_enabled(), "submit must be enabled on the last step"

    page.check("#confirmacion")
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.click("[data-step-nav] [data-step-submit]")

    assert PREVIEW_PATH in page.url, "the form must post to the no-op handler"
    page.wait_for_selector("[data-stepper-submitted]", state="attached")
