"""E2E CRUD coverage for the ``/entradas`` slice under the CI browser gate.

Port of ``tests/e2e/test_entradas_crud.py`` (issue #1095, slice 2) so the
fail-closed CI smoke suite (``tests/e2e_ci/``) actually exercises the
intake-entry business flow instead of skipping on every assertion.

The seven tests pin the entradas CRUD contract end-to-end:

- List (GET /entradas -> 200, ``Entradas`` h1).
- Create (POST /entradas -> 303 to detail). The shared
  ``animal_id_factory`` supplies a host animal because the FK
  validation rejects an ``animal_id`` that does not reference an
  existing animal.
- Create with non-existent ``animal_id`` -> 422 with a Spanish error
  message. The application raises ``ValueError("animal_id does not
  reference an existing animal")`` and the route maps it to 422.
- Detail (GET /entradas/{id} -> 200, animal_id visible).
- Edit (POST /entradas/{id}/update -> 303 to /entradas/{id}; new
  ``origen`` visible).
- Soft-delete (POST /entradas/{id}/delete -> 303 to /entradas;
  entry no longer appears in the list).
- Future ``fecha_entrada``: the original test skipped when the
  POST returned 303 (because no future-date validation exists
  today). The slice-2 port leaves the assertion as the contract
  states it (4xx), reports the real status, and uses the
  ``findings`` channel rather than a silent ``pytest.skip``.

Seven cases, mirror the slice-1 animales battery exactly in
mechanics (Playwright ``page.goto`` for the regression sentinel
+ ``page.request.post(..., max_redirects=0)`` for the assertion)
so the CI browser gate stays homogeneous.

The shared helpers (``animal_form_data``, ``csrf_token_from_form``,
``entrada_form_data``, Spanish fragments, list/h1 constants) live
in ``tests/e2e_ci/_crud_helpers.py``; the shared fixtures
(``authenticated_session``, ``animal_id_factory``) live in
``tests/e2e_ci/conftest.py``.

Fail-closed contract: under this gate a missing
``APAP_E2E_AUTH_SECRET``, a failed ``/e2e/login``, or a non-303 on
a happy path is a HARD failure, never a skip.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, timedelta

import pytest
from playwright.sync_api import Page

from tests.e2e_ci._crud_helpers import (
    ENTRADA_SAVE_FAILED_SPANISH,
    ENTRADAS_LIST_TITLE,
    NONEXISTENT_ANIMAL_SPANISH,
    csrf_token_from_form,
    entrada_form_data,
)

# --- helpers --------------------------------------------------------------


def _visit_entradas_form(
    page: Page, base_url: str, entrada_id: str | None
) -> str:
    """Navigate to the entradas new/edit form and return its csrf_token.

    When ``entrada_id`` is ``None`` the test goes to ``/entradas/new``;
    otherwise to ``/entradas/{entrada_id}/edit``. The form template is
    shared between new and edit (same URL pattern but the form is
    pre-filled when editing).

    Mirrors ``test_animales_crud.py::_visit_animal_form`` (slice 1).
    """
    if entrada_id is None:
        path = "/entradas/new"
    else:
        path = f"/entradas/{entrada_id}/edit"
    response = page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200, f"{path} must return 200, got {response.status}"
    return csrf_token_from_form(page)


# --- 1. list ---------------------------------------------------------------


def test_list_entradas_renders_200(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /entradas -> 200 with the ``Entradas`` h1 (or empty-state card)."""
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/entradas", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, f"/entradas must return 200, got {response.status}"
    assert page.locator("h1").first.inner_text().strip() == ENTRADAS_LIST_TITLE, (
        "list page must render the Entradas h1"
    )


# --- 2. create -------------------------------------------------------------


