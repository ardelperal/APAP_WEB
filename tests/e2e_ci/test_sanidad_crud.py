"""E2E CRUD coverage for the ``/sanidad`` slice under the CI browser gate.

Port of ``tests/e2e/test_sanidad_crud.py`` (issue #1095, slice 3) so the
fail-closed CI smoke suite (``tests/e2e_ci/``) actually exercises the
clinical-actuaciones (HEALTH-01) business flow instead of skipping on
every assertion.

Seven cases pin the sanidad CRUD contract end-to-end:

1. List (GET /sanidad → 200 with the ``Actuaciones sanitarias`` h1).
2. List with ``?animal_id=`` filter → 200, only matching rows.
3. Create (POST /sanidad with animal_id + fecha → 303 to
   /sanidad/{id}). The detail page renders the animal_id + fecha +
   veterinarian. ``tipo_actuacion_id`` is left blank so the test
   does not assume the ``catalogos_pruebas`` seed is populated; the
   service stores NULL and the detail page renders "Sin clasificar".
4. Create with non-existent ``animal_id`` → 422 with the Spanish
   ``"No se pudo guardar la actuación"`` banner. Sanidad's guard lives in
   its lifecycle gate, so the sentence is its own
   (``SANIDAD_NONEXISTENT_ANIMAL_SPANISH``: ``"debe apuntar a un animal
   activo"``), not the ``NONEXISTENT_ANIMAL_SPANISH`` copy the modules
   with an FK pre-check produce.
5. Detail (GET /sanidad/{id} → 200; the detail page renders the
   ``Activa`` badge and the actuacion's animal_id + fecha +
   veterinarian).
6. Edit (POST /sanidad/{id}/update with new ``observaciones`` → 303
   to /sanidad/{id}; the detail page shows the new observaciones).
7. Soft-delete (POST /sanidad/{id}/delete → 303 to /sanidad; the
   row is deactivated — the list query filters on
   ``activo = true`` per ``_LIST_ACTUACIONES_SANITARIAS_SQL`` in
   ``app/modules/sanidad/service.py``, so a soft-deleted row stops
   appearing in the list — the natural contract for the operator
   surface).

The shared helpers (``animal_form_data``, ``csrf_token_from_form``,
``unique_chip``, ``actuacion_form_data``, Spanish fragments) live in
``tests/e2e_ci/_crud_helpers.py``; the session fixture and factories
(``authenticated_session``, ``animal_id_factory``) live in
``tests/e2e_ci/conftest.py``.

Fail-closed contract: under this gate a missing
``APAP_E2E_AUTH_SECRET``, a failed /e2e/login, or a non-303 on a happy
path is a HARD failure, never a skip.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date

from playwright.sync_api import Page

from tests.e2e_ci._crud_helpers import (
    SANIDAD_NONEXISTENT_ANIMAL_SPANISH,
    SANIDAD_SAVE_FAILED_SPANISH,
    actuacion_form_data,
    csrf_token_from_form,
)

# Slice 3 — D-24 regla 3 nuance. The original ``tests/e2e/test_sanidad_crud.py``
# test battery used ``fecha = "2024-07-15"`` for every actuacion. Under
# the real DB in the e2e_ci gate (where ``animal_id_factory`` creates a
# brand-new animal with ``fecha_alta = now()``), that fecha falls BEFORE
# the animal's ``fecha_alta``, so the CTE's regla 3 filter rejects the
# INSERT and the disambiguation path runs — at which point the
# original's ``pytest.skip`` on a non-303 would have masked the gap.
# Under the e2e_ci gate the skip is forbidden, so the happy-path tests
# must use a fecha that satisfies regla 3
# (``fecha >= animales.fecha_alta::date``). Today's date always
# satisfies it against a fresh animal. The 422 test
# (``test_create_actuacion_with_nonexistent_animal_returns_422``) keeps
# the original fecha literal so the documented natural contract is the
# one the user asked for an empirical answer on.
_FECHA_DEFAULT = date.today().isoformat()

# --- helpers --------------------------------------------------------------


def _visit_sanidad_form(
    page: Page, base_url: str, actuacion_id: str | None
) -> str:
    """Navigate to the sanidad new/edit form and return its csrf_token.

    When ``actuacion_id`` is ``None`` the test goes to
    ``/sanidad/new``; otherwise to
    ``/sanidad/{actuacion_id}/edit``. The form template is shared
    between new and edit (same URL pattern but pre-filled when
    editing).

    Mirrors ``test_animales_crud.py::_visit_animal_form`` (slice 1),
    ``test_entradas_crud.py::_visit_entradas_form`` (slice 2), and
    ``test_adopciones_crud.py::_visit_adopcion_form`` (slice 3).
    """
    if actuacion_id is None:
        path = "/sanidad/new"
    else:
        path = f"/sanidad/{actuacion_id}/edit"
    response = page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200, f"{path} must return 200, got {response.status}"
    return csrf_token_from_form(page)


# --- 1. list ---------------------------------------------------------------


def test_list_sanidad_renders_200(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /sanidad → 200 with the ``Actuaciones sanitarias`` h1.

    Pins the list surface: either the ``<table>`` OR the empty-state
    card is a valid contract — both render on a 200 response. The h1
    assertion confirms the route rendered (not an error page).
    """
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/sanidad", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, f"/sanidad must return 200, got {response.status}"
    assert (
        page.locator("h1").first.inner_text().strip()
        == "Actuaciones sanitarias"
    ), "list page must render the 'Actuaciones sanitarias' h1"


