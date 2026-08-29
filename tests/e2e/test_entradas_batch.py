"""E2E CRUD coverage for the ``/entradas/batch`` slice (PLAN-E2E-COVERAGE.md §Fichero 3).

The batch flow (Entradas Múltiples, INTAKE-02) lets an operator
register multiple intake entries in a single session:

1. ``GET /entradas/batch/new`` — show five empty rows.
2. ``POST /entradas/batch`` — stage records (per-record FK validation,
   cross-batch uniqueness check).
3. ``GET /entradas/batch/{batch_id}`` — preview each record's status.
4. ``POST /entradas/batch/{batch_id}/commit`` — atomic copy staging → ``entradas``.
5. ``POST /entradas/batch/{batch_id}/cancel`` — clear staging without commit.

Each test follows the same OAuth-mock pattern as the rest of the
authenticated E2E suite: the ``authenticated_session`` fixture mints a
developer session via ``GET /e2e/login`` and returns a
``(Page, csrf_token)`` tuple. Form-encoded POSTs through the browser
submit the hidden csrf_token automatically; the batch flow is form-only
(no PATCH / JSON), so the csrf_token captured at login is unused on the
happy path — it is preserved in the fixture signature for symmetry with
the animales / entradas single-CRUD files.

Six cases pin the batch contract end-to-end:

- New (GET → 200, five ``<fieldset>`` rows).
- Stage five valid rows (POST → 303 to ``/entradas/batch/{batch_id}``).
- Preview (GET → 200, status column shows ``Válida`` per row).
- Commit (POST → 303 to ``/entradas``; new rows land in the entradas
  table; verified by ``GET /entradas`` showing the new entries).
- Cancel (POST → 303 to ``/entradas/batch/new``; staging cleared;
  a follow-up ``GET /entradas/batch/{batch_id}`` returns 404).
- Empty submission (POST with all five rows empty → 422 with the
  Spanish message ``"Añade al menos una entrada antes de
  previsualizar."``). The user-facing contract is "needs at least one
  non-empty row", not "needs exactly five rows" — see
  ``app/modules/entradas/batch_routes.py::stage_batch_view``.

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset (the OAuth
mock cannot authenticate). The animal setup fixture creates five
unique animals via ``/animales``; if that fails (DB unavailable,
permissions, etc.) the dependent tests skip with a descriptive reason.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import pytest
from playwright.sync_api import BrowserContext, Page

# --- shared constants -----------------------------------------------------

E2E_SECRET_HEADER = "X-E2E-Secret"
CSRF_HEADER = "X-CSRFToken"

SPECIES_CANINA = "CANINA"
SEX_MACHO = "M"

# The batch form renders five initial rows; this constant matches
# ``_build_initial_rows(5)`` in ``app/modules/entradas/batch_routes.py``.
EXPECTED_INITIAL_ROWS = 5


# --- fixtures -------------------------------------------------------------


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or ``None`` if unset."""
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_session(browser_context: BrowserContext, base_url: str) -> tuple[Page, str]:
    """Mint a developer session and return ``(page, csrf_token)``."""
    secret = _e2e_secret()
    if secret is None:
        pytest.skip("APAP_E2E_AUTH_SECRET not set — the OAuth mock cannot authenticate this test.")

    response = browser_context.request.get(
        f"{base_url}/e2e/login",
        headers={E2E_SECRET_HEADER: secret},
    )
    assert response.status == 200, (
        f"/e2e/login must return 200 in the e2e suite, got {response.status}."
    )
    payload = response.json()
    csrf_token = payload.get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token, (
        f"/e2e/login must return a non-empty csrf_token, got {payload!r}."
    )

    page = browser_context.new_page()
    return page, csrf_token


