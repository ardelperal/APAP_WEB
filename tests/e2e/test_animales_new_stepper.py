"""E2E: stepper wizard on the animales create flow (issue #823).

Pins the create-branch contract of ``app/templates/animales/form.html``
(5 fieldsets + stepper list, gate ``form_action == '/animales' and not error``)
and the edit-branch contract (no stepper markup). Same auth + skip
semantics as ``tests/e2e/test_stepper_component.py``: ``/e2e/login``
via ``APAP_E2E_AUTH_SECRET``; the suite SKIPs when the secret is unset.
The wizard gate keeps the wizard off the edit-error rerender (the
upstream ``_render_animal_form_error`` hardcodes ``form_action="/animales``
for both create and edit error paths); that branch is exercised
implicitly by ``test_edit_has_no_stepper`` so we don't spawn a
duplicate-chip request to keep the suite hermetic.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from playwright.sync_api import BrowserContext, Page

# Sentinel header name shared with app.core.e2e_auth. Duplicated here
# on purpose: tests/e2e/ does not import from app.core to keep the
# Playwright suite transport-agnostic (same convention as
# test_stepper_component.py and test_nav_rail.py).
E2E_SECRET_HEADER = "X-E2E-Secret"
NEW_PATH = "/animales/new"
SPECIES_CANINA = "CANINA"
SEX_MACHO = "M"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def rendered_create(page: Page) -> Page:
    """Render the production template and assets without an auth server."""
    environment = Environment(
        loader=ChoiceLoader(
            [
                DictLoader({"test_base.html": "{% block content %}{% endblock %}"}),
                FileSystemLoader(ROOT / "app/templates"),
            ]
        ),
        autoescape=True,
    )
    html = environment.get_template("animales/form.html").render(
        base_template="test_base.html",
        form_action="/animales",
        form_data={},
        csrf_token="test-csrf-token",
        especies=[SPECIES_CANINA],
        sexos=[SEX_MACHO],
        error=None,
    )
    page.set_content(html)
    page.add_style_tag(path=str(ROOT / "app/static/css/output.css"))
    page.add_script_tag(path=str(ROOT / "app/static/js/form-stepper.js"))
    return page


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or ``None`` if unset."""
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_page(browser_context: BrowserContext, base_url: str) -> Page:
    """A Page with a valid developer session, skipping when auth is unavailable.

    Same flow as ``tests/e2e/test_stepper_component.py::devtools_page``:
    mint a session through the E2E mock, then open a fresh Page bound
    to the same context so cookies are carried.
    """
    secret = _e2e_secret()
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

    return browser_context.new_page()


