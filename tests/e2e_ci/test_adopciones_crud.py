"""E2E CRUD coverage for the ``/adopciones`` slice under the CI browser gate.

Port of ``tests/e2e/test_adopciones_crud.py`` (issue #1095, slice 3) so the
fail-closed CI smoke suite (``tests/e2e_ci/``) actually exercises the
adoption business flow instead of skipping on every assertion.

Seven cases pin the adopciones CRUD contract end-to-end:

1. List (GET /adopciones → 200 with the ``Adopciones`` h1).
2. List with ``?adoptante=`` filter → 200, only matching rows in the
   table. The filter is a partial ILIKE on ``nombre_adoptante`` per
   ``search_adopciones_by_adoptante`` in
   ``app/modules/adopciones/service.py``.
3. Create (POST /adopciones with animal_id + fecha_adopcion +
   nombre_adoptante + tipo_adopcion → 303 to /adopciones/{id}).
4. Create with non-existent ``animal_id`` → 422 with the Spanish
   ``"No se pudo guardar la adopción"`` banner and the
   ``"animal_id does not reference"`` FK message preserved.
5. Detail (GET /adopciones/{id} → 200; the detail page renders the
   ``Vigente`` badge when ``fecha_devolucion IS NULL``).
6. Edit (POST /adopciones/{id}/update with new ``telefono_adoptante``
   → 303 to /adopciones/{id}; the detail page shows the new phone).
7. Soft-delete (POST /adopciones/{id}/delete → 303 to /adopciones;
   the adoption no longer appears in the list because the list query
   filters on ``activo = true`` per
   ``build_adopcion_list`` in ``app/modules/adopciones/queries.py``).

The shared helpers (``animal_form_data``, ``csrf_token_from_form``,
``unique_chip``, ``adopcion_form_data``, Spanish fragments, list
title constant) live in ``tests/e2e_ci/_crud_helpers.py``; the session
fixture and factories (``authenticated_session``, ``animal_id_factory``)
live in ``tests/e2e_ci/conftest.py``.

Fail-closed contract: under this gate a missing
``APAP_E2E_AUTH_SECRET``, a failed /e2e/login, or a non-303 on a happy
path is a HARD failure, never a skip.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from playwright.sync_api import Page

from tests.e2e_ci._crud_helpers import (
    ADOPCION_SAVE_FAILED_SPANISH,
    ADOPCIONES_LIST_TITLE,
    NONEXISTENT_ANIMAL_SPANISH,
    adopcion_form_data,
    csrf_token_from_form,
)

# --- helpers --------------------------------------------------------------


def _visit_adopcion_form(
    page: Page, base_url: str, adopcion_id: str | None
) -> str:
    """Navigate to the adopciones new/edit form and return its csrf_token.

    When ``adopcion_id`` is ``None`` the test goes to
    ``/adopciones/new``; otherwise to
    ``/adopciones/{adopcion_id}/edit``. The form template is shared
    between new and edit (same URL pattern but pre-filled when
    editing).

    Mirrors ``test_animales_crud.py::_visit_animal_form`` (slice 1)
    and ``test_entradas_crud.py::_visit_entradas_form`` (slice 2).
    """
    if adopcion_id is None:
        path = "/adopciones/new"
    else:
        path = f"/adopciones/{adopcion_id}/edit"
    response = page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200, f"{path} must return 200, got {response.status}"
    return csrf_token_from_form(page)


# --- 1. list ---------------------------------------------------------------


def test_list_adopciones_renders_200(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /adopciones → 200 with the ``Adopciones`` h1.

    Pins the list surface: either the ``<table>`` OR the empty-state
    card is a valid contract — both render on a 200 response. The h1
    assertion confirms the route rendered (not an error page).
    """
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/adopciones", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, f"/adopciones must return 200, got {response.status}"
    assert page.locator("h1").first.inner_text().strip() == ADOPCIONES_LIST_TITLE, (
        "list page must render the 'Adopciones' h1"
    )