def test_create_entrada_redirects_to_detail(
    authenticated_session: tuple[Page, str],
    base_url: str,
    animal_id_factory: Callable[[], str],
) -> None:
    """Submit entrada form with valid animal_id -> 303 to detail page.

    Pins the create flow end-to-end: form is reachable (GET 200), the
    POST accepts a valid animal_id (303 redirect), and the detail
    page shows the ``animal_id`` and the ``origen`` marker the test
    just submitted.
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    fecha = "2026-06-25"
    origen_marker = f"Origen-Test-{uuid.uuid4().hex[:8]}"

    # Visit the form (regression sentinel — the page must render + csrf present).
    _visit_entradas_form(page, base_url, entrada_id=None)

    # POST via the request client (mirroring the slice-1 animales
    # create path): ``max_redirects=0`` keeps the raw 303 (Playwright
    # follows redirects by default and would otherwise hide the 303
    # under a 200 detail page).
    response = page.request.post(
        f"{base_url}/entradas",
        form={"csrf_token": csrf_token, **entrada_form_data(
            animal_id=animal_id,
            fecha_entrada=fecha,
            origen=origen_marker,
        )},
        max_redirects=0,
    )
    assert response.status == 303, (
        f"create POST must return 303, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/entradas/"), (
        f"create POST must redirect to /entradas/{{id}}, got {location!r}"
    )
    assert not location.endswith("/new") and not location.endswith("/edit"), (
        f"create POST must not redirect back to a form URL: {location}"
    )
    entrada_id = location.rsplit("/", 1)[-1]
    assert entrada_id

    # Follow the redirect to the detail page and verify the markers.
    detail_response = page.goto(
        f"{base_url}/entradas/{entrada_id}", wait_until="domcontentloaded"
    )
    assert detail_response is not None and detail_response.status == 200
    body = page.content()
    assert animal_id in body, f"detail page must show the animal_id {animal_id!r}"
    assert origen_marker in body, (
        f"detail page must show the origen marker {origen_marker!r}"
    )


# --- 3. create with non-existent animal_id ---------------------------------


def test_create_with_nonexistent_animal_returns_422_with_spanish_error(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """Submit entrada form with bogus animal_id -> 422 with Spanish error.

    The route's ``ValueError`` (raised by ``_validate_references`` in
    ``app/modules/entradas/service.py``) maps to a 422 response with
    the message re-rendered through the form template. The form
    template prepends ``"No se pudo guardar la entrada"`` and exposes
    the FK validation message verbatim.

    The bogus ``animal_id`` uses a UUID-shaped string that cannot
    exist in any ``animales`` table, so the FK check is guaranteed
    to fail.
    """
    page, csrf_token = authenticated_session

    bogus_animal_id = str(uuid.uuid4())  # well-formed UUID, never inserted

    response = page.request.post(
        f"{base_url}/entradas",
        form={"csrf_token": csrf_token, **entrada_form_data(
            animal_id=bogus_animal_id,
            fecha_entrada="2026-06-25",
        )},
        max_redirects=0,
    )

    assert response.status == 422, (
        f"create with bogus animal_id must return 422, got {response.status}"
    )
    body = response.text()
    assert ENTRADA_SAVE_FAILED_SPANISH in body, (
        f"422 response must carry the Spanish form error header, "
        f"got body excerpt: {body[:500]!r}"
    )
    assert NONEXISTENT_ANIMAL_SPANISH in body or "animal_id" in body, (
        f"422 response must surface the FK validation message, "
        f"got body excerpt: {body[:500]!r}"
    )


# --- 4. detail -------------------------------------------------------------


def test_detail_entrada_page_shows_animal_id(
    authenticated_session: tuple[Page, str],
    base_url: str,
    animal_id_factory: Callable[[], str],
) -> None:
    """GET /entradas/{id} -> 200, body contains the animal_id."""
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    fecha = "2026-06-25"

    # Create the entrada (fail-closed).
    _visit_entradas_form(page, base_url, entrada_id=None)
    create_response = page.request.post(
        f"{base_url}/entradas",
        form={"csrf_token": csrf_token, **entrada_form_data(
            animal_id=animal_id,
            fecha_entrada=fecha,
        )},
        max_redirects=0,
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, "
        f"got {create_response.status}: {create_response.text()[:300]!r}"
    )
    entrada_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert entrada_id

    # Detail page.
    response = page.goto(
        f"{base_url}/entradas/{entrada_id}", wait_until="domcontentloaded"
    )
    assert response is not None
    assert response.status == 200, (
        f"/entradas/{{id}} must return 200, got {response.status}"
    )
    body = page.content()
    assert animal_id in body, (
        f"detail page must show the animal_id {animal_id!r}"
    )


# --- 5. edit ---------------------------------------------------------------


def test_edit_entrada_updates_origen_and_redirects_to_detail(
    authenticated_session: tuple[Page, str],
    base_url: str,
    animal_id_factory: Callable[[], str],
) -> None:
    """Edit form: change origen -> submit -> 303 to detail with new origen.

    Pins the edit path end-to-end: GET ``/entradas/{id}/edit`` renders
    the prefilled form (csrf_token + pre-filled values), POST
    ``/entradas/{id}/update`` returns 303 to ``/entradas/{id}``, and
    the detail page shows the updated ``origen``.
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    fecha = "2026-06-25"
    new_origen = f"Origen-Editado-{uuid.uuid4().hex[:8]}"

    # Create the entrada first (fail-closed).
    _visit_entradas_form(page, base_url, entrada_id=None)
    create_response = page.request.post(
        f"{base_url}/entradas",
        form={"csrf_token": csrf_token, **entrada_form_data(
            animal_id=animal_id,
            fecha_entrada=fecha,
            origen="Origen-Inicial",
        )},
        max_redirects=0,
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    entrada_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert entrada_id

    # Visit the edit form (regression sentinel — form renders + csrf present).
    edit_csrf = _visit_entradas_form(page, base_url, entrada_id=entrada_id)

    # POST /entradas/{id}/update with a new origen. All other fields
    # stay the same so the update is minimal.
    update_response = page.request.post(
        f"{base_url}/entradas/{entrada_id}/update",
        form={"csrf_token": edit_csrf, **entrada_form_data(
            animal_id=animal_id,
            fecha_entrada=fecha,
            origen=new_origen,
        )},
        max_redirects=0,
    )
    assert update_response.status == 303, (
        f"edit POST must return 303, got {update_response.status}: "
        f"{update_response.text()[:300]!r}"
    )
    assert update_response.headers.get("location", "").endswith(
        f"/entradas/{entrada_id}"
    ), (
        f"edit POST must redirect to /entradas/{{entrada_id}}, "
        f"got location={update_response.headers.get('location')!r}"
    )

    # Follow the redirect and verify the detail page shows the new origen.
    detail_response = page.goto(
        f"{base_url}/entradas/{entrada_id}", wait_until="domcontentloaded"
    )
    assert detail_response is not None and detail_response.status == 200
    body = page.content()
    assert new_origen in body, (
        f"detail page must show the updated origen {new_origen!r}"
    )


# --- 6. delete -------------------------------------------------------------


def test_soft_delete_entrada_removes_from_list(
    authenticated_session: tuple[Page, str],
    base_url: str,
    animal_id_factory: Callable[[], str],
) -> None:
    """POST /entradas/{id}/delete -> 303 to /entradas; entrada gone from list.

    Pins the soft-delete contract end-to-end: create -> delete ->
    redirect -> list no longer contains the entrada. Confirm dialogs
    are handled inside the browser context (Playwright auto-accepts
    in synchronous scripts; the original test registered a
    one-shot listener for completeness).
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    fecha = "2026-06-25"

    # Create the entrada (fail-closed).
    _visit_entradas_form(page, base_url, entrada_id=None)
    create_response = page.request.post(
        f"{base_url}/entradas",
        form={"csrf_token": csrf_token, **entrada_form_data(
            animal_id=animal_id,
            fecha_entrada=fecha,
        )},
        max_redirects=0,
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    entrada_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert entrada_id

    # Visit the detail page to grab its csrf_token (regression sentinel
    # — the detail page renders the delete form with the token; this
    # also confirms the detail page is reachable before we delete).
    detail_response = page.goto(
        f"{base_url}/entradas/{entrada_id}", wait_until="domcontentloaded"
    )
    assert detail_response is not None and detail_response.status == 200
    delete_csrf = csrf_token_from_form(page)

    # Auto-accept any confirm dialog the delete form raises.
    page.on("dialog", lambda dialog: dialog.accept())

    # Submit delete. The detail page's delete form has the correct
    # ``action="/entradas/{id}/delete"`` so this is a form-encoded
    # POST to the right endpoint.
    delete_response = page.request.post(
        f"{base_url}/entradas/{entrada_id}/delete",
        form={"csrf_token": delete_csrf},
        max_redirects=0,
    )
    assert delete_response.status == 303, (
        f"delete POST must return 303, got {delete_response.status}"
    )
    assert delete_response.headers.get("location", "").endswith("/entradas"), (
        f"delete POST must redirect to /entradas, got location="
        f"{delete_response.headers.get('location')!r}"
    )

    # Verify the entrada is gone from the list (the entradas table hides
    # ``activo=false`` rows per ``list_entradas`` in
    # ``app/modules/entradas/service.py``).
    list_response = page.goto(
        f"{base_url}/entradas", wait_until="domcontentloaded"
    )
    assert list_response is not None and list_response.status == 200
    body = page.content()
    assert entrada_id not in body, (
        f"deleted entrada id {entrada_id!r} must not appear in /entradas"
    )


# --- 7. future fecha_entrada -----------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "issue #1296: POST /entradas accepts a future fecha_entrada (303 and the "
        "row is persisted); the contract says 4xx, and the gap is either a "
        "missing validation or an undocumented P1-fidelity decision"
    ),
)
def test_create_with_future_fecha_returns_422(
    authenticated_session: tuple[Page, str],
    base_url: str,
    animal_id_factory: Callable[[], str],
) -> None:
    """Submit entrada with future fecha_entrada -> expect 4xx.

    Pinned as ``xfail(strict=True)`` against issue #1296, never as a skip:
    the gate's contract forbids conditional skips, and the assertion keeps
    stating the documented contract. Fixing the gap — or deciding that the
    legacy allowed a future date and pinning that behaviour — turns this
    into ``XPASS`` and forces the marker's withdrawal, so the hole cannot be
    forgotten.

    ``app/modules/entradas/service.py`` does not validate that
    ``fecha_entrada`` is in the past, so today the request answers 303 and
    the row is persisted. The bogus fecha is one year ahead so it can never
    drift into the past.
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    future_fecha = (date.today() + timedelta(days=365)).isoformat()

    response = page.request.post(
        f"{base_url}/entradas",
        form={"csrf_token": csrf_token, **entrada_form_data(
            animal_id=animal_id,
            fecha_entrada=future_fecha,
        )},
        max_redirects=0,
    )

    if response.status == 422:
        body = response.text()
        assert ENTRADA_SAVE_FAILED_SPANISH in body, (
            f"422 response must carry the Spanish form error header, "
            f"got body excerpt: {body[:500]!r}"
        )
        return

    # Findings channel for the parent: the route accepted the future
    # date — no validation exists today. The assertion stays as the
    # contract states (4xx); the test fails hard with the captured
    # status + body excerpt so the parent can decide between
    # ``xfail`` and tightening the contract to the actual
    # behaviour.
    raise AssertionError(
        "Future fecha_entrada was accepted by the route — the entradas "
        f"service does not validate that fecha_entrada is in the past. "
        f"Captured status={response.status}; body excerpt="
        f"{response.text()[:500]!r}. Add a check in "
        f"app/modules/entradas/service.py::_validate_references or "
        f"in the EntradaForm Pydantic model to close this gap-of-fidelity."
    )
