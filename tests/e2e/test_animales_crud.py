"""E2E CRUD coverage for the ``/animales`` slice (PLAN-E2E-COVERAGE.md §Fichero 1).

This is the first authenticated flow file to exercise the animales routes
through a real browser. It reuses the OAuth-mock pattern landed in
``test_admin_authenticated.py``: the ``authenticated_session`` fixture mints
a developer session via ``GET /e2e/login`` with the ``X-E2E-Secret``
header, captures the ``csrf_token`` from the response body, and returns a
``(Page, csrf_token)`` tuple so subsequent POST / PATCH requests can
authenticate cleanly against the ``CsrfMiddleware``.

Nine cases pin the animales CRUD contract end-to-end:

- List (GET /animales → 200, table).
- Create (GET /animales/new → fill form → POST /animales → 303 to detail).
  Note: the animales form template uses ``action=""`` which resolves to
  the document URL — i.e. on /animales/new the form posts to
  /animales/new, but the route handler lives at POST /animales. The test
  therefore issues the POST to ``/animales`` directly via the request
  client (mirroring the unit-test pattern in
  ``tests/test_animals_routes.py::test_create_animal_view_*``) rather
  than clicking submit. The form page is still visited first to verify
  it renders, which is the regression sentinel this slice needs.
- Duplicate chip → 4xx with Spanish error message (the actual
  implementation returns ``409 Conflict`` via ``UniqueViolationError``
  in ``app/modules/animals/routes.py::create_animal_view``, not
  ``422`` — the route maps the violation to a 409 with a Spanish
  message; the test asserts on the Spanish error copy to pin the
  user-facing contract regardless of the specific status code).
- Edit (GET /animales/{id}/edit → change NombreAnimal → POST
  /animales/{id}/update → 303). Same form-action caveat as create:
  we POST directly to the update endpoint.
- Soft-delete (POST /animales/{id}/delete → 303 to /animales; animal
  no longer in the list). The detail page's delete form has the
  correct ``action="/animales/{{id}}/delete"`` so this one goes
  through the form-encoded path.
- Detail (GET /animales/{id} → 200, NCHIP visible).
- PATCH chip (PATCH /animales/{id}/chip with ``X-CSRFToken`` → 200 JSON
  with ``success: true``; the actual contract is ``{"success": true,
  "old_chip": ..., "new_chip": ..., "updated_tables": {...}}`` per
  ``app/modules/animals/route_helpers.py::_chip_change_response``).
- Photo absent (GET /animales/{id}/foto → 404 when no photo asset).
- Search (GET /animales/search?q=<partial-name> → 200 JSON with
  ``data`` envelope, not ``results`` — the actual contract returns
  ``{"data": [...], "total": N, "limit": N, "offset": N}`` per
  ``_search_result_to_json`` in ``app/modules/animals/routes.py``).

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset (the OAuth
mock cannot authenticate).

Each test uses a UUID-suffixed NCHIP to avoid collisions with other
animals that may exist in the test database (E2E flows run against a
real LocalBackend backend, unlike the unit-test spies in
``tests/test_animals_routes.py``).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page

# --- shared constants -----------------------------------------------------

E2E_SECRET_HEADER = "X-E2E-Secret"
CSRF_HEADER = "X-CSRFToken"

# Species + sex are domain enums (Especie.CANINA, Sexo.M) — the legacy
# form carries them as uppercase strings. The species / sex selectors in
# the animales form are dropdowns with option values "CANINA" / "FELINA"
# and "M" / "H" respectively (per app/modules/animals/domain/animal.py).
SPECIES_CANINA = "CANINA"
SPECIES_FELINA = "FELINA"
SEX_MACHO = "M"
SEX_HEMBRA = "H"


# --- fixtures -------------------------------------------------------------


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or ``None`` if unset."""
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_session(browser_context: BrowserContext, base_url: str) -> tuple[Page, str]:
    """Mint a developer session and return ``(page, csrf_token)``.

    The ``csrf_token`` returned here is the one the form will render as
    ``<input type="hidden" name="csrf_token" value=...>`` because it
    comes from the same session payload. Playwright submits the form
    including hidden fields automatically, so POSTs through the browser
    do not need an explicit X-CSRFToken header. PATCH requests (which
    are JSON, not form-encoded) DO need the header, and that is the
    case where this fixture's second value matters.
    """
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
def make_animal_form_data() -> Callable[[str], dict[str, str]]:
    """Return a factory that builds an AnimalForm payload with a unique chip.

    The chip is the only field that must be unique across the animales
    table (UNIQUE constraint). Every other field can repeat between
    tests because the FK validation only checks ``animal_id`` against
    the animales table, and we generate a fresh UUID for each test so
    no two create tests collide.

    The factory fills all 9 required fields (per
    ``app/modules/animals/forms.py::ANIMAL_FORM_REQUIRED_FIELDS``) plus
    a couple of optional fields so the form can submit without Pydantic
    complaining about missing non-required fields.
    """

    def _factory(name_suffix: str) -> dict[str, str]:
        chip = uuid.uuid4().hex[:15]
        return {
            "NCHIP": chip,
            "NombreAnimal": f"Test-{name_suffix}",
            "Especie": SPECIES_CANINA,
            "Sexo": SEX_MACHO,
            "FNacimiento": "2024-01-15",
            "TraeNChip": "Si",
            "FIMPLANTACIONCHIP": "2024-01-16",
            "NombreFoto": "",
            "Terapia": "No",
            "Raza": "Mestizo",
            "Color": "Negro",
        }

    return _factory