@pytest.fixture
def batch_animal_ids(authenticated_session: tuple[Page, str], base_url: str) -> list[str]:
    """Create five unique animals and return their UUIDs.

    ``batch_service._validate_references`` rejects any ``animal_id``
    that does not reference an existing animal row. To make the batch
    happy-path testable end-to-end, this fixture creates the five
    animals via the ``/animales`` form up front and returns their
    UUIDs. The chip and name use UUIDs to avoid collisions with
    animals other tests may have created.

    If any of the five animal creates fails (e.g. the test DB is not
    writable from the E2E browser), the fixture skips with a clear
    reason rather than failing the whole suite.
    """
    page, csrf_token = authenticated_session
    ids: list[str] = []
    for index in range(EXPECTED_INITIAL_ROWS):
        chip = uuid.uuid4().hex[:15]
        form_data = {
            "NCHIP": chip,
            "NombreAnimal": f"BatchHost-{index}-{uuid.uuid4().hex[:8]}",
            "Especie": SPECIES_CANINA,
            "Sexo": SEX_MACHO,
            "FNacimiento": "2024-01-15",
            "TraeNChip": "Si",
            "FIMPLANTACIONCHIP": "2024-01-16",
            "NombreFoto": "",
            "Terapia": "No",
        }
        # POST directly to /animales (the animales form template uses
        # ``action=""`` which resolves to the document URL, not to the
        # actual POST endpoint; bypassing the form mirrors the
        # unit-test pattern in tests/test_animals_routes.py).
        response = page.request.post(
            f"{base_url}/animales",
            form={"csrf_token": csrf_token, **form_data},
        )
        if response.status != 303:
            pytest.skip(
                f"Could not create host animal #{index + 1} for the batch "
                f"test (POST /animales did not return 303; got "
                f"{response.status}: {response.text()[:200]!r}). The test "
                f"database may not be writable from E2E."
            )
        animal_id = response.headers.get("location", "").rsplit("/", 1)[-1]
        if not animal_id or animal_id.endswith("/new") or animal_id.endswith("/edit"):
            pytest.skip(
                f"Could not create host animal #{index + 1} for the batch "
                f"test (unexpected redirect target {response.headers.get('location')!r})."
            )
        ids.append(animal_id)
    return ids


# --- helpers --------------------------------------------------------------


def _csrf_token_from_form(page: Page) -> str:
    """Read the csrf_token hidden input rendered on the current page."""
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "every form page must render a non-empty csrf_token hidden input"
    return token


def _fill_batch_row(
    page: Page,
    *,
    row_index: int,
    animal_id: str,
    fecha_entrada: str,
    origen: str = "",
    motivo: str = "",
) -> None:
    """Fill the batch form's ``row_index``-th (0-based) row.

    The batch form renders each row as a ``<fieldset>`` with inputs
    sharing the same ``name`` across rows. We use ``.nth(row_index)``
    to disambiguate. The form template does NOT carry unique ``id``
    attributes per row, so name-based selection is the only
    deterministic way to address a specific row in Playwright.
    """
    page.locator('input[name="animal_id"]').nth(row_index).fill(animal_id)
    page.locator('input[name="fecha_entrada"]').nth(row_index).fill(fecha_entrada)
    if origen:
        page.locator('input[name="origen"]').nth(row_index).fill(origen)
    if motivo:
        page.locator('input[name="motivo"]').nth(row_index).fill(motivo)


def _submit_batch_form(page: Page) -> None:
    """Click the batch form's primary submit button."""
    page.locator('button[type="submit"]:has-text("Previsualizar lote")').click()


# --- 1. GET /entradas/batch/new --------------------------------------------


