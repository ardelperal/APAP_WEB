"""E2E: stepper wizard on the entradas batch create flow (issue #824).

Pins the create-branch contract of ``app/templates/entradas/batch_new.html``
(3 stepper panels + stepper list, gate ``{% if not error %}``) and the
422/error-branch contract (flat markup, no stepper). Same auth + skip
semantics as ``tests/e2e/test_stepper_component.py`` and
``tests/e2e/test_animales_new_stepper.py``: ``/e2e/login`` via
``APAP_E2E_AUTH_SECRET``; the suite SKIPs when the secret is unset.

The batch form has five fixed rows sharing the same input ``name`` (and
``id``) attributes across rows — a list-form pattern — so the stepper
controller's panel-scoped selector must validate every match (the JS
loops over ``querySelectorAll`` results). The data-step-validate JSON
here pins that contract: panel 1 covers all five rows' ``animal_id`` and
``fecha_entrada`` inputs.

Five cases pin the wizard contract:

- 3-step markup with row fieldsets distributed per panel (create branch).
- Error rerender: no data-stepper markup, flat layout, error visible.
- Step 1 required gate blocks advance until every row has both
  ``animal_id`` and ``fecha_entrada`` filled (mirrors HTML5 ``required``
  semantics; the route's "leave a row empty to discard" UX is a
  pre-existing constraint of the ``required`` attribute, not of the
  wizard — see ``odd/tasks/ui-824-stepper-batch.md`` evidence).
- Data preserved when stepping back to step 1.
- Live POST to ``/entradas/batch`` with csrf + every row's fields
  (reuses ``tests/e2e/test_entradas_batch.py``'s animal-host fixture
  pattern, which creates five animals up front via ``POST /animales``
  so the staged batch references real rows).
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from playwright.sync_api import BrowserContext, Page

# Sentinel header name shared with app.core.e2e_auth. Duplicated here
# on purpose: tests/e2e/ does not import from app.core to keep the
# Playwright suite transport-agnostic (same convention as
# test_animales_new_stepper.py and test_stepper_component.py).
E2E_SECRET_HEADER = "X-E2E-Secret"
NEW_PATH = "/entradas/batch/new"
POST_PATH = "/entradas/batch"
# Five fixed rows; matches ``_build_initial_rows(5)`` in
# ``app/modules/entradas/batch_routes.py``.
EXPECTED_INITIAL_ROWS = 5

ROOT = Path(__file__).resolve().parents[2]


def _blank_rows(count: int = EXPECTED_INITIAL_ROWS) -> list[dict[str, str]]:
    """Return ``count`` blank rows for the form template (create branch)."""
    return [
        {
            "animal_id": "",
            "voluntario_entrada_id": "",
            "fecha_entrada": "",
            "origen": "",
            "motivo": "",
            "observaciones": "",
        }
        for _ in range(count)
    ]


@pytest.fixture
def rendered_create(page: Page) -> Page:
    """Render the production template + assets without an auth server.

    Mirrors ``tests/e2e/test_animales_new_stepper.py::rendered_create``:
    ChoiceLoader for ``test_base.html`` (DictLoader) + the real
    ``app/templates`` tree (FileSystemLoader), then ``page.set_content``
    + ``add_style_tag`` + ``add_script_tag`` so the form-stepper
    controller runs against the rendered wizard markup.
    """
    environment = Environment(
        loader=ChoiceLoader(
            [
                DictLoader({"test_base.html": "{% block content %}{% endblock %}"}),
                FileSystemLoader(ROOT / "app/templates"),
            ]
        ),
        autoescape=True,
    )
    html = environment.get_template("entradas/batch_new.html").render(
        base_template="test_base.html",
        csrf_token="test-csrf-token",
        rows=_blank_rows(),
        error=None,
    )
    page.set_content(html)
    page.add_style_tag(path=str(ROOT / "app/static/css/output.css"))
    page.add_script_tag(path=str(ROOT / "app/static/js/form-stepper.js"))
    return page


@pytest.fixture
def rendered_error(page: Page) -> Page:
    """Render the production template on the 422/error branch.

    Same render technique as ``rendered_create`` but with a non-empty
    ``error`` so the template renders the original flat layout (the
    ``{% if not error %}`` gate skips the wizard markup).
    """
    environment = Environment(
        loader=ChoiceLoader(
            [
                DictLoader({"test_base.html": "{% block content %}{% endblock %}"}),
                FileSystemLoader(ROOT / "app/templates"),
            ]
        ),
        autoescape=True,
    )
    html = environment.get_template("entradas/batch_new.html").render(
        base_template="test_base.html",
        csrf_token="test-csrf-token",
        rows=_blank_rows(),
        error="Animal duplicado en el lote",
    )
    page.set_content(html)
    page.add_style_tag(path=str(ROOT / "app/static/css/output.css"))
    return page


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or ``None`` if unset."""
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_page(browser_context: BrowserContext, base_url: str) -> Page:
    """A Page with a valid developer session, skipping when auth is unavailable.

    Same flow as ``tests/e2e/test_animales_new_stepper.py::authenticated_page``
    and ``tests/e2e/test_stepper_component.py``: mint a session through
    the E2E mock, then open a fresh Page bound to the same context so
    cookies are carried.
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
    """Navigate to ``GET /entradas/batch/new`` and assert 200."""
    response = page.goto(f"{base_url}{NEW_PATH}", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200, f"{NEW_PATH} must return 200, got {response.status}"


def _create_host_animals(page: Page, base_url: str) -> list[str]:
    """Create five unique animals via ``POST /animales`` and return their UUIDs.

    Same pattern as ``tests/e2e/test_entradas_batch.py::batch_animal_ids``:
    the batch service's ``_validate_references`` rejects any
    ``animal_id`` that does not reference an existing animal row, so
    staging a valid batch end-to-end requires five host animals up
    front. If any of the five creates fails (test DB not writable
    from E2E), skip with a descriptive reason.
    """
    ids: list[str] = []
    # ``/e2e/login`` returns the csrf_token in its JSON payload; capture it
    # so the form-encoded POSTs below carry a valid token.
    preflight = page.context.request.get(f"{base_url}/e2e/login")
    csrf_token = ""
    if preflight.status == 200:
        csrf_token = (preflight.json() or {}).get("csrf_token", "")

    for index in range(EXPECTED_INITIAL_ROWS):
        chip = uuid.uuid4().hex[:15]
        form_data = {
            "csrf_token": csrf_token,
            "NCHIP": chip,
            "NombreAnimal": f"BatchStepper-{index}-{uuid.uuid4().hex[:8]}",
            "Especie": "CANINA",
            "Sexo": "M",
            "FNacimiento": "2024-01-15",
            "TraeNChip": "Si",
            "FIMPLANTACIONCHIP": "2024-01-16",
            "NombreFoto": "",
            "Terapia": "No",
        }
        # POST directly to /animales (the animales form template uses
        # ``action=""`` which resolves to the document URL, not to the
        # actual POST endpoint; bypassing the form mirrors the
        # unit-test pattern in tests/test_animals_routes.py and the
        # sibling test_entradas_batch.py::batch_animal_ids fixture).
        response = page.request.post(f"{base_url}/animales", form=form_data)
        if response.status != 303:
            pytest.skip(
                f"Could not create host animal #{index + 1} for the "
                f"batch-stepper test (POST /animales did not return 303; "
                f"got {response.status}: {response.text()[:200]!r}). The "
                f"test database may not be writable from E2E."
            )
        animal_id = response.headers.get("location", "").rsplit("/", 1)[-1]
        if not animal_id or animal_id.endswith("/new") or animal_id.endswith("/edit"):
            pytest.skip(
                f"Could not create host animal #{index + 1} for the "
                f"batch-stepper test (unexpected redirect target "
                f"{response.headers.get('location')!r})."
            )
        ids.append(animal_id)
    return ids


# --- 1. create renders 3 steps with row fieldsets per panel ----------------


def test_render_three_steps(rendered_create: Page) -> None:
    """The create branch renders 3 stepper panels with rows distributed per step.

    Pins the markup contract:
    - form carries ``data-stepper="true"`` + ``data-step-current="1"``
    - stepper list has 3 ``[data-step]`` items with ``.stepper-label[id]``
    - 3 fieldsets with ``data-step-panel="1|2|3"``
    - panel 1 is visible; panels 2-3 start hidden
    - the data-step-nav submit button starts hidden (and keeps the
      original "Previsualizar lote" label)
    - panel 1 contains 5 ``animal_id`` and 5 ``fecha_entrada`` inputs
      (one per row); panel 2 contains the four optional fields per row
    """
    page = rendered_create

    assert page.locator('form[data-stepper="true"]').count() == 1, (
        "the create form must carry exactly one data-stepper form"
    )
    assert page.locator('form[data-step-current="1"]').count() == 1, (
        "the create form must start at step 1"
    )

    items = page.locator("[data-stepper-list] [data-step]")
    items.first.wait_for(state="attached")
    assert items.count() == 3, "the stepper list must render exactly 3 steps"
    for step in range(1, 4):
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
    assert panels.count() == 3, "the form must render exactly 3 stepper panels"
    assert page.locator('[data-step-panel="1"]').is_visible(), (
        "panel 1 must be visible by default"
    )
    assert not page.locator('[data-step-panel="2"]').is_visible(), (
        "panel 2 must start hidden"
    )
    assert not page.locator('[data-step-panel="3"]').is_visible(), (
        "panel 3 must start hidden"
    )

    submit = page.locator("[data-step-nav] [data-step-submit]")
    assert submit.count() == 1, "the nav must carry exactly one submit button"
    assert not submit.is_visible(), "submit must start hidden on step 1"
    assert "Previsualizar lote" in (submit.inner_text() or ""), (
        "submit must keep the 'Previsualizar lote' label"
    )

    # Panel 1: 5 animal_id + 5 fecha_entrada inputs (one per row). The
    # rows share name/id attributes across rows, so we count by name
    # within the panel scope.
    panel1 = page.locator('[data-step-panel="1"]')
    assert panel1.locator('input[name="animal_id"]').count() == EXPECTED_INITIAL_ROWS, (
        f"panel 1 must render {EXPECTED_INITIAL_ROWS} animal_id inputs "
        f"(one per row)"
    )
    assert panel1.locator('input[name="fecha_entrada"]').count() == EXPECTED_INITIAL_ROWS, (
        f"panel 1 must render {EXPECTED_INITIAL_ROWS} fecha_entrada "
        f"inputs (one per row)"
    )

    # Panel 2: 5 rows × 4 optional inputs each.
    panel2 = page.locator('[data-step-panel="2"]')
    for field in ("voluntario_entrada_id", "origen", "motivo", "observaciones"):
        assert panel2.locator(f'[name="{field}"]').count() == EXPECTED_INITIAL_ROWS, (
            f"panel 2 must render {EXPECTED_INITIAL_ROWS} {field} "
            f"inputs (one per row)"
        )

    # Panel 3: review summary only — no editable inputs.
    panel3 = page.locator('[data-step-panel="3"]')
    assert panel3.locator("input, select, textarea").count() == 0, (
        "review panel must not duplicate editable fields or their values"
    )
    assert "Revisión y previsualización" in panel3.inner_text(), (
        "review panel must show its legend"
    )

    # The vanilla-JS controller initialises from data-stepper on
    # DOMContentLoaded; the visible list entry carries aria-current.
    page.wait_for_selector(
        '[data-stepper-list] [data-step="1"][aria-current="step"]'
    )


# --- 2. error branch renders flat layout ---------------------------------


def test_error_branch_renders_flat(rendered_error: Page) -> None:
    """A non-empty ``error`` context renders the original flat layout.

    Pins the gate contract: ``{% if not error %}`` skips the wizard
    markup on 422 rerenders (BatchValidationError or all-empty
    submission — see ``batch_routes.py::stage_batch_view``). The
    flat layout keeps the original Cancelar link, the
    "Previsualizar lote" submit, the 5 row fieldsets, and renders
    the Spanish error banner above the form.
    """
    page = rendered_error

    assert page.locator('form[data-stepper="true"]').count() == 0, (
        "the error rerender must NOT carry data-stepper (gate is false "
        "when error is set)"
    )
    assert page.locator("[data-stepper-list]").count() == 0, (
        "the error rerender must NOT carry the stepper list"
    )
    assert page.locator("[data-step-panel]").count() == 0, (
        "the error rerender must NOT carry any stepper panels"
    )
    assert page.locator("[data-step-nav]").count() == 0, (
        "the error rerender must NOT carry the stepper nav"
    )
    assert page.locator('script[src*="form-stepper.js"]').count() == 0, (
        "the error rerender must NOT load form-stepper.js (wizard is off)"
    )

    # Error banner is visible with the operator's message.
    body_text = page.content()
    assert "No se pudo previsualizar el lote" in body_text, (
        "the error banner must show the Spanish header"
    )
    assert "Animal duplicado en el lote" in body_text, (
        "the error banner must show the operator's error message"
    )

    # Flat layout: 5 row fieldsets, each with the 6 inputs.
    fieldsets = page.locator("fieldset")
    assert fieldsets.count() == EXPECTED_INITIAL_ROWS, (
        f"the error rerender must render exactly {EXPECTED_INITIAL_ROWS} "
        f"row fieldsets, got {fieldsets.count()}"
    )
    for field in ("animal_id", "fecha_entrada"):
        assert page.locator(f'input[name="{field}"]').count() == EXPECTED_INITIAL_ROWS, (
            f"the error rerender must render {EXPECTED_INITIAL_ROWS} "
            f"{field} inputs"
        )

    # Original submit button is visible (no hidden attribute on it).
    submit = page.locator('button[type="submit"]:has-text("Previsualizar lote")')
    assert submit.count() == 1
    assert submit.is_visible(), (
        "the error rerender must keep the original submit button visible"
    )


# --- 3. step-1 required gate blocks advance -----------------------------


def test_step1_required_blocks_advance(rendered_create: Page) -> None:
    """Empty required fields disable ``Siguiente`` and block advance.

    Pins the data-step-validate JSON contract on the create form:
    step 1 requires every row's ``animal_id`` and ``fecha_entrada``
    (panel-scoped selector). With the controller's ``form.noValidate``
    + whole-form recheck, an empty row blocks ``Siguiente`` until the
    operator fills every required input across the five rows — the
    same constraint the HTML5 ``required`` attribute imposed before
    this slice. See ``odd/tasks/ui-824-stepper-batch.md`` evidence for
    the empty-row semantics decision (route-level discard vs.
    HTML5 required is a pre-existing constraint, not a wizard
    regression).
    """
    page = rendered_create
    next_button = page.locator("[data-step-nav] [data-step-next]")
    assert next_button.is_disabled()

    assert page.locator('[data-step-panel="1"]').is_visible(), (
        "must stay on step 1 when required fields are empty"
    )
    assert not page.locator('[data-step-panel="2"]').is_visible(), (
        "must NOT advance to step 2 when required fields are empty"
    )

    # Filling only one row's required fields is not enough — the
    # selector covers all five rows (panel-scoped), so the other four
    # rows still block advance.
    page.locator('input[name="animal_id"]').nth(0).fill(uuid.uuid4().hex)
    page.locator('input[name="fecha_entrada"]').nth(0).fill("2024-01-15")
    assert next_button.is_disabled(), (
        "Siguiente must stay disabled while ANY row's required fields are empty"
    )

    # Filling every row's required fields enables advance.
    for row in range(EXPECTED_INITIAL_ROWS):
        page.locator('input[name="animal_id"]').nth(row).fill(
            uuid.uuid4().hex + str(row)
        )
        page.locator('input[name="fecha_entrada"]').nth(row).fill("2024-01-15")
    assert next_button.is_enabled(), (
        "Siguiente must enable when ALL rows' required fields are filled"
    )


# --- 4. data preserved across steps --------------------------------------


def test_data_preserved_across_steps(rendered_create: Page) -> None:
    """Filling step 1, advancing to step 2, then Anterior preserves values.

    The stepper controller only toggles ``[hidden]`` on the fieldsets;
    it does not destroy or reset inputs. Going back to step 1 must
    therefore show the filled values untouched.
    """
    page = rendered_create
    next_button = page.locator("[data-step-nav] [data-step-next]")

    # Fill step 1 for every row so the Next button enables.
    for row in range(EXPECTED_INITIAL_ROWS):
        page.locator('input[name="animal_id"]').nth(row).fill(
            f"row-{row}-animal"
        )
        page.locator('input[name="fecha_entrada"]').nth(row).fill("2024-02-01")

    next_button.click()
    page.wait_for_selector('[data-step-panel="2"]', state="visible")
    assert not page.locator('[data-step-panel="1"]').is_visible(), (
        "panel 1 must be hidden after advancing to step 2"
    )

    # Fill step 2 too, then go back to step 1.
    page.locator('input[name="origen"]').nth(0).fill("Test origen")
    page.locator('input[name="motivo"]').nth(0).fill("Test motivo")
    page.locator('textarea[name="observaciones"]').nth(0).fill("Test nota")

    page.click("[data-step-nav] [data-step-prev]")
    page.wait_for_selector('[data-step-panel="1"]', state="visible")
    assert not page.locator('[data-step-panel="2"]').is_visible(), (
        "panel 2 must be hidden after going back to step 1"
    )

    for row in range(EXPECTED_INITIAL_ROWS):
        assert (
            page.locator('input[name="animal_id"]').nth(row).input_value()
            == f"row-{row}-animal"
        ), f"animal_id row {row} must be preserved when stepping back"
        assert (
            page.locator('input[name="fecha_entrada"]').nth(row).input_value()
            == "2024-02-01"
        ), f"fecha_entrada row {row} must be preserved when stepping back"

    # Forward to step 2 — optional fields stay populated.
    next_button.click()
    page.wait_for_selector('[data-step-panel="2"]', state="visible")
    assert (
        page.locator('input[name="origen"]').nth(0).input_value() == "Test origen"
    ), "step-2 optional fields must be preserved when stepping forward"


# --- 5. live submit POSTs all fields to /entradas/batch -------------------


def test_submit_posts_all_fields_to_entradas_batch(
    authenticated_page: Page, base_url: str
) -> None:
    """Reaching step 3 and clicking ``Previsualizar lote`` POSTs the batch.

    Fills every required field across the three steps, advances to
    step 3, then asserts the submit click triggers a POST to
    ``/entradas/batch`` carrying the CSRF token and the row fields
    for all five rows (one POST list-form field per input, five
    values each). The wizard ``<form>`` keeps ``action="/entradas/batch"``
    and the submit button is a plain ``type="submit"``, so
    Playwright's ``expect_request`` captures the network call produced
    by the actual form submission (not a manually constructed POST).
    The test SKIPS cleanly when no host animals are available
    (writeable test DB), so it does not hard-fail on hermetic runs.
    """
    page = authenticated_page
    _goto_new(page, base_url)

    # Pin the wizard contract on the live server: form has data-stepper,
    # 3 stepper items, panels 2-3 hidden, submit hidden.
    assert page.locator('form[data-stepper="true"]').count() == 1
    assert page.locator("[data-stepper-list] [data-step]").count() == 3
    assert not page.locator('[data-step-panel="2"]').is_visible()
    assert not page.locator('[data-step-panel="3"]').is_visible()
    assert not page.locator("[data-step-nav] [data-step-submit]").is_visible()

    # Setup: create five host animals so the staged batch references
    # real rows. Skip cleanly if the test DB is not writable.
    animal_ids = _create_host_animals(page, base_url)
    assert len(animal_ids) == EXPECTED_INITIAL_ROWS, (
        f"setup must create {EXPECTED_INITIAL_ROWS} host animals, got {len(animal_ids)}"
    )

    # Step 1 — Identificación por fila (required for advance).
    base_fecha = date.today()
    origins = [f"Stepper-{i}-{uuid.uuid4().hex[:6]}" for i in range(EXPECTED_INITIAL_ROWS)]
    for row in range(EXPECTED_INITIAL_ROWS):
        page.locator('input[name="animal_id"]').nth(row).fill(animal_ids[row])
        fecha = (base_fecha + timedelta(days=row + 1)).isoformat()
        page.locator('input[name="fecha_entrada"]').nth(row).fill(fecha)
    page.click("[data-step-nav] [data-step-next]")
    page.wait_for_selector('[data-step-panel="2"]', state="visible")

    # Step 2 — Contexto por fila (no required rule, just advance).
    for row in range(EXPECTED_INITIAL_ROWS):
        page.locator('input[name="origen"]').nth(row).fill(origins[row])
        page.locator('input[name="motivo"]').nth(row).fill(f"motivo-{row}")
    page.click("[data-step-nav] [data-step-next]")
    page.wait_for_selector('[data-step-panel="3"]', state="visible")

    # Step 3 — review + submit. The submit button must now be visible
    # and enabled, and carry the original label "Previsualizar lote".
    submit = page.locator("[data-step-nav] [data-step-submit]")
    assert submit.is_visible(), "submit must be visible on the last step"
    assert submit.is_enabled(), "submit must be enabled on the last step"
    assert "Previsualizar lote" in (submit.inner_text() or ""), (
        "submit must keep the 'Previsualizar lote' label"
    )

    # Capture the actual POST produced by clicking submit. We use a
    # response listener (not navigation) so the test stays stable
    # regardless of whether the batch stages successfully (303 to
    # /entradas/batch/{id}) or rerenders the form (422 with error).
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.rstrip("/") == f"{base_url}{POST_PATH}"
    ) as response_info:
        submit.click()
    response = response_info.value
    assert response.request.method == "POST", (
        f"submit must POST, got {response.request.method}"
    )
    body = (response.request.post_data or "")
    assert "csrf_token=" in body, (
        f"submit must carry the csrf_token, got body excerpt: {body[:300]!r}"
    )

    # The body carries every required field per row (5 rows each).
    # We assert the markers rather than full equality to keep the test
    # robust against whitespace/ordering changes in form encoding.
    for row in range(EXPECTED_INITIAL_ROWS):
        assert animal_ids[row] in body, (
            f"submit body must carry animal_id row {row} "
            f"({animal_ids[row]!r}); got body excerpt: {body[:300]!r}"
        )
        fecha = (base_fecha + timedelta(days=row + 1)).isoformat()
        assert fecha in body, (
            f"submit body must carry fecha_entrada row {row} ({fecha!r}); "
            f"got body excerpt: {body[:300]!r}"
        )
    for marker in origins:
        assert marker in body, (
            f"submit body must carry origen marker {marker!r}; "
            f"got body excerpt: {body[:300]!r}"
        )

    # The route either stages the batch (303 to /entradas/batch/{id})
    # or rejects it (422 with a Spanish error rerender). Both are
    # valid observable outcomes — the wizard's job is to deliver the
    # POST with every row's fields; the route decides what happens
    # next. We pin the redirect/rerender contract here, not the
    # stepper markup (already covered by the rendered-form cases).
    assert response.status in (303, 422), (
        f"batch POST must return 303 (success) or 422 (validation), "
        f"got {response.status}"
    )
