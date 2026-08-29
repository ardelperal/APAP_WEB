"""E2E CRUD coverage for the ``/adopciones`` slice (ADOPT-01, #47).

Pins the adopciones CRUD contract end-to-end via Playwright + the OAuth
mock landed in ``tests/e2e/test_admin_authenticated.py``. The
``authenticated_session`` fixture mints a developer session via
``GET /e2e/login`` with the ``X-E2E-Secret`` header and returns a
``(Page, csrf_token)`` tuple.

Seven cases pin the adopciones CRUD contract end-to-end:

1. List (GET /adopciones → 200 with the ``Adopciones`` h1).
2. List with ``?adoptante=`` filter → 200, only matching rows in the
   table. The filter is a partial ILIKE on ``nombre_adoptante`` per
   ``search_adopciones_by_adoptante`` in
   ``app/modules/adopciones/service.py``.
3. Create (POST /adopciones with animal_id + fecha_adopcion +
   nombre_adoptante + tipo_adopcion → 303 to /adopciones/{id}). The
   adopcion requires an existing active animal (the service's
   ``_raise_validation_error`` rejects bogus ``animal_id``), so each
   test creates its host animal via ``POST /animales`` first. The
   form template uses ``action="{{ form_action }}"`` which the route
   sets to ``/adopciones`` for create; the test still POSTs via the
   request client to capture the status code (mirroring the unit-test
   pattern in ``tests/test_adopciones_routes.py``).
4. Create with non-existent ``animal_id`` → 422 with the Spanish
   ``"No se pudo guardar la adopción"`` banner and the
   ``"animal_id does not reference"`` FK message preserved.
5. Detail (GET /adopciones/{id} → 200; the detail page renders the
   ``Vigente`` badge when ``fecha_devolucion IS NULL`` and the
   adoptante's nombre_adoptante + animal_id are visible).
6. Edit (POST /adopciones/{id}/update with new ``telefono_adoptante``
   → 303 to /adopciones/{id}; the detail page shows the new phone).
7. Soft-delete (POST /adopciones/{id}/delete → 303 to /adopciones;
   the row is deactivated — the ``Adopcion.delete_adopcion`` service
   flips ``activo = false`` and the row stays visible in the list per
   the ``build_adopcion_list`` query's lack of an ``activo`` filter
   for legacy compat).

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset (the
OAuth mock cannot authenticate). Each adopcion uses a uuid-suffixed
nombre + telefono to avoid collisions with other rows that may exist
in the test database.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page

# --- shared constants -----------------------------------------------------

E2E_SECRET_HEADER = "X-E2E-Secret"

# Species + sex are domain enums (Especie.CANINA, Sexo.M) — the legacy
# form carries them as uppercase strings. The animales form dropdowns
# match these literals.
SPECIES_CANINA = "CANINA"
SEX_MACHO = "M"

# Spanish error copy from the route's 422 branch (per
# ``app/modules/adopciones/routes.py::create_adopcion_view``). The form
# template wraps the underlying ValueError under
# ``"No se pudo guardar la adopción: ..."``.
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

    Same flow as ``test_voluntarios_crud.py::authenticated_session`` —
    the csrf_token is threaded into form-encoded POSTs so the
    ``CsrfMiddleware`` accepts them.
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
    """Read the csrf_token hidden input rendered on the current page.

    Regression sentinel: every form page must render a non-empty
    csrf_token. Returns the token so callers can use it directly
    (request-client POSTs).
    """
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "every form page must render a non-empty csrf_token hidden input"
    return token


def _animal_form_data(suffix: str) -> dict[str, str]:
    """Build a valid AnimalForm payload (9 required + optionals).

    Mirrors the factory in ``tests/e2e/test_animales_crud.py``. Each
    call uses a unique chip so multiple create calls within a session
    do not collide on the ``NCHIP`` UNIQUE constraint.
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
    """POST /animales and return the new animal's UUID. Skips on failure.

    Skips when the create POST does not return 303 (e.g. the test
    database is not writable from E2E). Same skip pattern as
    ``tests/e2e/test_entradas_crud.py::animal_id_factory``.
    """
    suffix = f"{uuid.uuid4().hex[:8]}"
    form_data = _animal_form_data(suffix)

    form_page = page.goto(f"{base_url}/animales/new", wait_until="domcontentloaded")
    assert form_page is not None and form_page.status == 200
    _csrf_token_from_form(page)  # regression sentinel

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