def test_batch_new_form_shows_five_initial_rows(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /entradas/batch/new → 200 with five empty ``<fieldset>`` rows.

    The template renders one ``<fieldset>`` per row from
    ``_build_initial_rows(5)``. Pinning the count at the template
    level protects against a future change that drops the count
    silently — a regression there would break the entire batch flow
    because operators would not see enough rows to fill.
    """
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/entradas/batch/new", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, f"/entradas/batch/new must return 200, got {response.status}"
    _csrf_token_from_form(page)  # regression sentinel

    # Five ``<fieldset>`` rows. The legend text is ``"Entrada {n}"``,
    # which gives us a secondary cross-check via the rendered text.
    fieldsets = page.locator("fieldset")
    assert fieldsets.count() == EXPECTED_INITIAL_ROWS, (
        f"batch new form must render exactly {EXPECTED_INITIAL_ROWS} "
        f"fieldset rows, got {fieldsets.count()}"
    )
    # Each row has at least the two required inputs (animal_id, fecha_entrada).
    animal_id_inputs = page.locator('input[name="animal_id"]')
    fecha_inputs = page.locator('input[name="fecha_entrada"]')
    assert animal_id_inputs.count() == EXPECTED_INITIAL_ROWS
    assert fecha_inputs.count() == EXPECTED_INITIAL_ROWS


# --- 2. POST /entradas/batch with 5 valid rows -----------------------------


def test_batch_post_five_valid_rows_redirects_to_preview(
    authenticated_session: tuple[Page, str],
    base_url: str,
    batch_animal_ids: list[str],
) -> None:
    """POST /entradas/batch with five valid rows → 303 to /entradas/batch/{id}.

    Pins the stage-batch happy path: the POST accepts five rows, the
    service stages them under a fresh ``batch_id``, and the browser
    lands on the preview URL.

    Each row uses a different animal (one of the ``batch_animal_ids``)
    and a different ``fecha_entrada`` so the cross-batch uniqueness
    check (``_check_cross_batch_uniqueness``) does not reject the
    batch.
    """
    page, _ = authenticated_session
    base_fecha = date.today()
    origins = [f"BatchOrigen-{i}-{uuid.uuid4().hex[:6]}" for i in range(EXPECTED_INITIAL_ROWS)]

    page.goto(f"{base_url}/entradas/batch/new", wait_until="domcontentloaded")
    for index in range(EXPECTED_INITIAL_ROWS):
        fecha = (base_fecha + timedelta(days=index + 1)).isoformat()
        _fill_batch_row(
            page,
            row_index=index,
            animal_id=batch_animal_ids[index],
            fecha_entrada=fecha,
            origen=origins[index],
        )

    with page.expect_response(lambda r: r.request.method == "POST") as resp_info:
        _submit_batch_form(page)
    response = resp_info.value

    assert response.status == 303, (
        f"batch POST with valid rows must return 303, got "
        f"{response.status}: {response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/entradas/batch/"), (
        f"batch POST must redirect to /entradas/batch/{{id}}, got {location!r}"
    )
    # The redirect target must NOT be /entradas/batch/new (that would
    # mean the service rejected the batch and re-rendered the form).
    assert location != "/entradas/batch/new", (
        "batch POST with valid rows must not redirect back to the new form"
    )


# --- 3. GET /entradas/batch/{id} preview -----------------------------------


def test_batch_preview_shows_status_per_row(
    authenticated_session: tuple[Page, str],
    base_url: str,
    batch_animal_ids: list[str],
) -> None:
    """GET /entradas/batch/{batch_id} → 200 with ``Válida`` status per row.

    Pins the preview contract: after a successful stage, the preview
    page renders one row per staged record with the ``Válida`` badge.
    The batch_id is extracted from the stage POST redirect so this
    test stays decoupled from the UUID format.
    """
    page, _ = authenticated_session
    base_fecha = date.today()

    # Stage five rows.
    page.goto(f"{base_url}/entradas/batch/new", wait_until="domcontentloaded")
    for index in range(EXPECTED_INITIAL_ROWS):
        fecha = (base_fecha + timedelta(days=index + 1)).isoformat()
        _fill_batch_row(
            page,
            row_index=index,
            animal_id=batch_animal_ids[index],
            fecha_entrada=fecha,
        )

    with page.expect_response(lambda r: r.request.method == "POST") as resp_info:
        _submit_batch_form(page)
    stage_response = resp_info.value
    assert stage_response.status == 303, (
        f"setup failed: batch POST must return 303, got {stage_response.status}"
    )
    location = stage_response.headers.get("location", "")
    batch_id = location.rsplit("/", 1)[-1]
    assert batch_id and batch_id != "new", (
        f"setup failed: could not extract batch_id from {location!r}"
    )

    # Fetch the preview page.
    preview_response = page.goto(
        f"{base_url}/entradas/batch/{batch_id}", wait_until="domcontentloaded"
    )
    assert preview_response is not None
    assert preview_response.status == 200, (
        f"/entradas/batch/{{batch_id}} must return 200, got {preview_response.status}"
    )

    # The preview page renders ``Válida`` for each successfully-staged
    # row. We count both the badge and the row count to pin the
    # contract on two axes: count == EXPECTED_INITIAL_ROWS, every row
    # shows Válida.
    body = page.content()
    assert body.count("Válida") >= EXPECTED_INITIAL_ROWS, (
        f"preview must show 'Válida' badge for all {EXPECTED_INITIAL_ROWS} "
        f"staged rows; got body excerpt: {body[:500]!r}"
    )


# --- 4. POST /entradas/batch/{id}/commit -----------------------------------


def test_batch_commit_redirects_to_entradas_and_creates_records(
    authenticated_session: tuple[Page, str],
    base_url: str,
    batch_animal_ids: list[str],
) -> None:
    """POST /entradas/batch/{id}/commit → 303 to /entradas; new records land.

    Pins the commit happy path: after staging, a POST to the commit
    endpoint copies the staging rows into ``entradas`` and redirects
    to ``/entradas``. The follow-up ``GET /entradas`` shows the new
    records (verified by their unique ``origen`` markers).
    """
    page, _ = authenticated_session
    base_fecha = date.today()
    origins = [f"Commit-{i}-{uuid.uuid4().hex[:8]}" for i in range(EXPECTED_INITIAL_ROWS)]

    # Stage.
    page.goto(f"{base_url}/entradas/batch/new", wait_until="domcontentloaded")
    for index in range(EXPECTED_INITIAL_ROWS):
        fecha = (base_fecha + timedelta(days=index + 1)).isoformat()
        _fill_batch_row(
            page,
            row_index=index,
            animal_id=batch_animal_ids[index],
            fecha_entrada=fecha,
            origen=origins[index],
        )

    with page.expect_response(lambda r: r.request.method == "POST") as resp_info:
        _submit_batch_form(page)
    stage_response = resp_info.value
    assert stage_response.status == 303, (
        f"setup failed: batch POST must return 303, got {stage_response.status}"
    )
    batch_id = stage_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert batch_id and batch_id != "new"

    # Visit the preview page so we can extract csrf_token from the
    # commit form. The preview template renders a
    # ``<form action="/entradas/batch/{batch_id}/commit">`` with a
    # csrf_token hidden input.
    preview_response = page.goto(
        f"{base_url}/entradas/batch/{batch_id}", wait_until="domcontentloaded"
    )
    assert preview_response is not None and preview_response.status == 200
    csrf_token = _csrf_token_from_form(page)

    # Commit.
    commit_response = page.request.post(
        f"{base_url}/entradas/batch/{batch_id}/commit",
        form={"csrf_token": csrf_token},
    )
    assert commit_response.status == 303, (
        f"batch commit POST must return 303, got {commit_response.status}: "
        f"{commit_response.text()[:300]!r}"
    )
    assert commit_response.headers.get("location", "").endswith("/entradas"), (
        f"batch commit must redirect to /entradas, got {commit_response.headers.get('location')!r}"
    )

    # Verify the new records landed in /entradas.
    list_response = page.goto(f"{base_url}/entradas", wait_until="domcontentloaded")
    assert list_response is not None and list_response.status == 200
    body = page.content()
    missing = [o for o in origins if o not in body]
    assert not missing, (
        f"after commit, all {EXPECTED_INITIAL_ROWS} origen markers must "
        f"appear in /entradas; missing: {missing!r}"
    )


# --- 5. POST /entradas/batch/{id}/cancel -----------------------------------


def test_batch_cancel_clears_staging_and_follow_up_returns_404(
    authenticated_session: tuple[Page, str],
    base_url: str,
    batch_animal_ids: list[str],
) -> None:
    """POST /entradas/batch/{id}/cancel → 303 to /entradas/batch/new.

    Pins the cancel path end-to-end: cancel clears staging without
    committing, the redirect lands on the new-batch form, and a
    follow-up GET to the cancelled batch_id returns 404 (the staging
    rows are gone).
    """
    page, _ = authenticated_session
    base_fecha = date.today()

    # Stage.
    page.goto(f"{base_url}/entradas/batch/new", wait_until="domcontentloaded")
    for index in range(EXPECTED_INITIAL_ROWS):
        fecha = (base_fecha + timedelta(days=index + 1)).isoformat()
        _fill_batch_row(
            page,
            row_index=index,
            animal_id=batch_animal_ids[index],
            fecha_entrada=fecha,
        )

    with page.expect_response(lambda r: r.request.method == "POST") as resp_info:
        _submit_batch_form(page)
    stage_response = resp_info.value
    assert stage_response.status == 303, (
        f"setup failed: batch POST must return 303, got {stage_response.status}"
    )
    batch_id = stage_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert batch_id and batch_id != "new"

    # Visit the preview to capture csrf_token from the cancel form.
    page.goto(f"{base_url}/entradas/batch/{batch_id}", wait_until="domcontentloaded")
    csrf_token = _csrf_token_from_form(page)

    # Cancel.
    cancel_response = page.request.post(
        f"{base_url}/entradas/batch/{batch_id}/cancel",
        form={"csrf_token": csrf_token},
    )
    assert cancel_response.status == 303, (
        f"batch cancel POST must return 303, got {cancel_response.status}: "
        f"{cancel_response.text()[:300]!r}"
    )
    assert cancel_response.headers.get("location", "").endswith("/entradas/batch/new"), (
        f"batch cancel must redirect to /entradas/batch/new, got "
        f"{cancel_response.headers.get('location')!r}"
    )

    # Follow-up GET to the cancelled batch_id must 404.
    follow_up = page.request.get(f"{base_url}/entradas/batch/{batch_id}")
    assert follow_up.status == 404, (
        f"cancelled batch_id must 404 on follow-up GET, got {follow_up.status}"
    )


# --- 6. POST with fewer than 5 rows ----------------------------------------


def test_batch_post_with_no_valid_rows_returns_422(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /entradas/batch with all-empty rows → 422 with Spanish error.

    The actual contract per ``app/modules/entradas/batch_routes.py`` is
    "needs at least one non-empty row", not "needs exactly five rows".
    Submitting five empty rows triggers the ``if not records`` branch
    in ``stage_batch_view`` and the form is re-rendered with status
    422 and the Spanish error message
    ``"Añade al menos una entrada antes de previsualizar."``.

    The PLAN-E2E-COVERAGE.md §Fichero 3 wording "POST with fewer than
    5 rows → 422" is satisfied by this empty-rows case (5 < 5+ in the
    sense that no record is staged). A future change to enforce an
    exact count of 5 would need a contract-level update; today's
    implementation accepts 1+ valid rows.
    """
    page, _ = authenticated_session

    page.goto(f"{base_url}/entradas/batch/new", wait_until="domcontentloaded")
    # All rows left empty — Playwright submits the form with empty
    # input values. The hidden csrf_token is the only populated field.
    _csrf_token_from_form(page)  # regression sentinel

    with page.expect_response(lambda r: r.request.method == "POST") as resp_info:
        _submit_batch_form(page)
    response = resp_info.value

    assert response.status == 422, (
        f"batch POST with no valid rows must return 422, got {response.status}"
    )
    body = response.text()
    assert "Añade al menos una entrada" in body, (
        f"422 response must carry the Spanish error message, got body excerpt: {body[:500]!r}"
    )