def _goto_new(page: Page, base_url: str) -> None:
    """Navigate to ``GET /animales/new`` and assert 200."""
    response = page.goto(f"{base_url}{NEW_PATH}", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200, f"{NEW_PATH} must return 200, got {response.status}"


def _create_animal_for_edit(page: Page, base_url: str) -> str:
    """Create through the browser before checking the real edit form."""
    _goto_new(page, base_url)
    page.fill("#NCHIP", uuid.uuid4().hex[:15])
    page.fill("#NombreAnimal", "Test-stepper-edit")
    page.fill("#FNacimiento", "2024-01-15")
    page.click("[data-step-next]")
    page.click("[data-step-next]")
    page.fill("#TraeNChip", "Si")
    page.fill("#FIMPLANTACIONCHIP", "2024-01-16")
    page.click("[data-step-next]")
    page.fill("#Terapia", "No")
    page.fill("#NombreFoto", "photo.jpg")
    page.click("[data-step-next]")
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.click("[data-step-submit]")
    assert page.url.startswith(f"{base_url}/animales/")
    return page.url.rsplit("/", 1)[-1]


@pytest.mark.parametrize("width,columns", [(375, 1), (1440, 2)])
def test_create_five_step_sidebar_layout(
    rendered_create: Page, width: int, columns: int
) -> None:
    """The five-step navigation sits above the form on mobile, beside it on desktop."""
    page = rendered_create
    page.set_viewport_size({"width": width, "height": 900})
    layout = page.locator(".animal-wizard-layout")
    assert layout.count() == 1
    assert layout.evaluate("node => getComputedStyle(node).display") == "grid"
    tracks = layout.evaluate(
        "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
    )
    assert tracks == columns
    assert page.locator("[data-stepper-list] [data-step]").count() == 5
    assert page.locator('[data-step-panel="5"]').get_by_text(
        "Revisión y envío"
    ).count() == 1


def test_next_and_final_submit_recheck_required_fields(rendered_create: Page) -> None:
    """A stale early-step value cannot bypass validation at final review."""
    page = rendered_create
    next_button = page.locator("[data-step-next]")
    assert next_button.is_disabled()
    page.locator("#NCHIP").fill(uuid.uuid4().hex[:15])
    page.locator("#NombreAnimal").fill("Test wizard")
    page.locator("#FNacimiento").fill("2024-01-15")
    assert next_button.is_enabled()
    next_button.click()
    next_button.click()
    page.locator("#TraeNChip").fill("Si")
    page.locator("#FIMPLANTACIONCHIP").fill("2024-01-16")
    next_button.click()
    page.locator("#Terapia").fill("No")
    page.locator("#NombreFoto").fill("photo.jpg")
    next_button.click()
    assert page.locator('[data-step-panel="5"]').is_visible()
    page.locator("#NCHIP").evaluate("node => node.value = ''")
    page.locator("[data-step-submit]").click()
    assert page.locator('[data-step-panel="1"]').is_visible()
    assert page.locator("#NCHIP").get_attribute("aria-invalid") == "true"


def test_create_five_step_form_accessible_with_axe(rendered_create: Page) -> None:
    """Audit all five visible create panels, not only the initial view."""
    axe_path = os.environ.get("APAP_E2E_AXE_PATH")
    if not axe_path:
        pytest.skip("APAP_E2E_AXE_PATH not set — local axe-core asset unavailable")
    page = rendered_create
    page.add_script_tag(path=axe_path)
    next_button = page.locator("[data-step-next]")

    for step in range(1, 6):
        assert page.locator(f'[data-step-panel="{step}"]').is_visible()
        violations = page.evaluate(
            """async () => (await axe.run(document.querySelector('form[data-stepper]'),
            {runOnly: {type: 'tag',
            values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"""
        )
        assert not violations, f"Step {step}: {violations}"
        if step == 1:
            page.locator("#NCHIP").fill(uuid.uuid4().hex[:15])
            page.locator("#NombreAnimal").fill("Test wizard")
            page.locator("#FNacimiento").fill("2024-01-15")
        elif step == 3:
            page.locator("#TraeNChip").fill("Si")
            page.locator("#FIMPLANTACIONCHIP").fill("2024-01-16")
        elif step == 4:
            page.locator("#Terapia").fill("No")
            page.locator("#NombreFoto").fill("photo.jpg")
        if step < 5:
            next_button.click()


# 1. create renders the wizard
def test_create_renders_five_steps(
    authenticated_page: Page, base_url: str
) -> None:
    """``GET /animales/new`` carries the wizard contract (5 steps, panel 1 visible).

    Pins the create branch of the gate: form has ``data-stepper="true"``,
    list renders exactly 5 ``li[data-step]`` with ``.stepper-label[id]``
    for a11y, 5 ``[data-step-panel]`` fieldsets (only panel 1 visible),
    submit starts hidden.
    """
    page = authenticated_page
    _goto_new(page, base_url)

    assert page.locator('form[data-stepper="true"]').count() == 1, (
        "the create form must carry exactly one data-stepper form"
    )
    assert page.locator('form[data-step-current="1"]').count() == 1, (
        "the create form must start at step 1"
    )

    items = page.locator("[data-stepper-list] [data-step]")
    items.first.wait_for(state="attached")
    assert items.count() == 5, "the stepper list must render exactly 5 steps"
    for step in range(1, 6):
        label = page.locator(
            f'[data-stepper-list] [data-step="{step}"] .stepper-label'
        )
        assert label.count() == 1, (
            f"step {step} must carry exactly one .stepper-label child"
        )
        assert label.first.get_attribute("id"), (
            f"step {step} .stepper-label must have an id for aria-labelledby"
        )

    panels = page.locator("[data-step-panel]")
    assert panels.count() == 5, "the form must render exactly 5 fieldsets"
    review = page.locator('[data-step-panel="5"]')
    assert "Revisión y envío" in review.inner_text()
    assert review.locator("input, select, textarea").count() == 0, (
        "review must not duplicate editable fields or their submitted values"
    )
    assert page.locator('[data-step-panel="1"]').is_visible(), (
        "panel 1 must be visible by default"
    )
    for step in range(2, 6):
        assert not page.locator(f'[data-step-panel="{step}"]').is_visible(), (
            f"panel {step} must start hidden"
        )

    submit = page.locator("[data-step-nav] [data-step-submit]")
    assert submit.count() == 1, "the nav must carry exactly one submit button"
    assert not submit.is_visible(), "submit must start hidden on step 1"

    # The vanilla-JS controller initialises from data-stepper on
    # DOMContentLoaded; the visible list entry carries aria-current.
    page.wait_for_selector(
        '[data-stepper-list] [data-step="1"][aria-current="step"]'
    )


# 2. edit renders without the wizard
def test_edit_has_no_stepper(
    authenticated_page: Page, base_url: str
) -> None:
    """``GET /animales/{id}/edit`` renders the original flat layout.

    Creates an animal first (to obtain a real id) and then visits the
    edit page. The wizard gate ``form_action == '/animales'`` is false
    on the edit path (the edit form_action is ``/animales/{id}/update``)
    so the wizard branch is skipped and the original flat markup
    renders — same as before this slice.
    """
    page = authenticated_page
    animal_id = _create_animal_for_edit(page, base_url)
    assert animal_id, "setup must return a non-empty animal id"

    edit_response = page.goto(
        f"{base_url}/animales/{animal_id}/edit", wait_until="domcontentloaded"
    )
    assert edit_response is not None
    assert edit_response.status == 200, (
        f"/animales/{animal_id}/edit must return 200, got {edit_response.status}"
    )

    assert page.locator('form[data-stepper="true"]').count() == 0, (
        "the edit form must NOT carry data-stepper (gate is false on edit)"
    )
    assert page.locator("[data-stepper-list]").count() == 0, (
        "the edit form must NOT carry the stepper list"
    )
    assert page.locator("[data-step-panel]").count() == 0, (
        "the edit form must NOT carry any stepper fieldsets"
    )
    assert page.locator("[data-step-nav]").count() == 0, (
        "the edit form must NOT carry the stepper nav"
    )
    assert page.locator('script[src*="form-stepper.js"]').count() == 0, (
        "the edit page must NOT load form-stepper.js (wizard is off)"
    )

    # The original single-submit footer stays visible (the JS does
    # not gate the edit form).
    edit_form = page.locator(f'form[action="/animales/{animal_id}/update"]')
    assert edit_form.count() == 1
    submit = edit_form.locator('button[type="submit"]')
    assert submit.is_visible(), (
        "edit form must keep the original submit button visible"
    )
    assert "Guardar" in (submit.inner_text() or ""), (
        "edit form submit must keep the 'Guardar' label"
    )

    # Form action points at the update endpoint, not the create one.
    action = edit_form.get_attribute("action") or ""
    assert action == f"/animales/{animal_id}/update", (
        f"edit form action must be /animales/{{id}}/update, got {action!r}"
    )


# 3. step-1 required gate blocks advance
def test_step1_required_blocks_advance(
    authenticated_page: Page, base_url: str
) -> None:
    """Empty required fields disable ``Siguiente`` before navigation.

    Pins the validate JSON contract on the create form: step 1
    requires ``#NCHIP, #NombreAnimal, #Especie, #Sexo, #FNacimiento``.
    An empty step 1 must not offer an advance action.
    """
    page = authenticated_page
    _goto_new(page, base_url)
    page.wait_for_selector('[data-stepper-list] [data-step="1"][aria-current="step"]')

    assert page.locator("[data-step-nav] [data-step-next]").is_disabled()

    assert page.locator('[data-step-panel="1"]').is_visible(), (
        "must stay on step 1 when required fields are empty"
    )
    assert not page.locator('[data-step-panel="2"]').is_visible(), (
        "must NOT advance to step 2 when required fields are empty"
    )



# 4. data preserved across steps
def test_data_preserved_across_steps(
    authenticated_page: Page, base_url: str
) -> None:
    """Filling step 1, advancing to step 2, then Anterior preserves step-1 values.

    The stepper controller only toggles ``[hidden]`` on the fieldsets;
    it does not destroy or reset inputs. Going back to step 1 must
    therefore show the filled values untouched.
    """
    page = authenticated_page
    _goto_new(page, base_url)

    page.fill("#NCHIP", "1234567890ABCDE")
    page.fill("#NombreAnimal", "Rocín")
    page.select_option("#Especie", SPECIES_CANINA)
    page.select_option("#Sexo", SEX_MACHO)
    page.fill("#FNacimiento", "2024-01-15")

    page.click("[data-step-nav] [data-step-next]")
    page.wait_for_selector('[data-step-panel="2"]', state="visible")
    assert not page.locator('[data-step-panel="1"]').is_visible(), (
        "panel 1 must be hidden after advancing to step 2"
    )

    page.click("[data-step-nav] [data-step-prev]")
    page.wait_for_selector('[data-step-panel="1"]', state="visible")
    assert not page.locator('[data-step-panel="2"]').is_visible(), (
        "panel 2 must be hidden after going back to step 1"
    )

    assert page.locator("#NCHIP").input_value() == "1234567890ABCDE", (
        "NCHIP must be preserved when stepping back"
    )
    assert page.locator("#NombreAnimal").input_value() == "Rocín", (
        "NombreAnimal must be preserved when stepping back"
    )
    assert page.locator("#FNacimiento").input_value() == "2024-01-15", (
        "FNacimiento must be preserved when stepping back"
    )
    reached_step = page.locator('[data-stepper-list] [data-step="2"]')
    assert reached_step.get_attribute("role") == "button"
    reached_step.press("Enter")
    assert page.locator('[data-step-panel="2"]').is_visible()


# 5. submit posts all fields to /animales
def test_submit_posts_all_fields_to_animales(
    authenticated_page: Page, base_url: str
) -> None:
    """Reaching step 5 and clicking ``Guardar`` POSTs the create payload.

    Fills every required field across the five steps, advances to
    step 5, then asserts the submit click triggers a POST to
    ``/animales`` carrying the CSRF token and the required field
    names (``NCHIP``, ``NombreAnimal``, ``Especie``, ``Sexo``,
    ``FNacimiento``, ``TraeNChip``, ``FIMPLANTACIONCHIP``,
    ``Terapia``, ``NombreFoto``). Because the wizard ``<form>`` keeps
    ``action="/animales"`` and the submit button is a plain
    ``type="submit"``, Playwright's ``expect_request`` captures the
    network call produced by the actual form submission (not a
    manually constructed POST).
    """
    page = authenticated_page
    _goto_new(page, base_url)

    # Step 1 — Identificación (required for advance + for submit).
    page.fill("#NCHIP", uuid.uuid4().hex[:15])
    page.fill("#NombreAnimal", "Rocín")
    page.select_option("#Especie", SPECIES_CANINA)
    page.select_option("#Sexo", SEX_MACHO)
    page.fill("#FNacimiento", "2024-01-15")
    page.fill("#Raza", "Mestizo")
    page.click("[data-step-nav] [data-step-next]")
    page.wait_for_selector('[data-step-panel="2"]', state="visible")

    # Step 2 — Características (no required rule, just advance).
    page.fill("#Color", "Negro")
    page.fill("#Pelo", "Corto")
    page.fill("#Tamano", "Mediano")
    page.fill("#Caracter", "Tranquilo")
    page.fill("#Mestizo", "Si")
    page.fill("#RazaPPP", "No")
    page.click("[data-step-nav] [data-step-next]")
    page.wait_for_selector('[data-step-panel="3"]', state="visible")

    # Step 3 — Chip y documentación (required for advance).
    page.fill("#TraeNChip", "Si")
    page.fill("#FIMPLANTACIONCHIP", "2024-01-16")
    page.fill("#Cartilla", "Cart-001")
    page.fill("#ComunicacionARIAC", "ARIAC-001")
    page.click("[data-step-nav] [data-step-next]")
    page.wait_for_selector('[data-step-panel="4"]', state="visible")

    # Step 4 — Salud y situación (required for advance).
    page.fill("#Terapia", "No")
    page.fill("#NombreFoto", "foto-rocin.jpg")
    page.fill("#Eutanasia", "No")
    page.fill("#Observaciones", "Animal sano, sin incidencias.")
    page.click("[data-step-nav] [data-step-next]")
    page.wait_for_selector('[data-step-panel="5"]', state="visible")

    submit = page.locator("[data-step-nav] [data-step-submit]")
    assert submit.is_visible(), "submit must be visible on the last step"
    assert submit.is_enabled(), "submit must be enabled on the last step"

    with page.expect_navigation(wait_until="domcontentloaded") as navigation_info:
        with page.expect_request(
            lambda req: req.method == "POST"
            and req.url.rstrip("/").endswith("/animales"),
        ) as request_info:
            page.click("[data-step-nav] [data-step-submit]")

    captured = request_info.value
    assert captured.method == "POST", f"submit must POST, got {captured.method}"
    body = captured.post_data or ""
    assert "csrf_token=" in body, (
        f"submit must carry the csrf_token, got body excerpt: {body[:300]!r}"
    )
    for required_field in (
        "NCHIP=",
        "NombreAnimal=",
        "Especie=CANINA",
        "Sexo=M",
        "FNacimiento=2024-01-15",
        "TraeNChip=",
        "FIMPLANTACIONCHIP=2024-01-16",
        "Terapia=",
        "NombreFoto=",
    ):
        assert required_field in body, (
            f"submit body must carry {required_field!r}; got body excerpt: "
            f"{body[:300]!r}"
        )
    navigation = navigation_info.value
    assert navigation is not None and navigation.status == 200
    assert page.url.startswith(f"{base_url}/animales/")
    assert not page.url.endswith(NEW_PATH)