def _adopcion_form_data(
    *,
    animal_id: str,
    fecha_adopcion: str,
    nombre_adoptante: str,
    tipo_adopcion: str = "regular",
    telefono_adoptante: str = "",
    email_adoptante: str = "",
    dni_adoptante: str = "",
    observaciones: str = "",
) -> dict[str, str]:
    """Build a valid AdopcionForm payload.

    Field names match the Pydantic model in
    ``app/modules/adopciones/forms.py::AdopcionForm`` (snake_case).
    The 4 required fields are ``animal_id``, ``fecha_adopcion``,
    ``nombre_adoptante``, ``tipo_adopcion``; the rest are optional.
    """
    return {
        "animal_id": animal_id,
        "voluntario_seguimiento_id": "",
        "fecha_adopcion": fecha_adopcion,
        "fecha_devolucion": "",
        "donativo_preadopcion": "",
        "donativo_adopcion": "",
        "nombre_adoptante": nombre_adoptante,
        "dni_adoptante": dni_adoptante,
        "telefono_adoptante": telefono_adoptante,
        "email_adoptante": email_adoptante,
        "entrada_origen_id": "",
        "observaciones": observaciones,
        "tipo_adopcion": tipo_adopcion,
    }


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
    """POST /adopciones and return the new adopcion's UUID. Skips on failure.

    Defaults: ``fecha_adopcion="2024-06-15"`` (fixed historical date so
    assertions are reproducible). The ``nombre_adoptante`` defaults to
    a uuid-suffixed marker so each test row is unique in the database.
    """
    if nombre_adoptante is None:
        nombre_adoptante = f"Adoptante-{uuid.uuid4().hex[:8]}"

    form_data = _adopcion_form_data(
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
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create adopcion (POST /adopciones did not return 303; "
            f"got {response.status}: {response.text()[:200]!r}). The test "
            f"database may not be writable from E2E."
        )
    adopcion_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not adopcion_id or adopcion_id.endswith("new") or adopcion_id.endswith("edit"):
        pytest.skip(
            f"adopcion setup failed; /adopciones redirect was "
            f"{response.headers.get('location')!r}."
        )
    return adopcion_id


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
    assert page.locator("h1").first.inner_text().strip() == "Adopciones", (
        "list page must render the 'Adopciones' h1"
    )


# --- 2. list with adoptante filter -----------------------------------------


def test_list_adopciones_adoptante_filter_excludes_non_matching(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /adopciones?adoptante=foo → 200; only matching rows in the table.

    Setup creates two adopciones with distinct ``nombre_adoptante``
    markers (uuid-suffixed to avoid collision). The filtered list
    must contain the matching nombre_adoptante but NOT the
    non-matching one. The filter is a partial ILIKE on
    ``nombre_adoptante`` per
    ``search_adopciones_by_adoptante`` in
    ``app/modules/adopciones/service.py``.

    We use distinct animal_ids per row (one animal per adopcion) so
    the FK validation in ``_raise_validation_error`` is guaranteed to
    pass without sharing host animals between rows.
    """
    page, csrf_token = authenticated_session

    animal_a = _create_animal(page, csrf_token, base_url)
    animal_b = _create_animal(page, csrf_token, base_url)

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
    response = page.goto(
        f"{base_url}/adopciones",
        params={"adoptante": "FilterA"},
        wait_until="domcontentloaded",
    )
    assert response is not None
    assert response.status == 200, (
        f"/adopciones?adoptante=FilterA must return 200, got {response.status}"
    )
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
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /adopciones with valid payload → 303 to /adopciones/{id}.

    Pins the full create flow: visit the form (regression sentinel:
    page renders + csrf_token present), POST the form payload, verify
    303 redirect to /adopciones/{id} (NOT back to /new or /edit), and
    verify the detail page shows the submitted nombre_adoptante +
    animal_id.

    The adopciones form template uses ``action="{{ form_action }}"``
    which the route renders as ``/adopciones`` for create — the form
    would submit correctly through the browser, but we POST via the
    request client to capture the status code (mirroring the unit-test
    pattern in ``tests/test_adopciones_routes.py``).
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)
    nombre_adoptante = f"Create-{uuid.uuid4().hex[:8]}"
    fecha_adopcion = "2024-06-15"
    tipo_adopcion = "regular"

    # Visit the form first (regression sentinel).
    form_page = page.goto(f"{base_url}/adopciones/new", wait_until="domcontentloaded")
    assert form_page is not None and form_page.status == 200
    _csrf_token_from_form(page)

    # POST directly to /adopciones with the form payload.
    form_data = _adopcion_form_data(
        animal_id=animal_id,
        fecha_adopcion=fecha_adopcion,
        nombre_adoptante=nombre_adoptante,
        tipo_adopcion=tipo_adopcion,
    )
    response = page.request.post(
        f"{base_url}/adopciones",
        form={"csrf_token": csrf_token, **form_data},
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

    form_data = _adopcion_form_data(
        animal_id=bogus_animal_id,
        fecha_adopcion=fecha_adopcion,
        nombre_adoptante=nombre_adoptante,
    )
    response = page.request.post(
        f"{base_url}/adopciones",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 422, (
        f"create POST with bogus animal_id must return 422, got "
        f"{response.status}: {response.text()[:300]!r}"
    )
    body = response.text()
    assert "No se pudo guardar la adopción" in body, (
        f"422 response must carry the Spanish form error header, "
        f"got body excerpt: {body[:500]!r}"
    )
    assert NONEXISTENT_ANIMAL_SPANISH in body, (
        f"422 response must carry the FK validation message "
        f"({NONEXISTENT_ANIMAL_SPANISH!r}), got body excerpt: {body[:500]!r}"
    )


# --- 5. detail -------------------------------------------------------------


def test_detail_adopcion_shows_vigente_badge_and_adoptante_info(
    authenticated_session: tuple[Page, str], base_url: str
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
    animal_id = _create_animal(page, csrf_token, base_url)
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
    authenticated_session: tuple[Page, str], base_url: str
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
    animal_id = _create_animal(page, csrf_token, base_url)
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

    # Visit the edit form (regression sentinel).
    edit_page = page.goto(
        f"{base_url}/adopciones/{adopcion_id}/edit", wait_until="domcontentloaded"
    )
    assert edit_page is not None
    assert edit_page.status == 200, (
        f"/adopciones/{{id}}/edit must return 200, got {edit_page.status}"
    )
    edit_csrf = _csrf_token_from_form(page)

    # POST the update with the new telefono_adoptante; other fields
    # carried through unchanged so the validation passes.
    update_data = _adopcion_form_data(
        animal_id=animal_id,
        fecha_adopcion=fecha_adopcion,
        nombre_adoptante=nombre_adoptante,
        telefono_adoptante=new_telefono,
    )
    update_response = page.request.post(
        f"{base_url}/adopciones/{adopcion_id}/update",
        form={"csrf_token": edit_csrf, **update_data},
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
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /adopciones/{id}/delete → 303 to /adopciones.

    Pins the soft-delete contract end-to-end:

    - Create an adopcion.
    - Visit the detail page to grab the delete form's csrf_token.
    - POST /adopciones/{id}/delete via the request client with the
      form-encoded csrf_token. The detail page's delete form has the
      correct ``action="/adopciones/{{id}}/delete"`` and a JS
      ``onsubmit="return confirm(...)"`` that we bypass via the
      request client.
    - Verify 303 redirect to /adopciones.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)
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
    delete_csrf = _csrf_token_from_form(page)

    # POST delete via the request client (bypasses the JS confirm).
    delete_response = page.request.post(
        f"{base_url}/adopciones/{adopcion_id}/delete",
        form={"csrf_token": delete_csrf},
    )
    assert delete_response.status == 303, (
        f"delete POST must return 303, got {delete_response.status}: "
        f"{delete_response.text()[:300]!r}"
    )
    assert delete_response.headers.get("location", "").endswith("/adopciones"), (
        f"delete POST must redirect to /adopciones, got location="
        f"{delete_response.headers.get('location')!r}"
    )


__all__: list[Any] = [
    "test_list_adopciones_renders_200",
    "test_list_adopciones_adoptante_filter_excludes_non_matching",
    "test_create_adopcion_redirects_to_detail",
    "test_create_adopcion_with_nonexistent_animal_returns_422",
    "test_detail_adopcion_shows_vigente_badge_and_adoptante_info",
    "test_edit_adopcion_updates_telefono_and_redirects_to_detail",
    "test_soft_delete_adopcion_redirects_to_list",
]
