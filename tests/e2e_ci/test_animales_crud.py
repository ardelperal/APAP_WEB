"""E2E CRUD coverage for the ``/animales`` slice under the CI browser gate.

Port of ``tests/e2e/test_animales_crud.py`` (issue #1095, slice 1) so the
fail-closed CI smoke suite (``tests/e2e_ci/``) actually exercises
business flows instead of six tests that submit no form.

The shared helpers (``animal_form_data``, ``csrf_token_from_form``,
``unique_chip``, species/sex constants, Spanish error fragments) live
in ``tests/e2e_ci/_crud_helpers.py`` and are reused by the five
follow-up batteries (entradas, adopciones, acogidas, cesiones, sanidad).

Fail-closed contract: under this gate a missing
``APAP_E2E_AUTH_SECRET``, a failed /e2e/login, or a non-303 on a happy
path is a HARD failure, never a skip. The original
``tests/e2e/test_animales_crud.py`` skipped when ``APAP_E2E_AUTH_SECRET``
was unset and when the host animal could not be created; the port
removes every ``pytest.skip`` so the gate stays loud when something is
wrong (point of this slice).

Nine cases pin the animales CRUD contract end-to-end:

- List (GET /animales → 200, ``Animales`` h1).
- Create (POST /animales → 303 to detail). Same ``action=""`` form
  caveat as the original: we POST directly to ``/animales`` via the
  request client.
- Duplicate chip → 4xx with the Spanish error fragment
  ``"Ya existe un animal con ese NCHIP"``.
- Edit (POST /animales/{id}/update → 303 to /animales/{id}).
- Soft-delete (POST /animales/{id}/delete → 303 to /animales; animal
  no longer in the list).
- Detail (GET /animales/{id} → 200, NCHIP visible).
- PATCH chip (PATCH /animales/{id}/chip → 200 JSON with ``success: true``).
- Photo absent (GET /animales/{id}/foto → 404 when no photo asset).
- Search (GET /animales/search?q=<name> → 200 JSON with ``data`` envelope).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from playwright.sync_api import Page

from tests.e2e_ci._crud_helpers import (
    animal_form_data,
    csrf_token_from_form,
    unique_chip,
)

# --- helpers --------------------------------------------------------------


def _visit_animal_form(page: Page, base_url: str, animal_id: str | None) -> str:
    """Navigate to the animales new/edit form and return its csrf_token.

    When ``animal_id`` is ``None`` the test goes to ``/animales/new``;
    otherwise to ``/animales/{animal_id}/edit``. The form template is
    shared between new and edit (same URL pattern but the form is
    pre-filled when editing).

    Returns the rendered csrf_token so the test can submit the form
    via the request client (the animales form template uses
    ``action=""``, which resolves to the document URL — see the
    module-level docstring of the original test for the rationale).
    """
    if animal_id is None:
        path = "/animales/new"
    else:
        path = f"/animales/{animal_id}/edit"
    response = page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200, f"{path} must return 200, got {response.status}"
    return csrf_token_from_form(page)


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
    form_data = animal_form_data("create")

    _visit_animal_form(page, base_url, animal_id=None)

    # POST to /animales (the actual create endpoint). csrf_token is
    # sent as a form field so CsrfMiddleware accepts the request.
    # ``max_redirects=0`` keeps the raw 303 (APIRequestContext follows
    # redirects by default; without the override the assertion would
    # see the final 200 detail page, not the 303 the route emits).
    response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "issue #1293: the psycopg executor turns SQLSTATE 23505 into QueryError "
        "(app/core/local_backend/db.py:91), so the route never reaches its "
        "UniqueViolationError branch and the response is 502, not 409"
    ),
)
def test_duplicate_chip_returns_spanish_error(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /animales twice with the same chip → 4xx with Spanish error.

    Pinned as ``xfail(strict=True)`` against issue #1293, not as a skip:
    the contract below is the one the route documents, the application
    serves a 502 today, and a strict xfail turns red the moment the bug is
    fixed so the marker cannot outlive it. The assertion stays on the
    documented contract on purpose; adjusting it to the 502 would bless the
    bug.

    The actual implementation raises ``UniqueViolationError`` from the
    port, which the route maps to ``409 Conflict`` with the message
    ``"Ya existe un animal con ese NCHIP. Compruebalo."``. The test
    accepts either 409 (the documented contract) or 422 (an alternate
    mapping that preserves the Spanish copy) so it stays useful if a
    future refactor swaps the status code but keeps the message.

    The chip must be unique to the test database BEFORE the duplicate
    attempt, which is why we create it via the form first rather than
    picking a hard-coded value. Under this gate the create POST is
    fail-closed: a non-303 on the first attempt is a hard failure
    (no skip).
    """
    page, csrf_token = authenticated_session
    form_data = animal_form_data("duplicate")

    # First create: succeeds with 303 to detail. Fail-closed: a non-303
    # is a hard assertion (the original test had a pytest.skip on this
    # branch — the gate forbids skips).
    _visit_animal_form(page, base_url, animal_id=None)
    first_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )
    assert first_response.status == 303, (
        f"first create must succeed with 303, got {first_response.status}: "
        f"{first_response.text()[:300]!r}"
    )

    # Second create with the same chip: must return 4xx with a Spanish
    # error message. The 4xx branch is not a redirect, so the default
    # redirect-follow does not interfere; we still pass ``max_redirects=0``
    # for consistency with the create test.
    second_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
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
    create_data = animal_form_data("edit-base")
    new_name = f"Test-edit-renamed-{uuid.uuid4().hex[:8]}"

    # Create first (fail-closed).
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **create_data},
        max_redirects=0,
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
        max_redirects=0,
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
    form_data = animal_form_data("delete")

    # Create the animal (fail-closed).
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
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
    delete_csrf = csrf_token_from_form(page)

    # Submit delete. The detail page's delete form has the correct
    # ``action="/animales/{{id}}/delete"`` so this is a form-encoded
    # POST to the right endpoint.
    delete_response = page.request.post(
        f"{base_url}/animales/{animal_id}/delete",
        form={"csrf_token": delete_csrf},
        max_redirects=0,
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
) -> None:
    """GET /animales/{id} → 200, body contains the chip."""
    page, csrf_token = authenticated_session
    form_data = animal_form_data("detail")

    # Create (fail-closed).
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
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
    form_data = animal_form_data("chip")

    # Create the animal first (fail-closed).
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    animal_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert animal_id

    # Issue the PATCH with X-CSRFToken.
    new_chip = unique_chip()
    patch_response = page.request.patch(
        f"{base_url}/animales/{animal_id}/chip",
        headers={"X-CSRFToken": csrf_token},
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


def test_photo_missing_serves_the_placeholder(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """GET /animales/{id}/foto with no photo asset → a placeholder PNG, not 404.

    ``resolve_animal_photo`` answers a placeholder by design whenever
    storage is unconfigured, the object comes back empty, or the storage
    call fails (``_placeholder()`` under ``is_placeholder=True``, see
    ``app/modules/animals/adapters/local_backend/animals_local_backend_photo.py``):
    the template always receives an image, so a list never renders a
    broken thumbnail.

    The legacy e2e battery asserted a 404 here, a contract the adapter no
    longer has. This pin documents the behaviour production actually
    serves; if the team prefers the 404, that is a product decision and
    this assertion is where it would change.
    """
    page, csrf_token = authenticated_session
    form_data = animal_form_data("foto")

    # Create the animal with NombreFoto left blank so no asset is
    # registered in storage (fail-closed).
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **{**form_data, "NombreFoto": ""}},
        max_redirects=0,
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    animal_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert animal_id

    # The /foto endpoint answers the designed placeholder, never a 404.
    response = page.request.get(f"{base_url}/animales/{animal_id}/foto")
    assert response.status == 200, (
        f"/animales/{{id}}/foto must serve the placeholder, got {response.status}"
    )
    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("image/png"), (
        f"placeholder must be a PNG, got {content_type!r}"
    )
    assert response.body(), "placeholder body must not be empty"


# --- 9. search -------------------------------------------------------------


def test_search_partial_name_returns_json_envelope(
    authenticated_session: tuple[Page, str],
    base_url: str,
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
    form_data = animal_form_data("search")

    # Create the animal so we can search for it (fail-closed).
    _visit_animal_form(page, base_url, animal_id=None)
    create_response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
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
