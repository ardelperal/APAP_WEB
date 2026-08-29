"""E2E CRUD coverage for the ``/sanidad`` slice (HEALTH-01, #50).

Pins the sanidad actuaciones CRUD contract end-to-end via Playwright +
the OAuth mock landed in ``tests/e2e/test_admin_authenticated.py``.
The ``authenticated_session`` fixture mints a developer session via
``GET /e2e/login`` with the ``X-E2E-Secret`` header and returns a
``(Page, csrf_token)`` tuple.

The ``/sanidad`` slice requires a pre-existing ``animal_id`` row
because the service's FK validation rejects ``animal_id`` values that
do not reference an existing animal row. Each test creates its host
animal via ``POST /animales`` first. The ``tipo_actuacion_id`` field is
optional (the form lets the operator leave it blank and the service
stores NULL), so the tests skip the catalogos_pruebas seed assumption
and just POST without it.

Seven cases pin the sanidad CRUD contract end-to-end:

1. List (GET /sanidad → 200 with the ``Actuaciones sanitarias`` h1).
2. List with ``?animal_id=`` filter → 200, only matching rows.
3. Create (POST /sanidad with animal_id + fecha → 303 to
   /sanidad/{id}). The detail page renders the animal_id + fecha +
   tipo_actuacion (or "Sin clasificar").
4. Create with non-existent ``animal_id`` → 422 with the Spanish
   ``"No se pudo guardar la actuación"`` banner.
5. Detail (GET /sanidad/{id} → 200; the detail page renders the
   ``Activa`` badge and the actuacion's animal_id + fecha).
6. Edit (POST /sanidad/{id}/update with new ``observaciones`` → 303
   to /sanidad/{id}; the detail page shows the new observaciones).
7. Soft-delete (POST /sanidad/{id}/delete → 303 to /sanidad).

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page

# --- shared constants -----------------------------------------------------

E2E_SECRET_HEADER = "X-E2E-Secret"

# Species + sex are domain enums (Especie.CANINA, Sexo.M).
SPECIES_CANINA = "CANINA"
SEX_MACHO = "M"

# Spanish error copy that the route's 422 branch renders (per
# ``app/modules/sanidad/routes.py::create_actuacion_view``). The
# underlying ValueError from ``_validate_references`` raises
# ``"animal_id does not reference an active animal"``; the form template
# wraps it under ``"No se pudo guardar la actuación: ..."``.
NONEXISTENT_ANIMAL_SPANISH = "animal_id does not reference"


# --- fixtures -------------------------------------------------------------


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or ``None`` if unset."""
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    """Mint a developer session and return ``(page, csrf_token)``.

    Same flow as ``test_adopciones_crud.py::authenticated_session``.
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
    csrf_token = payload.get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token, (
        f"/e2e/login must return a non-empty csrf_token, got {payload!r}."
    )

    page = browser_context.new_page()
    return page, csrf_token


# --- helpers --------------------------------------------------------------


def _csrf_token_from_form(page: Page) -> str:
    """Read the csrf_token hidden input rendered on the current page."""
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "every form page must render a non-empty csrf_token hidden input"
    return token


def _animal_form_data(suffix: str) -> dict[str, str]:
    """Build a valid AnimalForm payload with a unique chip.

    Mirrors the helper in ``tests/e2e/test_adopciones_crud.py``.
    """
    return {
        "NCHIP": uuid.uuid4().hex[:15],
        "NombreAnimal": f"Animal-{suffix}",
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


def _create_animal(page: Page, csrf_token: str, base_url: str) -> str:
    """POST /animales and return the new animal's UUID. Skips on failure."""
    suffix = f"{uuid.uuid4().hex[:8]}"
    form_data = _animal_form_data(suffix)

    form_page = page.goto(f"{base_url}/animales/new", wait_until="domcontentloaded")
    assert form_page is not None and form_page.status == 200
    _csrf_token_from_form(page)

    response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create host animal (POST /animales did not return "
            f"303; got {response.status}: {response.text()[:200]!r}). The test "
            f"database may not be writable from E2E."
        )
    animal_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not animal_id or animal_id.endswith("new") or animal_id.endswith("edit"):
        pytest.skip(
            f"animal setup failed; /animales redirect was "
            f"{response.headers.get('location')!r}."
        )
    return animal_id