# --- 2. list with adoptante filter -----------------------------------------


def test_list_adopciones_adoptante_filter_excludes_non_matching(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """GET /adopciones?adoptante=foo → 200; only matching rows in the table.

    Setup creates two adopciones with distinct ``nombre_adoptante``
    markers (uuid-suffixed to avoid collision). The filtered list
    must contain the matching nombre_adoptante but NOT the
    non-matching one. The filter is a partial ILIKE on
    ``nombre_adoptante`` per
    ``search_adopciones_by_adoptante`` in
    ``app/modules/adopciones/service.py``.

    Each row uses a distinct animal (one animal per adopcion) so the
    FK validation in ``_raise_validation_error`` is guaranteed to
    pass without sharing host animals between rows.
    """
    page, csrf_token = authenticated_session

    animal_a = animal_id_factory()
    animal_b = animal_id_factory()

    marker_a = f"FilterA-{uuid.uuid4().hex[:8]}"
    marker_b = f"FilterB-{uuid.uuid4().hex[:8]}"

    _create_adopcion(
        page,
        csrf_token,
        base_url,
        animal_id=animal_a,
        nombre_adoptante=marker_a,
    )
    _create_adopcion(
        page,
        csrf_token,
        base_url,
        animal_id=animal_b,
        nombre_adoptante=marker_b,
    )

    # GET /adopciones?adoptante=FilterA → only the matching row appears.
    # ``Page.goto`` has no ``params`` kwarg — use the request client
    # so the query string is properly encoded, then follow into the
    # rendered page so ``page.content()`` reflects the filtered
    # server-side list. Mirrors the slice 1 animales search test.
    filter_response = page.request.get(
        f"{base_url}/adopciones",
        params={"adoptante": "FilterA"},
    )
    assert filter_response is not None
    assert filter_response.status == 200, (
        f"/adopciones?adoptante=FilterA must return 200, got "
        f"{filter_response.status}"
    )
    rendered = page.goto(
        f"{base_url}/adopciones?adoptante=FilterA",
        wait_until="domcontentloaded",
    )
    assert rendered is not None and rendered.status == 200
    body = page.content()
    assert marker_a in body, (
        f"matching nombre_adoptante {marker_a!r} must appear in the filtered "
        f"list; body excerpt: {body[:500]!r}"
    )
    assert marker_b not in body, (
        f"non-matching nombre_adoptante {marker_b!r} must NOT appear in the "
        f"filtered list; body excerpt: {body[:500]!r}"
    )


# --- 3. create -------------------------------------------------------------


def test_create_adopcion_redirects_to_detail(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /adopciones with valid payload → 303 to /adopciones/{id}.

    Pins the full create flow: visit the form (regression sentinel:
    page renders + csrf_token present), POST the form payload, verify
    303 redirect to /adopciones/{id} (NOT back to /new or /edit), and
    verify the detail page shows the submitted nombre_adoptante +
    animal_id + fecha_adopcion.

    The adopciones form template uses ``action="{{ form_action }}"``
    which the route renders as ``/adopciones`` for create — the
    POST is issued via the request client so the 303 status is
    preserved (Playwright's request client follows redirects by
    default; ``max_redirects=0`` keeps the raw 303).
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    nombre_adoptante = f"Create-{uuid.uuid4().hex[:8]}"
    fecha_adopcion = "2024-06-15"

    # Visit the form first (regression sentinel).
    _visit_adopcion_form(page, base_url, adopcion_id=None)

    # POST directly to /adopciones with the form payload.
    form_data = adopcion_form_data(
        animal_id=animal_id,
        fecha_adopcion=fecha_adopcion,
        nombre_adoptante=nombre_adoptante,
        tipo_adopcion="regular",
    )
    response = page.request.post(
        f"{base_url}/adopciones",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )
    assert response.status == 303, (
        f"create POST must return 303, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/adopciones/"), (
        f"create POST must redirect to /adopciones/{{id}}, got {location!r}"
    )
    adopcion_id = location.rsplit("/", 1)[-1]
    assert (
        adopcion_id
        and not adopcion_id.endswith("new")
        and not adopcion_id.endswith("edit")
    ), f"create POST must not redirect back to a form URL: {location!r}"

    # Follow the redirect and verify the detail page shows the submitted
    # nombre_adoptante + animal_id + fecha_adopcion.
    detail = page.goto(
        f"{base_url}/adopciones/{adopcion_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert nombre_adoptante in body, (
        f"detail page must show the submitted nombre_adoptante "
        f"{nombre_adoptante!r}"
    )
    assert animal_id in body, (
        f"detail page must show the submitted animal_id {animal_id!r}"
    )
    assert fecha_adopcion in body, (
        f"detail page must show the submitted fecha_adopcion {fecha_adopcion!r}"
    )


# --- 4. create with non-existent animal_id → 422 ---------------------------


def test_create_adopcion_with_nonexistent_animal_returns_422(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /adopciones with bogus ``animal_id`` → 422 + Spanish error.

    The service's ``_raise_validation_error`` raises
    ``ValueError("animal_id does not reference an active animal")``
    when the FK check returns 0 rows. The route maps this to a 422
    response with the operator's form input preserved.

    The bogus animal_id uses a UUID-shaped string that cannot exist
    in any animales table, so the FK check is guaranteed to fail.
    """
    page, csrf_token = authenticated_session
    bogus_animal_id = str(uuid.uuid4())  # well-formed UUID, never inserted
    nombre_adoptante = f"Bogus-{uuid.uuid4().hex[:8]}"
    fecha_adopcion = "2024-06-15"

    form_data = adopcion_form_data(
        animal_id=bogus_animal_id,
        fecha_adopcion=fecha_adopcion,
        nombre_adoptante=nombre_adoptante,
    )
    response = page.request.post(
        f"{base_url}/adopciones",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )

    assert response.status == 422, (
        f"create POST with bogus animal_id must return 422, got "
        f"{response.status}: {response.text()[:300]!r}"
    )
    body = response.text()
    assert ADOPCION_SAVE_FAILED_SPANISH in body, (
        f"422 response must carry the Spanish form error header, "
        f"got body excerpt: {body[:500]!r}"
    )
    assert NONEXISTENT_ANIMAL_SPANISH in body, (
        f"422 response must carry the FK validation message "
        f"({NONEXISTENT_ANIMAL_SPANISH!r}), got body excerpt: {body[:500]!r}"
    )


# --- 5. detail -------------------------------------------------------------


def test_detail_adopcion_shows_vigente_badge_and_adoptante_info(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """GET /adopciones/{id} → 200; ``Vigente`` badge + adoptante data visible.

    For an active adopcion (``fecha_devolucion IS NULL``), the detail
    template's Estado block renders ``"Vigente"`` (because
    ``adopcion.is_active`` returns True). The Datos del adoptante +
    Datos de la adopción sections render ``nombre_adoptante``,
    ``animal_id``, ``fecha_adopcion``, and ``telefono_adoptante``.

    The ``Vigente`` badge is the regression sentinel for the active
    detail surface. The data fields are pinned so the form-to-detail
    path is verified end-to-end.
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    nombre_adoptante = f"Detail-{uuid.uuid4().hex[:8]}"
    fecha_adopcion = "2024-06-15"
    telefono = f"6{uuid.uuid4().int % 100000000:08d}"
    adopcion_id = _create_adopcion(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        fecha_adopcion=fecha_adopcion,
        nombre_adoptante=nombre_adoptante,
        telefono_adoptante=telefono,
    )

    response = page.goto(
        f"{base_url}/adopciones/{adopcion_id}", wait_until="domcontentloaded"
    )
    assert response is not None
    assert response.status == 200, (
        f"/adopciones/{{id}} must return 200, got {response.status}"
    )
    body = page.content()
    assert "Vigente" in body, (
        f"active adopcion detail page must render the 'Vigente' Estado badge; "
        f"body excerpt: {body[:500]!r}"
    )
    assert nombre_adoptante in body, (
        f"detail page must show the adoptante's nombre "
        f"{nombre_adoptante!r}"
    )
    assert animal_id in body, (
        f"detail page must show the animal_id {animal_id!r}"
    )
    assert fecha_adopcion in body, (
        f"detail page must show the fecha_adopcion {fecha_adopcion!r}"
    )
    assert telefono in body, (
        f"detail page must show the telefono_adoptante {telefono!r}"
    )


# --- 6. edit ---------------------------------------------------------------


def test_edit_adopcion_updates_telefono_and_redirects_to_detail(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /adopciones/{id}/update with new telefono_adoptante → 303 to detail.

    Pins the edit path end-to-end:

    - Create an adopcion with empty telefono_adoptante.
    - Visit the edit form (regression sentinel: page renders + csrf
      present).
    - POST /adopciones/{id}/update with new telefono_adoptante (all
      other fields carried through unchanged so the validation
      passes).
    - Verify 303 redirect to /adopciones/{id}.
    - Verify the detail page shows the new telefono_adoptante.

    Note: the adopcion form re-runs FK validation on the incoming
    form values, so the animal_id must still reference an active
    animal (it does, because we created it just above).
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    nombre_adoptante = f"Edit-{uuid.uuid4().hex[:8]}"
    fecha_adopcion = "2024-06-15"
    adopcion_id = _create_adopcion(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        fecha_adopcion=fecha_adopcion,
        nombre_adoptante=nombre_adoptante,
    )
    new_telefono = f"7{uuid.uuid4().int % 100000000:08d}"

    # Visit the edit form (regression sentinel: page renders + csrf present).
    edit_csrf = _visit_adopcion_form(page, base_url, adopcion_id=adopcion_id)

    # POST the update with the new telefono_adoptante; other fields
    # carried through unchanged so the validation passes.
    update_data = adopcion_form_data(
        animal_id=animal_id,
        fecha_adopcion=fecha_adopcion,
        nombre_adoptante=nombre_adoptante,
        telefono_adoptante=new_telefono,
    )
    update_response = page.request.post(
        f"{base_url}/adopciones/{adopcion_id}/update",
        form={"csrf_token": edit_csrf, **update_data},
        max_redirects=0,
    )
    assert update_response.status == 303, (
        f"update POST must return 303, got {update_response.status}: "
        f"{update_response.text()[:300]!r}"
    )
    assert update_response.headers.get("location", "").endswith(
        f"/adopciones/{adopcion_id}"
    ), (
        f"update POST must redirect to /adopciones/{{id}}, got location="
        f"{update_response.headers.get('location')!r}"
    )

    # Follow the redirect and verify the detail page shows the new
    # telefono_adoptante.
    detail = page.goto(
        f"{base_url}/adopciones/{adopcion_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert new_telefono in body, (
        f"detail page must show the updated telefono_adoptante "
        f"{new_telefono!r}; body excerpt: {body[:500]!r}"
    )


# --- 7. soft-delete --------------------------------------------------------


def test_soft_delete_adopcion_redirects_to_list(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /adopciones/{id}/delete → 303 to /adopciones; row no longer listed.

    Pins the soft-delete contract end-to-end:

    - Create an adopcion.
    - Visit the detail page to grab the delete form's csrf_token.
    - POST /adopciones/{id}/delete via the request client with the
      form-encoded csrf_token. The detail page's delete form has the
      correct ``action="/adopciones/{id}/delete"`` and a JS
      ``onsubmit="return confirm(...)"`` we bypass via the request
      client.
    - Verify 303 redirect to /adopciones.
    - Visit /adopciones and verify the
      ``nombre_adoptante`` marker is no longer in the list. The
      ``Adopcion.delete_adopcion`` service flips ``activo = false``
      and the ``build_adopcion_list`` query filters on
      ``activo = true`` per
      ``app/modules/adopciones/queries.py``, so a soft-deleted row
      stops appearing in the operator-facing list (unlike the
      entradas battery's "Adopcion row may still be listed"
      docstring asserts — adopciones DOES filter on ``activo``,
      unlike entradas per its legacy contract).
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    nombre_adoptante = f"Delete-{uuid.uuid4().hex[:8]}"
    fecha_adopcion = "2024-06-15"
    adopcion_id = _create_adopcion(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        fecha_adopcion=fecha_adopcion,
        nombre_adoptante=nombre_adoptante,
    )

    # Visit the detail page to grab the delete form's csrf_token.
    detail = page.goto(
        f"{base_url}/adopciones/{adopcion_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    delete_csrf = csrf_token_from_form(page)

    # POST delete via the request client (bypasses the JS confirm).
    delete_response = page.request.post(
        f"{base_url}/adopciones/{adopcion_id}/delete",
        form={"csrf_token": delete_csrf},
        max_redirects=0,
    )
    assert delete_response.status == 303, (
        f"delete POST must return 303, got {delete_response.status}: "
        f"{delete_response.text()[:300]!r}"
    )
    assert delete_response.headers.get("location", "").endswith("/adopciones"), (
        f"delete POST must redirect to /adopciones, got location="
        f"{delete_response.headers.get('location')!r}"
    )

    # Verify the adopcion is gone from the list. The list query in
    # ``build_adopcion_list`` filters on ``activo = true``; a
    # soft-deleted row therefore must NOT appear in the operator-
    # facing list (unlike the entradas legacy module).
    list_response = page.goto(
        f"{base_url}/adopciones", wait_until="domcontentloaded"
    )
    assert list_response is not None and list_response.status == 200
    body = page.content()
    assert nombre_adoptante not in body, (
        f"deleted adopcion's nombre_adoptante {nombre_adoptante!r} must not "
        f"appear in /adopciones"
    )


# --- internal: factory helper ---------------------------------------------


def _create_adopcion(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    animal_id: str,
    fecha_adopcion: str = "2024-06-15",
    nombre_adoptante: str | None = None,
    tipo_adopcion: str = "regular",
    telefono_adoptante: str = "",
    observaciones: str = "",
) -> str:
    """POST /adopciones and return the new adopcion's UUID.

    Mirrors the parallel ``_create_animal`` factory used by
    ``tests/e2e/test_adopciones_crud.py`` and (slice 1)
    ``tests/e2e_ci/test_animales_crud.py`` but inlined here because
    the e2e_ci gate forbids the original's ``pytest.skip`` on a
    non-303 POST. Under the gate a non-303 is a HARD failure so the
    factory stays loud when the DB is not writable.

    Defaults: ``fecha_adopcion="2024-06-15"`` (fixed historical date
    so assertions are reproducible). The ``nombre_adoptante``
    defaults to a uuid-suffixed marker so each test row is unique
    in the database.
    """
    if nombre_adoptante is None:
        nombre_adoptante = f"Adoptante-{uuid.uuid4().hex[:8]}"

    form_data = adopcion_form_data(
        animal_id=animal_id,
        fecha_adopcion=fecha_adopcion,
        nombre_adoptante=nombre_adoptante,
        tipo_adopcion=tipo_adopcion,
        telefono_adoptante=telefono_adoptante,
        observaciones=observaciones,
    )
    response = page.request.post(
        f"{base_url}/adopciones",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )
    assert response.status == 303, (
        f"create adopcion must return 303, got {response.status}: "
        f"{response.text()[:300]!r}. The CI database must be writable from "
        f"the e2e gate."
    )
    adopcion_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    assert (
        adopcion_id
        and not adopcion_id.endswith("new")
        and not adopcion_id.endswith("edit")
    ), (
        f"create adopcion redirect was "
        f"{response.headers.get('location')!r}."
    )
    return adopcion_id