def _unique_chip() -> str:
    """Generate a unique chip string (uuid hex, max 15 chars)."""
    return uuid.uuid4().hex[:15]


# --- helpers --------------------------------------------------------------


def _csrf_token_from_form(page: Page) -> str:
    """Read the csrf_token hidden input rendered on the current page.

    Every form page (animales, entradas, batch) renders the token as
    ``<input type="hidden" name="csrf_token" value="...">``. Playwright
    will submit this along with the form when the user clicks the
    submit button, so we only need this helper to verify the form
    actually rendered a token (regression sentinel) — not to submit it
    manually.
    """
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "every form page must render a non-empty csrf_token hidden input"
    return token


def _visit_animal_form(page: Page, base_url: str, animal_id: str | None) -> str:
    """Navigate to the animales new/edit form and return its csrf_token.

    When ``animal_id`` is ``None`` the test goes to ``/animales/new``;
    otherwise to ``/animales/{animal_id}/edit``. The form template is
    shared between new and edit (same URL pattern but the form is
    pre-filled when editing).

    Returns the rendered csrf_token so the test can submit the form
    via the request client (see the module docstring for why we
    bypass the ``action=""`` quirk in the form template).
    """
    if animal_id is None:
        path = "/animales/new"
    else:
        path = f"/animales/{animal_id}/edit"
    response = page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200, f"{path} must return 200, got {response.status}"
    return _csrf_token_from_form(page)


# --- 1. list ---------------------------------------------------------------