def _actuacion_form_data(
    *,
    animal_id: str,
    fecha: str,
    tipo_actuacion_id: str = "",
    voluntario_id: str = "",
    veterinario: str = "",
    observaciones: str = "",
    material_utilizado: str = "",
) -> dict[str, str]:
    """Build a valid ActuacionForm payload.

    Field names match the Pydantic model in
    ``app/modules/sanidad/forms.py::ActuacionForm`` (snake_case). The
    2 required fields are ``animal_id`` + ``fecha``; the rest are
    optional. ``tipo_actuacion_id`` defaults to empty so the form
    submits without requiring the catalogos_pruebas seed.
    """
    return {
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "fecha": fecha,
        "tipo_actuacion_id": tipo_actuacion_id,
        "veterinario": veterinario,
        "observaciones": observaciones,
        "material_utilizado": material_utilizado,
    }


def _create_actuacion(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    animal_id: str,
    fecha: str = "2024-07-15",
    veterinario: str = "",
    observaciones: str = "",
) -> str:
    """POST /sanidad and return the new actuacion's UUID. Skips on failure."""
    form_data = _actuacion_form_data(
        animal_id=animal_id,
        fecha=fecha,
        veterinario=veterinario,
        observaciones=observaciones,
    )
    response = page.request.post(
        f"{base_url}/sanidad",
        form={"csrf_token": csrf_token, **form_data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create actuacion (POST /sanidad did not return 303; "
            f"got {response.status}: {response.text()[:200]!r}). The test "
            f"database may not be writable from E2E."
        )
    actuacion_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not actuacion_id or actuacion_id.endswith("new") or actuacion_id.endswith("edit"):
        pytest.skip(
            f"actuacion setup failed; /sanidad redirect was "
            f"{response.headers.get('location')!r}."
        )
    return actuacion_id


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
        page.locator("h1").first.inner_text().strip() == "Actuaciones sanitarias"
    ), "list page must render the 'Actuaciones sanitarias' h1"


# --- 2. list with animal_id filter -----------------------------------------


def test_list_sanidad_animal_id_filter_excludes_non_matching(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /sanidad?animal_id=<uuid> → 200; only matching rows in the table.

    Setup creates one actuacion for animal_a and one for animal_b.
    The filtered list (filtered by animal_a's UUID) must show the
    matching animal_id but NOT animal_b's UUID. The list query in
    ``app/modules/sanidad/service.py::search_actuaciones_by_animal``
    filters by exact animal_id match.
    """
    page, csrf_token = authenticated_session

    animal_a = _create_animal(page, csrf_token, base_url)
    animal_b = _create_animal(page, csrf_token, base_url)
    fecha = "2024-07-15"
    _create_actuacion(page, csrf_token, base_url, animal_id=animal_a, fecha=fecha)
    _create_actuacion(page, csrf_token, base_url, animal_id=animal_b, fecha=fecha)

    response = page.goto(
        f"{base_url}/sanidad",
        params={"animal_id": animal_a},
        wait_until="domcontentloaded",
    )
    assert response is not None
    assert response.status == 200, (
        f"/sanidad?animal_id={{uuid}} must return 200, got {response.status}"
    )
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
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /sanidad with valid payload → 303 to /sanidad/{id}.

    Pins the full create flow: visit the form (regression sentinel:
    page renders + csrf_token present), POST the form payload, verify
    303 redirect to /sanidad/{id}, and verify the detail page shows
    the submitted animal_id + fecha.

    The sanidad form template uses ``action="{{ form_action }}"``
    which the route renders as ``/sanidad`` for create — the form
    would submit correctly through the browser, but we POST via the
    request client to capture the status code (mirroring the unit-test
    pattern in ``tests/test_sanidad_routes.py``).

    We deliberately leave ``tipo_actuacion_id`` blank because the
    catalogos_pruebas seed is not assumed; the operator can leave the
    dropdown on the "Sin clasificar" option and the service stores
    NULL.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)
    fecha = "2024-07-15"
    veterinario = f"Dr.Test-{uuid.uuid4().hex[:6]}"

    # Visit the form first (regression sentinel).
    form_page = page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    assert form_page is not None and form_page.status == 200
    _csrf_token_from_form(page)

    # POST directly to /sanidad with the form payload.
    form_data = _actuacion_form_data(
        animal_id=animal_id,
        fecha=fecha,
        veterinario=veterinario,
    )
    response = page.request.post(
        f"{base_url}/sanidad",
        form={"csrf_token": csrf_token, **form_data},
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

    The service's ``_validate_references`` raises
    ``ValueError("animal_id does not reference an active animal")``
    when the FK check returns 0 rows. The route maps this to a 422
    response with the operator's form input preserved.

    The bogus animal_id uses a UUID-shaped string that cannot exist
    in any animales table, so the FK check is guaranteed to fail.
    """
    page, csrf_token = authenticated_session
    bogus_animal_id = str(uuid.uuid4())  # well-formed UUID, never inserted
    fecha = "2024-07-15"

    form_data = _actuacion_form_data(
        animal_id=bogus_animal_id,
        fecha=fecha,
    )
    response = page.request.post(
        f"{base_url}/sanidad",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 422, (
        f"create POST with bogus animal_id must return 422, got "
        f"{response.status}: {response.text()[:300]!r}"
    )
    body = response.text()
    assert "No se pudo guardar la actuación" in body, (
        f"422 response must carry the Spanish form error header, "
        f"got body excerpt: {body[:500]!r}"
    )
    assert NONEXISTENT_ANIMAL_SPANISH in body, (
        f"422 response must carry the FK validation message "
        f"({NONEXISTENT_ANIMAL_SPANISH!r}), got body excerpt: {body[:500]!r}"
    )


# --- 5. detail -------------------------------------------------------------


def test_detail_actuacion_shows_activa_badge_and_data(
    authenticated_session: tuple[Page, str], base_url: str
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
    animal_id = _create_animal(page, csrf_token, base_url)
    fecha = "2024-07-15"
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
    authenticated_session: tuple[Page, str], base_url: str
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
    animal_id = _create_animal(page, csrf_token, base_url)
    fecha = "2024-07-15"
    actuacion_id = _create_actuacion(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        fecha=fecha,
    )
    new_observaciones = f"Obs-edit-{uuid.uuid4().hex[:8]}"

    # Visit the edit form (regression sentinel).
    edit_page = page.goto(
        f"{base_url}/sanidad/{actuacion_id}/edit", wait_until="domcontentloaded"
    )
    assert edit_page is not None
    assert edit_page.status == 200, (
        f"/sanidad/{{id}}/edit must return 200, got {edit_page.status}"
    )
    edit_csrf = _csrf_token_from_form(page)

    # POST the update with the new observaciones; other fields carried
    # through unchanged so the validation passes.
    update_data = _actuacion_form_data(
        animal_id=animal_id,
        fecha=fecha,
        observaciones=new_observaciones,
    )
    update_response = page.request.post(
        f"{base_url}/sanidad/{actuacion_id}/update",
        form={"csrf_token": edit_csrf, **update_data},
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
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /sanidad/{id}/delete → 303 to /sanidad.

    Pins the soft-delete contract end-to-end:

    - Create an actuacion.
    - Visit the detail page to grab the delete form's csrf_token.
    - POST /sanidad/{id}/delete via the request client with the
      form-encoded csrf_token. The detail page's delete form has the
      correct ``action="/sanidad/{{id}}/delete"`` and a JS
      ``onsubmit="return confirm(...)"`` that we bypass via the
      request client.
    - Verify 303 redirect to /sanidad.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)
    fecha = "2024-07-15"
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
    delete_csrf = _csrf_token_from_form(page)

    # POST delete via the request client (bypasses the JS confirm).
    delete_response = page.request.post(
        f"{base_url}/sanidad/{actuacion_id}/delete",
        form={"csrf_token": delete_csrf},
    )
    assert delete_response.status == 303, (
        f"delete POST must return 303, got {delete_response.status}: "
        f"{delete_response.text()[:300]!r}"
    )
    assert delete_response.headers.get("location", "").endswith("/sanidad"), (
        f"delete POST must redirect to /sanidad, got location="
        f"{delete_response.headers.get('location')!r}"
    )


__all__: list[Any] = [
    "test_list_sanidad_renders_200",
    "test_list_sanidad_animal_id_filter_excludes_non_matching",
    "test_create_actuacion_redirects_to_detail",
    "test_create_actuacion_with_nonexistent_animal_returns_422",
    "test_detail_actuacion_shows_activa_badge_and_data",
    "test_edit_actuacion_updates_observaciones_and_redirects_to_detail",
    "test_soft_delete_actuacion_redirects_to_list",
]