# --- 2. list with animal_id filter -----------------------------------------


def test_list_sanidad_animal_id_filter_excludes_non_matching(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """GET /sanidad?animal_id=<uuid> → 200; only matching rows in the table.

    Setup creates one actuacion for animal_a and one for animal_b.
    The filtered list (filtered by animal_a's UUID) must show the
    matching animal_id but NOT animal_b's UUID. The list query in
    ``app/modules/sanidad/service.py::search_actuaciones_by_animal``
    filters by exact animal_id match.
    """
    page, csrf_token = authenticated_session

    animal_a = animal_id_factory()
    animal_b = animal_id_factory()
    # D-24 regla 3: today's date satisfies the CTE filter against a
    # fresh animal; see module-level ``_FECHA_DEFAULT``.
    fecha = _FECHA_DEFAULT
    _create_actuacion(
        page, csrf_token, base_url, animal_id=animal_a, fecha=fecha
    )
    _create_actuacion(
        page, csrf_token, base_url, animal_id=animal_b, fecha=fecha
    )

    # ``Page.goto`` has no ``params`` kwarg — use the request client
    # so the query string is properly encoded, then follow into the
    # rendered page so ``page.content()`` reflects the filtered
    # server-side list. Mirrors the slice 1 animales search test.
    filter_response = page.request.get(
        f"{base_url}/sanidad",
        params={"animal_id": animal_a},
    )
    assert filter_response is not None
    assert filter_response.status == 200, (
        f"/sanidad?animal_id={{uuid}} must return 200, got {filter_response.status}"
    )
    rendered = page.goto(
        f"{base_url}/sanidad?animal_id={animal_a}",
        wait_until="domcontentloaded",
    )
    assert rendered is not None and rendered.status == 200
    body = page.content()
    assert animal_a in body, (
        f"matching animal_id {animal_a!r} must appear in the filtered list; "
        f"body excerpt: {body[:500]!r}"
    )
    assert animal_b not in body, (
        f"non-matching animal_id {animal_b!r} must NOT appear in the filtered "
        f"list; body excerpt: {body[:500]!r}"
    )


# --- 3. create -------------------------------------------------------------


def test_create_actuacion_redirects_to_detail(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /sanidad with valid payload → 303 to /sanidad/{id}.

    Pins the full create flow: visit the form (regression sentinel:
    page renders + csrf_token present), POST the form payload, verify
    303 redirect to /sanidad/{id}, and verify the detail page shows
    the submitted animal_id + fecha + veterinario.

    We deliberately leave ``tipo_actuacion_id`` blank because the
    catalogos_pruebas seed is not assumed; the service stores NULL,
    and the detail template renders "Sin clasificar" in the Tipo
    block (the assertion pins the data fields, not the catalog
    block, so the catalog path is left untested when no row is
    referenced — see the empirical-answer note in the task).
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    # See module-level _FECHA_DEFAULT comment.
    fecha = _FECHA_DEFAULT
    veterinario = f"Dr.Test-{uuid.uuid4().hex[:6]}"

    # Visit the form first (regression sentinel).
    _visit_sanidad_form(page, base_url, actuacion_id=None)

    # POST directly to /sanidad with the form payload.
    form_data = actuacion_form_data(
        animal_id=animal_id,
        fecha=fecha,
        veterinario=veterinario,
    )
    response = page.request.post(
        f"{base_url}/sanidad",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )
    assert response.status == 303, (
        f"create POST must return 303, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/sanidad/"), (
        f"create POST must redirect to /sanidad/{{id}}, got {location!r}"
    )
    actuacion_id = location.rsplit("/", 1)[-1]
    assert (
        actuacion_id
        and not actuacion_id.endswith("new")
        and not actuacion_id.endswith("edit")
    ), f"create POST must not redirect back to a form URL: {location!r}"

    # Follow the redirect and verify the detail page shows the submitted
    # animal_id + fecha + veterinario.
    detail = page.goto(
        f"{base_url}/sanidad/{actuacion_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert animal_id in body, (
        f"detail page must show the submitted animal_id {animal_id!r}"
    )
    assert fecha in body, (
        f"detail page must show the submitted fecha {fecha!r}"
    )
    assert veterinario in body, (
        f"detail page must show the submitted veterinario {veterinario!r}"
    )


# --- 4. create with non-existent animal_id → 422 ---------------------------


def test_create_actuacion_with_nonexistent_animal_returns_422(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /sanidad with bogus ``animal_id`` → 422 + Spanish error.

    The service's ``_raise_validation_error`` raises ``ValueError``
    when the FK check returns 0 rows (the disambiguation path reads
    the animales table and finds no row by that id, raising
    ``animal_id debe apuntar a un animal activo
    (no encontrado: ...)``). The route maps this to a 422 response
    with the operator's form input preserved and prepends
    ``"No se pudo guardar la actuación: ..."`` to the message.

    The assertion pins ``SANIDAD_NONEXISTENT_ANIMAL_SPANISH``
    (``"debe apuntar a un animal activo"``), the sentence the lifecycle
    gate actually produces. The original battery asserted the
    ``NONEXISTENT_ANIMAL_SPANISH`` copy (``"animal_id does not
    reference"``) that the FK pre-check emits in other modules; that copy
    never reached this one, and issue #1298 — the drifted column name that
    turned this very path into a 502 — is what made it visible.

    The bogus animal_id uses a UUID-shaped string that cannot exist
    in any animales table, so the FK check is guaranteed to fail.
    """
    page, csrf_token = authenticated_session
    bogus_animal_id = str(uuid.uuid4())  # well-formed UUID, never inserted
    fecha = "2024-07-15"

    form_data = actuacion_form_data(
        animal_id=bogus_animal_id,
        fecha=fecha,
    )
    response = page.request.post(
        f"{base_url}/sanidad",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )

    assert response.status == 422, (
        f"create POST with bogus animal_id must return 422, got "
        f"{response.status}: {response.text()[:300]!r}"
    )
    body = response.text()
    assert SANIDAD_SAVE_FAILED_SPANISH in body, (
        f"422 response must carry the Spanish form error header, "
        f"got body excerpt: {body[:500]!r}"
    )
    assert SANIDAD_NONEXISTENT_ANIMAL_SPANISH in body, (
        f"422 response must name the animal in the Spanish message "
        f"({SANIDAD_NONEXISTENT_ANIMAL_SPANISH!r}), "
        f"got body excerpt: {body[:500]!r}"
    )


# --- 5. detail -------------------------------------------------------------


def test_detail_actuacion_shows_activa_badge_and_data(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """GET /sanidad/{id} → 200; ``Activa`` badge + actuacion data visible.

    For an active actuacion (``activo=True``), the detail template
    renders ``"Activa"`` in the Estado block. The Datos del acto +
    Responsable sections render ``animal_id``, ``fecha``,
    ``veterinario``, and ``material_utilizado``.

    The ``Activa`` badge is the regression sentinel for the active
    detail surface. The data fields are pinned so the form-to-detail
    path is verified end-to-end.
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    # See module-level _FECHA_DEFAULT comment.
    fecha = _FECHA_DEFAULT
    veterinario = f"Dr.Detail-{uuid.uuid4().hex[:6]}"
    actuacion_id = _create_actuacion(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        fecha=fecha,
        veterinario=veterinario,
    )

    response = page.goto(
        f"{base_url}/sanidad/{actuacion_id}", wait_until="domcontentloaded"
    )
    assert response is not None
    assert response.status == 200, (
        f"/sanidad/{{id}} must return 200, got {response.status}"
    )
    body = page.content()
    assert "Activa" in body, (
        f"active actuacion detail page must render the 'Activa' Estado "
        f"badge; body excerpt: {body[:500]!r}"
    )
    assert animal_id in body, (
        f"detail page must show the animal_id {animal_id!r}"
    )
    assert fecha in body, (
        f"detail page must show the fecha {fecha!r}"
    )
    assert veterinario in body, (
        f"detail page must show the veterinario {veterinario!r}"
    )


# --- 6. edit ---------------------------------------------------------------


def test_edit_actuacion_updates_observaciones_and_redirects_to_detail(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /sanidad/{id}/update with new observaciones → 303 to detail.

    Pins the edit path end-to-end:

    - Create an actuacion with empty observaciones.
    - Visit the edit form (regression sentinel: page renders + csrf
      present).
    - POST /sanidad/{id}/update with new observaciones (all other
      fields carried through unchanged so the validation passes).
    - Verify 303 redirect to /sanidad/{id}.
    - Verify the detail page shows the new observaciones.

    The update endpoint re-runs FK validation on the incoming form
    values, so the animal_id must still reference an active animal.
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    # See module-level _FECHA_DEFAULT comment.
    fecha = _FECHA_DEFAULT
    actuacion_id = _create_actuacion(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        fecha=fecha,
    )
    new_observaciones = f"Obs-edit-{uuid.uuid4().hex[:8]}"

    # Visit the edit form (regression sentinel: page renders + csrf present).
    edit_csrf = _visit_sanidad_form(page, base_url, actuacion_id=actuacion_id)

    # POST the update with the new observaciones; other fields carried
    # through unchanged so the validation passes.
    update_data = actuacion_form_data(
        animal_id=animal_id,
        fecha=fecha,
        observaciones=new_observaciones,
    )
    update_response = page.request.post(
        f"{base_url}/sanidad/{actuacion_id}/update",
        form={"csrf_token": edit_csrf, **update_data},
        max_redirects=0,
    )
    assert update_response.status == 303, (
        f"update POST must return 303, got {update_response.status}: "
        f"{update_response.text()[:300]!r}"
    )
    assert update_response.headers.get("location", "").endswith(
        f"/sanidad/{actuacion_id}"
    ), (
        f"update POST must redirect to /sanidad/{{id}}, got location="
        f"{update_response.headers.get('location')!r}"
    )

    # Follow the redirect and verify the detail page shows the new
    # observaciones.
    detail = page.goto(
        f"{base_url}/sanidad/{actuacion_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert new_observaciones in body, (
        f"detail page must show the updated observaciones "
        f"{new_observaciones!r}; body excerpt: {body[:500]!r}"
    )


# --- 7. soft-delete --------------------------------------------------------


def test_soft_delete_actuacion_redirects_to_list(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /sanidad/{id}/delete → 303 to /sanidad.

    Pins the soft-delete contract end-to-end:

    - Create an actuacion.
    - Visit the detail page to grab the delete form's csrf_token.
    - POST /sanidad/{id}/delete via the request client with the
      form-encoded csrf_token. The detail page's delete form has the
      correct ``action="/sanidad/{id}/delete"`` and a JS
      ``onsubmit="return confirm(...)"`` that we bypass via the
      request client.
    - Verify 303 redirect to /sanidad.
    """
    page, csrf_token = authenticated_session
    animal_id = animal_id_factory()
    # See module-level _FECHA_DEFAULT comment.
    fecha = _FECHA_DEFAULT
    actuacion_id = _create_actuacion(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        fecha=fecha,
    )

    # Visit the detail page to grab the delete form's csrf_token.
    detail = page.goto(
        f"{base_url}/sanidad/{actuacion_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    delete_csrf = csrf_token_from_form(page)

    # POST delete via the request client (bypasses the JS confirm).
    delete_response = page.request.post(
        f"{base_url}/sanidad/{actuacion_id}/delete",
        form={"csrf_token": delete_csrf},
        max_redirects=0,
    )
    assert delete_response.status == 303, (
        f"delete POST must return 303, got {delete_response.status}: "
        f"{delete_response.text()[:300]!r}"
    )
    assert delete_response.headers.get("location", "").endswith("/sanidad"), (
        f"delete POST must redirect to /sanidad, got location="
        f"{delete_response.headers.get('location')!r}"
    )


# --- internal: factory helper ---------------------------------------------


def _create_actuacion(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    animal_id: str,
    fecha: str = _FECHA_DEFAULT,
    veterinario: str = "",
    observaciones: str = "",
) -> str:
    """POST /sanidad and return the new actuacion's UUID.

    Mirrors the parallel ``_create_animal`` factory but inlined here
    because the e2e_ci gate forbids the original's ``pytest.skip``
    on a non-303 POST. Under the gate a non-303 is a HARD failure so
    the factory stays loud when the DB is not writable.
    """
    form_data = actuacion_form_data(
        animal_id=animal_id,
        fecha=fecha,
        veterinario=veterinario,
        observaciones=observaciones,
    )
    response = page.request.post(
        f"{base_url}/sanidad",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )
    assert response.status == 303, (
        f"create actuacion must return 303, got {response.status}: "
        f"{response.text()[:300]!r}. The CI database must be writable "
        f"from the e2e gate."
    )
    actuacion_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    assert (
        actuacion_id
        and not actuacion_id.endswith("new")
        and not actuacion_id.endswith("edit")
    ), (
        f"create actuacion redirect was "
        f"{response.headers.get('location')!r}."
    )
    return actuacion_id