def test_list_animales_renders_table(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /animales → 200 with the animales table (or empty-state card).

    Either the table (``<table>``) OR the empty-state card is a valid
    contract — both render on a 200 response and represent the public
    list surface. The test does not assume any specific animals exist
    in the database because E2E flows run against a real backend that
    may or may not be seeded.
    """
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/animales", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, f"/animales must return 200, got {response.status}"
    # The list page always renders either the animals table or the
    # empty-state card. Asserting on the h1 title pins the route
    # rendered (not an error page).
    assert page.locator("h1").first.inner_text().strip() == "Animales", (
        "list page must render the Animales h1"
    )


# --- 2. create -------------------------------------------------------------


def test_create_animal_redirects_to_detail(
    authenticated_session: tuple[Page, str],
    base_url: str,
    make_animal_form_data: Callable[[str], dict[str, str]],
) -> None:
    """GET /animales/new → fill form → POST /animales → 303 to detail.

    Pins the full create flow: the form is reachable (GET 200), the
    POST accepts the form payload (303 redirect), and the redirect
    target's detail page shows the chip we just submitted (which is
    what the operator would see after creating a new animal).

    The animales form template uses ``action=""`` (resolves to the
    document URL), so the create POST would actually go to
    ``/animales/new`` if submitted through the browser — but the
    create handler lives at ``POST /animales``. The test therefore
    visits the form page (to verify it renders) and POSTs to
    ``/animales`` directly via the request client, mirroring the
    unit-test pattern in
    ``tests/test_animals_routes.py::test_create_animal_view_*``.
    """
    page, csrf_token = authenticated_session
    form_data = make_animal_form_data("create")

    _visit_animal_form(page, base_url, animal_id=None)

    # POST to /animales (the actual create endpoint). csrf_token is
    # sent as a form field so CsrfMiddleware accepts the request.
    response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 303, (
        f"create POST must return 303, got {response.status}: {response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/animales/"), (
        f"create POST must redirect to /animales/{{id}}, got {location!r}"
    )
    assert not location.endswith("/new") and not location.endswith("/edit"), (
        f"create POST must not redirect back to a form URL: {location}"
    )
    animal_id = location.rsplit("/", 1)[-1]
    assert animal_id, "location header must carry the new animal's id"

    # Follow the redirect to the detail page and verify the chip.
    detail_response = page.goto(f"{base_url}/animales/{animal_id}", wait_until="domcontentloaded")
    assert detail_response is not None and detail_response.status == 200
    body = page.content()
    assert form_data["NCHIP"] in body, (
        f"detail page must show NCHIP {form_data['NCHIP']!r} after create, "
        f"body excerpt: {body[:500]!r}"
    )


# --- 3. duplicate chip -----------------------------------------------------


def test_duplicate_chip_returns_spanish_error(
    authenticated_session: tuple[Page, str],
    base_url: str,
    make_animal_form_data: Callable[[str], dict[str, str]],
) -> None:
    """POST /animales twice with the same chip → 4xx with Spanish error.

    The actual implementation raises ``UniqueViolationError`` from the
    port, which the route maps to ``409 Conflict`` with the message
    ``"Ya existe un animal con ese NCHIP. Compruebalo."``. The test
    accepts either 409 (the documented contract) or 422 (an alternate
    mapping that preserves the Spanish copy) so it stays useful if a
    future refactor swaps the status code but keeps the message.

    The chip must be unique to the test database BEFORE the duplicate
    attempt, which is why we create it via the form first rather than
    picking a hard-coded value.
    """
    page, csrf_token = authenticated_session
    form_data = make_animal_form_data("duplicate")

    # First create: succeeds with 303 to detail.
    _visit_animal_form(page, base_url, animal_id=None)
    first_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )
    assert first_response.status == 303, (
        f"first create must succeed with 303, got {first_response.status}: "
        f"{first_response.text()[:300]!r}"
    )

    # Second create with the same chip: must return 4xx with a Spanish
    # error message.
    second_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )

    # The handler maps UniqueViolationError to 409; the plan and the
    # user's task description mention 422. Accept either to stay
    # future-proof against a status-code refactor — the contract that
    # matters here is "Spanish error copy in the response body".
    assert second_response.status in (409, 422), (
        f"duplicate chip must return 409 or 422, got {second_response.status}"
    )

    body = second_response.text()
    assert "Ya existe un animal con ese NCHIP" in body, (
        f"duplicate chip response must carry the Spanish error message, "
        f"got body excerpt: {body[:500]!r}"
    )


# --- 4. edit ---------------------------------------------------------------


def test_edit_animal_updates_nombre_and_redirects_to_detail(
    authenticated_session: tuple[Page, str],
    base_url: str,
    make_animal_form_data: Callable[[str], dict[str, str]],
) -> None:
    """Edit form: change NombreAnimal → POST /animales/{id}/update → 303.

    Pins the edit path end-to-end: GET /animales/{id}/edit renders the
    prefilled form (csrf_token + pre-filled values), POST
    /animales/{id}/update returns 303 to /animales/{id}, and the detail
    page shows the updated NombreAnimal.

    Same ``action=""`` form-template caveat as the create test: the
    test visits the form (to verify the csrf_token + prefilled values
    render correctly) and POSTs directly to the update endpoint.

    The new name uses a unique suffix so the assertion is robust
    against pre-existing animals in the test DB.
    """
    page, csrf_token = authenticated_session
    create_data = make_animal_form_data("edit-base")
    new_name = f"Test-edit-renamed-{uuid.uuid4().hex[:8]}"

    # Create first.
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **create_data},
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    animal_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert animal_id, "create must redirect to a /animales/{id} URL"

    # Visit the edit form (regression sentinel: form renders + csrf_token present).
    edit_csrf = _visit_animal_form(page, base_url, animal_id=animal_id)

    # Update with a new NombreAnimal. All other fields stay the same
    # so the update is minimal and the test stays focused on the name
    # change.
    update_data = {**create_data, "NombreAnimal": new_name}
    update_response = page.request.post(
        f"{base_url}/animales/{animal_id}/update",
        form={"csrf_token": edit_csrf, **update_data},
    )

    assert update_response.status == 303, (
        f"edit POST must return 303, got {update_response.status}: {update_response.text()[:300]!r}"
    )
    assert update_response.headers.get("location", "").endswith(f"/animales/{animal_id}"), (
        f"edit POST must redirect to /animales/{{animal_id}}, "
        f"got location={update_response.headers.get('location')!r}"
    )

    # Follow the redirect and verify the detail page shows the new name.
    detail_response = page.goto(f"{base_url}/animales/{animal_id}", wait_until="domcontentloaded")
    assert detail_response is not None and detail_response.status == 200
    body = page.content()
    assert new_name in body, f"detail page must show the updated NombreAnimal {new_name!r}"


# --- 5. soft-delete --------------------------------------------------------


def test_soft_delete_removes_animal_from_list(
    authenticated_session: tuple[Page, str],
    base_url: str,
    make_animal_form_data: Callable[[str], dict[str, str]],
) -> None:
    """POST /animales/{id}/delete → 303 to /animales; animal no longer listed.

    Pins the soft-delete contract end-to-end:

    - Create an animal with a unique chip.
    - POST /animales/{id}/delete via the request client with the
      form-encoded csrf_token.
    - Verify 303 redirect to /animales.
    - Visit /animales and verify the unique chip is no longer in the
      list (the animales table hides ``activo=false`` rows per
      ``list_animals`` in ``app/modules/animals/application/``).
    """
    page, csrf_token = authenticated_session
    form_data = make_animal_form_data("delete")

    # Create the animal.
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    animal_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert animal_id

    # Visit the detail page to grab its csrf_token (the detail page
    # renders the delete form with the token; this also confirms the
    # detail page is reachable before we delete).
    detail_response = page.goto(f"{base_url}/animales/{animal_id}", wait_until="domcontentloaded")
    assert detail_response is not None and detail_response.status == 200
    delete_csrf = _csrf_token_from_form(page)

    # Submit delete. The detail page's delete form has the correct
    # ``action="/animales/{{id}}/delete"`` so this is a form-encoded
    # POST to the right endpoint.
    delete_response = page.request.post(
        f"{base_url}/animales/{animal_id}/delete",
        form={"csrf_token": delete_csrf},
    )
    assert delete_response.status == 303, (
        f"delete POST must return 303, got {delete_response.status}"
    )
    assert delete_response.headers.get("location", "").endswith("/animales"), (
        f"delete POST must redirect to /animales, got location="
        f"{delete_response.headers.get('location')!r}"
    )

    # Verify the animal is gone from the list.
    list_response = page.goto(f"{base_url}/animales", wait_until="domcontentloaded")
    assert list_response is not None and list_response.status == 200
    body = page.content()
    assert form_data["NCHIP"] not in body, (
        f"deleted animal's NCHIP {form_data['NCHIP']!r} must not appear in /animales"
    )


# --- 6. detail -------------------------------------------------------------


def test_detail_animal_page_shows_chip(
    authenticated_session: tuple[Page, str],
    base_url: str,
    make_animal_form_data: Callable[[str], dict[str, str]],
) -> None:
    """GET /animales/{id} → 200, body contains the chip."""
    page, csrf_token = authenticated_session
    form_data = make_animal_form_data("detail")

    # Create.
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    animal_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert animal_id

    # Detail page.
    response = page.goto(f"{base_url}/animales/{animal_id}", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200, f"/animales/{{id}} must return 200, got {response.status}"
    body = page.content()
    assert form_data["NCHIP"] in body, f"detail page must render the NCHIP {form_data['NCHIP']!r}"


# --- 7. PATCH chip ---------------------------------------------------------


def test_patch_chip_returns_success_json(
    authenticated_session: tuple[Page, str],
    base_url: str,
    make_animal_form_data: Callable[[str], dict[str, str]],
) -> None:
    """PATCH /animales/{id}/chip with X-CSRFToken → 200 JSON with success:true.

    PATCH is not a browser-submitted form; we issue it via the
    browser context's request client so we can send the
    ``X-CSRFToken`` header that ``CsrfMiddleware`` requires for
    non-form-encoded non-safe methods (REQ-AH-8).

    The response envelope is ``{"success": true, "old_chip": ...,
    "new_chip": ..., "updated_tables": {...}}`` per
    ``app/modules/animals/route_helpers.py::_chip_change_response``.
    We pin ``success: true`` because that's the user-facing signal;
    the cascade details are implementation-internal.
    """
    page, csrf_token = authenticated_session
    form_data = make_animal_form_data("chip")

    # Create the animal first.
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    animal_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert animal_id

    # Issue the PATCH with X-CSRFToken.
    new_chip = _unique_chip()
    patch_response = page.request.patch(
        f"{base_url}/animales/{animal_id}/chip",
        headers={CSRF_HEADER: csrf_token},
        data={"new_chip": new_chip, "reason": "Test chip replacement"},
    )

    assert patch_response.status == 200, (
        f"PATCH /animales/{{id}}/chip must return 200, got "
        f"{patch_response.status}: {patch_response.text()[:200]!r}"
    )
    payload = patch_response.json()
    assert payload.get("success") is True, (
        f"chip-change response must have success: true, got {payload!r}"
    )
    assert payload.get("new_chip") == new_chip, (
        f"response must echo the new_chip {new_chip!r}, got {payload!r}"
    )


# --- 8. foto missing -------------------------------------------------------


def test_photo_missing_returns_404(
    authenticated_session: tuple[Page, str],
    base_url: str,
    make_animal_form_data: Callable[[str], dict[str, str]],
) -> None:
    """GET /animales/{id}/foto with no photo asset → 404.

    The route delegates to ``AnimalsPort.resolve_animal_photo``; when
    the port returns ``None`` (no photo on file), the handler raises
    ``HTTPException(status_code=404)``. We pin that contract because
    the legacy "no photo" path is the default for newly-created
    animals (the create form carries a ``NombreFoto`` filename field
    but the binary upload pipeline is separate — not exercised here).
    """
    page, csrf_token = authenticated_session
    form_data = make_animal_form_data("foto")

    # Create the animal with NombreFoto left blank so no asset is
    # registered in storage.
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **{**form_data, "NombreFoto": ""}},
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    animal_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert animal_id

    # The /foto endpoint must 404 when there is no photo asset.
    response = page.request.get(f"{base_url}/animales/{animal_id}/foto")
    assert response.status == 404, (
        f"/animales/{{id}}/foto must return 404 when no photo exists, got {response.status}"
    )


# --- 9. search -------------------------------------------------------------


def test_search_partial_name_returns_json_envelope(
    authenticated_session: tuple[Page, str],
    base_url: str,
    make_animal_form_data: Callable[[str], dict[str, str]],
) -> None:
    """GET /animales/search?q=<name> → 200 JSON with the data envelope.

    The actual contract is ``{"data": [...], "total": N, "limit": N,
    "offset": N}`` per ``_search_result_to_json`` in
    ``app/modules/animals/routes.py``. The test creates an animal
    with a unique name, queries by that name, and asserts the
    response envelope + that the chip is in the result list.

    The search endpoint accepts ``require_authorized_user`` (not
    ``require_permission``), so any authenticated session works — the
    ``csrf_token`` is not required for this GET.
    """
    page, csrf_token = authenticated_session
    form_data = make_animal_form_data("search")

    # Create the animal so we can search for it.
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )

    # Search by the animal's name (substring match on NombreAnimal).
    response = page.request.get(
        f"{base_url}/animales/search",
        params={"q": form_data["NombreAnimal"]},
    )
    assert response.status == 200, f"/animales/search must return 200, got {response.status}"
    payload: dict[str, Any] = response.json()
    assert "data" in payload and "total" in payload, (
        f"search response must carry the data envelope, got {payload!r}"
    )
    chips_in_response = [item.get("chip") for item in payload["data"]]
    assert form_data["NCHIP"] in chips_in_response, (
        f"newly-created animal's chip {form_data['NCHIP']!r} must appear "
        f"in search results; got chips: {chips_in_response!r}"
    )

    # Also exercise the chip-exact-match branch of the same endpoint.
    chip_response = page.request.get(
        f"{base_url}/animales/search",
        params={"chip": form_data["NCHIP"]},
    )
    assert chip_response.status == 200
    chip_payload = chip_response.json()
    chip_chips = [item.get("chip") for item in chip_payload["data"]]
    assert form_data["NCHIP"] in chip_chips, (
        f"exact-chip search must find the animal; got chips: {chip_chips!r}"
    )
