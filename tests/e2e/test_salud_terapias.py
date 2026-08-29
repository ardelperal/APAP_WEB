"""E2E coverage for the ``/terapias`` slice (HEALTH-04, #53).

Pins the terapias CRUD + recomendaciones contract end-to-end via
Playwright + the OAuth mock landed in
``tests/e2e/test_admin_authenticated.py``. The
``authenticated_session`` fixture mints a developer session via
``GET /e2e/login`` with the ``X-E2E-Secret`` header and returns a
``(Page, csrf_token)`` tuple.

The terapias slice has two coupled entities:

- ``terapias`` (the therapy itself) with required fields ``animal_id``,
  ``voluntario_id``, ``fecha``; optional ``descripcion``.
- ``recomendaciones`` (recommendations) linked to a terapia with
  required ``fecha`` + ``texto``; soft-deletable; markable complete via
  PATCH.

The slice enforces a delete-block: a terapia with active
``completada=false`` recomendaciones cannot be soft-deleted — the
service raises ``TerapiaHasPendingRecomendaciones`` and the route maps
it to a 409 with the Spanish ``"No se puede eliminar la terapia: tiene
recomendaciones pendientes."`` message.

Seven cases pin the terapias + recomendaciones contract:

1. List (GET /terapias → 200 with the ``Terapias`` h1).
2. Create (POST /terapias with animal_id + voluntario_id + fecha +
   descripcion → 303 to /terapias/{id}). The terapias form template is
    minimal today (per ``app/templates/salud/terapia_form.html``) and
    the test asserts on the field roundtrip via the detail page.
3. Detail (GET /terapias/{id} → 200; the detail page renders the
    terapia's descripcion + animal_id + voluntario_id and an empty
    ``Recomendaciones`` list when none exist).
4. Add recomendacion (POST /terapias/{terapia_id}/recomendaciones →
    303 back to detail; the new recomendacion appears on the detail
    page's ``Recomendaciones`` list).
5. Edit terapia (POST /terapias/{id}/update with new ``descripcion``
    → 303 to /terapias/{id}; the detail page shows the new
    descripcion).
6. Delete with pending recomendaciones → 409 with the Spanish
    ``"No se puede eliminar la terapia: tiene recomendaciones
    pendientes."`` message (the route's
    ``HTTPException(status_code=409, detail=...)`` raises a JSON 409
    that Playwright surfaces verbatim).
7. Delete without recomendaciones → 303 to /terapias.

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

# Spanish error copy that the route renders when delete is blocked by
# pending recomendaciones (per
# ``app/modules/salud/routes.py::delete_terapia_view`` — the
# ``HTTPException(status_code=409, detail="No se puede eliminar la
# terapia: tiene recomendaciones pendientes.")``).
PENDING_RECOMENDACIONES_SPANISH = (
    "No se puede eliminar la terapia: tiene recomendaciones pendientes"
)


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
    """Build a valid AnimalForm payload with a unique chip."""
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


def _voluntario_form_data(name_suffix: str) -> dict[str, str]:
    """Build a valid Voluntario form payload with a unique nombre.

    Mirrors the helper in ``tests/e2e/test_voluntarios_crud.py``. The
    telefono + email are populated so the voluntario row is distinct
    in the database.
    """
    return {
        "Voluntario": f"Vol-{name_suffix}",
        "Tel1": f"6{uuid.uuid4().int % 100000000:08d}",
        "Tel2": "",
        "Email": f"vol-{name_suffix}@example.test",
        "DNI": "",
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


def _create_voluntario(page: Page, csrf_token: str, base_url: str) -> str:
    """POST /voluntarios and return the new voluntario's UUID. Skips on failure."""
    suffix = f"{uuid.uuid4().hex[:8]}"
    form_data = _voluntario_form_data(suffix)

    response = page.request.post(
        f"{base_url}/voluntarios",
        form={"csrf_token": csrf_token, **form_data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create host voluntario (POST /voluntarios did not "
            f"return 303; got {response.status}: {response.text()[:200]!r}). "
            f"The test database may not be writable from E2E."
        )
    voluntario_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not voluntario_id or voluntario_id.endswith("new"):
        pytest.skip(
            f"voluntario setup failed; /voluntarios redirect was "
            f"{response.headers.get('location')!r}."
        )
    return voluntario_id


def _terapia_form_data(
    *,
    animal_id: str,
    voluntario_id: str,
    fecha: str,
    descripcion: str = "",
) -> dict[str, str]:
    """Build a valid TerapiaForm payload.

    Field names match the Pydantic model in
    ``app/modules/salud/forms.py::TerapiaForm`` (snake_case). The 3
    required fields are ``animal_id``, ``voluntario_id``, ``fecha``;
    ``descripcion`` is optional.
    """
    return {
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "fecha": fecha,
        "descripcion": descripcion,
    }


def _create_terapia(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    animal_id: str,
    voluntario_id: str,
    fecha: str = "2024-07-15",
    descripcion: str = "",
) -> str:
    """POST /terapias and return the new terapia's UUID. Skips on failure."""
    form_data = _terapia_form_data(
        animal_id=animal_id,
        voluntario_id=voluntario_id,
        fecha=fecha,
        descripcion=descripcion,
    )
    response = page.request.post(
        f"{base_url}/terapias",
        form={"csrf_token": csrf_token, **form_data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create terapia (POST /terapias did not return 303; "
            f"got {response.status}: {response.text()[:200]!r}). The test "
            f"database may not be writable from E2E."
        )
    terapia_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not terapia_id or terapia_id.endswith("new") or terapia_id.endswith("edit"):
        pytest.skip(
            f"terapia setup failed; /terapias redirect was "
            f"{response.headers.get('location')!r}."
        )
    return terapia_id


def _create_recomendacion(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    terapia_id: str,
    fecha: str = "2024-07-20",
    texto: str = "",
) -> str:
    """POST to /terapias/{id}/recomendaciones. Returns the new id.

    The route returns ``RedirectResponse(url=f"/terapias/{terapia_id}",
    status_code=303)`` on success — there is no id in the redirect
    header, so we return the terapia_id for the caller to assert on
    the detail page's list.
    """
    if not texto:
        texto = f"Recomendacion-{uuid.uuid4().hex[:8]}"
    response = page.request.post(
        f"{base_url}/terapias/{terapia_id}/recomendaciones",
        form={"csrf_token": csrf_token, "fecha": fecha, "texto": texto},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create recomendacion (POST /terapias/{{id}}/recomendaciones "
            f"did not return 303; got {response.status}: "
            f"{response.text()[:200]!r}). The test database may not be writable."
        )
    return terapia_id


# --- 1. list ---------------------------------------------------------------


def test_list_terapias_renders_200(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /terapias → 200 with the ``Terapias`` h1.

    Pins the list surface. The list template today renders a simple
    ``<h1>Terapias</h1>`` + ``<ul>`` per row (``app/templates/salud/
    list_terapias.html``); the test asserts on the h1 + 200 response.
    """
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/terapias", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, f"/terapias must return 200, got {response.status}"
    assert page.locator("h1").first.inner_text().strip() == "Terapias", (
        "list page must render the 'Terapias' h1"
    )


# --- 2. create -------------------------------------------------------------


def test_create_terapia_redirects_to_detail(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /terapias with valid payload → 303 to /terapias/{id}.

    Pins the full create flow: visit the form (regression sentinel),
    POST the form payload, verify 303 redirect to /terapias/{id}, and
    verify the detail page shows the submitted descripcion +
    animal_id + voluntario_id.

    The terapias form template uses ``action="{{ form_action }}"``
    which the route renders as ``/terapias`` for create — the form
    would submit correctly through the browser, but we POST via the
    request client to capture the status code.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)
    voluntario_id = _create_voluntario(page, csrf_token, base_url)
    fecha = "2024-07-15"
    descripcion = f"Desc-Create-{uuid.uuid4().hex[:8]}"

    # Visit the form first (regression sentinel).
    form_page = page.goto(f"{base_url}/terapias/new", wait_until="domcontentloaded")
    assert form_page is not None and form_page.status == 200
    _csrf_token_from_form(page)

    # POST directly to /terapias with the form payload.
    form_data = _terapia_form_data(
        animal_id=animal_id,
        voluntario_id=voluntario_id,
        fecha=fecha,
        descripcion=descripcion,
    )
    response = page.request.post(
        f"{base_url}/terapias",
        form={"csrf_token": csrf_token, **form_data},
    )
    assert response.status == 303, (
        f"create POST must return 303, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/terapias/"), (
        f"create POST must redirect to /terapias/{{id}}, got {location!r}"
    )
    terapia_id = location.rsplit("/", 1)[-1]
    assert (
        terapia_id
        and not terapia_id.endswith("new")
        and not terapia_id.endswith("edit")
    ), f"create POST must not redirect back to a form URL: {location!r}"

    # Follow the redirect and verify the detail page shows the
    # submitted descripcion + animal_id + voluntario_id.
    detail = page.goto(
        f"{base_url}/terapias/{terapia_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert descripcion in body, (
        f"detail page must show the submitted descripcion "
        f"{descripcion!r}; body excerpt: {body[:500]!r}"
    )
    assert animal_id in body, (
        f"detail page must show the submitted animal_id {animal_id!r}"
    )
    assert voluntario_id in body, (
        f"detail page must show the submitted voluntario_id {voluntario_id!r}"
    )


# --- 3. detail -------------------------------------------------------------


def test_detail_terapia_shows_data_and_recomendaciones_list(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /terapias/{id} → 200; terapia data + empty Recomendaciones list.

    Pins the detail surface: the detail template renders the terapia's
    fecha + descripcion + animal_id + voluntario_id and a
    ``<h2>Recomendaciones</h2>`` block. When the terapia has no
    recomendaciones the block renders an empty ``<ul>`` (per the
    template's ``{% for rec in recomendaciones %}`` loop).

    The ``Recomendaciones`` heading + the data fields are the
    regression sentinel for the detail surface; the empty-list path
    verifies the list-rendering branch is reachable.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)
    voluntario_id = _create_voluntario(page, csrf_token, base_url)
    fecha = "2024-07-15"
    descripcion = f"Desc-Detail-{uuid.uuid4().hex[:8]}"
    terapia_id = _create_terapia(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        voluntario_id=voluntario_id,
        fecha=fecha,
        descripcion=descripcion,
    )

    response = page.goto(
        f"{base_url}/terapias/{terapia_id}", wait_until="domcontentloaded"
    )
    assert response is not None
    assert response.status == 200, (
        f"/terapias/{{id}} must return 200, got {response.status}"
    )
    body = page.content()
    assert descripcion in body, (
        f"detail page must show the terapia's descripcion {descripcion!r}"
    )
    assert animal_id in body, (
        f"detail page must show the terapia's animal_id {animal_id!r}"
    )
    assert voluntario_id in body, (
        f"detail page must show the terapia's voluntario_id {voluntario_id!r}"
    )
    # The Recomendaciones heading anchors the recomendaciones block;
    # its presence pins the detail surface that the add-recomendacion
    # test will later populate.
    assert "Recomendaciones" in body, (
        f"detail page must render the 'Recomendaciones' heading; body "
        f"excerpt: {body[:500]!r}"
    )


# --- 4. add recomendacion --------------------------------------------------


def test_create_recomendacion_appears_on_detail(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /terapias/{id}/recomendaciones → 303 back to detail; rec visible.

    Pins the recomendaciones add flow: POST to
    ``/terapias/{terapia_id}/recomendaciones`` with csrf_token + fecha
    + texto → 303 to ``/terapias/{terapia_id}``. Following the redirect
    shows the new recomendacion's texto in the detail page's list.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)
    voluntario_id = _create_voluntario(page, csrf_token, base_url)
    terapia_id = _create_terapia(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        voluntario_id=voluntario_id,
    )

    rec_texto = f"Recomendacion-{uuid.uuid4().hex[:8]}"
    rec_fecha = "2024-07-20"

    response = page.request.post(
        f"{base_url}/terapias/{terapia_id}/recomendaciones",
        form={"csrf_token": csrf_token, "fecha": rec_fecha, "texto": rec_texto},
    )
    assert response.status == 303, (
        f"create recomendacion must return 303, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    assert response.headers.get("location", "").endswith(
        f"/terapias/{terapia_id}"
    ), (
        f"create recomendacion must redirect to /terapias/{{id}}, got "
        f"location={response.headers.get('location')!r}"
    )

    # Follow the redirect and verify the recomendacion is on the page.
    detail = page.goto(
        f"{base_url}/terapias/{terapia_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert rec_texto in body, (
        f"detail page must show the new recomendacion's texto "
        f"{rec_texto!r}; body excerpt: {body[:500]!r}"
    )


# --- 5. edit ---------------------------------------------------------------


def test_edit_terapia_updates_descripcion_and_redirects_to_detail(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /terapias/{id}/update with new descripcion → 303 to detail.

    Pins the edit path end-to-end:

    - Create a terapia with empty descripcion.
    - Visit the edit form (regression sentinel).
    - POST /terapias/{id}/update with new descripcion (all other
      fields carried through unchanged so the FK validation passes).
    - Verify 303 redirect to /terapias/{id}.
    - Verify the detail page shows the new descripcion.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)
    voluntario_id = _create_voluntario(page, csrf_token, base_url)
    fecha = "2024-07-15"
    terapia_id = _create_terapia(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        voluntario_id=voluntario_id,
        fecha=fecha,
    )
    new_descripcion = f"Desc-Edit-{uuid.uuid4().hex[:8]}"

    # Visit the edit form (regression sentinel).
    edit_page = page.goto(
        f"{base_url}/terapias/{terapia_id}/edit", wait_until="domcontentloaded"
    )
    assert edit_page is not None
    assert edit_page.status == 200, (
        f"/terapias/{{id}}/edit must return 200, got {edit_page.status}"
    )
    edit_csrf = _csrf_token_from_form(page)

    # POST the update with the new descripcion; other fields carried
    # through unchanged so the validation passes.
    update_data = _terapia_form_data(
        animal_id=animal_id,
        voluntario_id=voluntario_id,
        fecha=fecha,
        descripcion=new_descripcion,
    )
    update_response = page.request.post(
        f"{base_url}/terapias/{terapia_id}/update",
        form={"csrf_token": edit_csrf, **update_data},
    )
    assert update_response.status == 303, (
        f"update POST must return 303, got {update_response.status}: "
        f"{update_response.text()[:300]!r}"
    )
    assert update_response.headers.get("location", "").endswith(
        f"/terapias/{terapia_id}"
    ), (
        f"update POST must redirect to /terapias/{{id}}, got location="
        f"{update_response.headers.get('location')!r}"
    )

    # Follow the redirect and verify the detail page shows the new
    # descripcion.
    detail = page.goto(
        f"{base_url}/terapias/{terapia_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert new_descripcion in body, (
        f"detail page must show the updated descripcion "
        f"{new_descripcion!r}; body excerpt: {body[:500]!r}"
    )


# --- 6. delete with pending recomendaciones → 409 --------------------------


def test_delete_terapia_with_pending_recomendaciones_returns_409(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /terapias/{id}/delete with active rec → 409 + Spanish error.

    The service's ``delete_terapia`` raises
    ``TerapiaHasPendingRecomendaciones`` when the terapia has active
    ``completada=false`` recomendaciones. The route catches this and
    raises ``HTTPException(status_code=409, detail="No se puede eliminar
    la terapia: tiene recomendaciones pendientes.")`` per
    ``app/modules/salud/routes.py::delete_terapia_view``.

    The FastAPI HTTPException(409) renders as a JSON 409 body with the
    ``detail`` field carrying the Spanish message. Playwright surfaces
    this verbatim in ``response.text()``.

    The test pins:

    - Setup: create terapia + 1 pending recomendacion.
    - POST /terapias/{id}/delete → 409.
    - 409 response body carries the Spanish detail message.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)
    voluntario_id = _create_voluntario(page, csrf_token, base_url)
    terapia_id = _create_terapia(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        voluntario_id=voluntario_id,
    )
    _create_recomendacion(
        page,
        csrf_token,
        base_url,
        terapia_id=terapia_id,
    )

    delete_response = page.request.post(
        f"{base_url}/terapias/{terapia_id}/delete",
        form={"csrf_token": csrf_token},
    )
    assert delete_response.status == 409, (
        f"delete POST with pending recomendaciones must return 409, got "
        f"{delete_response.status}: {delete_response.text()[:300]!r}"
    )
    body = delete_response.text()
    assert PENDING_RECOMENDACIONES_SPANISH in body, (
        f"409 response must carry the Spanish 'No se puede eliminar la "
        f"terapia: tiene recomendaciones pendientes' message, got body "
        f"excerpt: {body[:500]!r}"
    )


# --- 7. delete without recomendaciones → 303 ------------------------------


def test_delete_terapia_without_recomendaciones_redirects_to_list(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /terapias/{id}/delete (no rec) → 303 to /terapias.

    Pins the soft-delete happy path: a terapia with zero active
    recomendaciones can be soft-deleted; the route returns 303 to
    /terapias. The test confirms the contract end-to-end without
    involving any recomendaciones.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)
    voluntario_id = _create_voluntario(page, csrf_token, base_url)
    terapia_id = _create_terapia(
        page,
        csrf_token,
        base_url,
        animal_id=animal_id,
        voluntario_id=voluntario_id,
    )

    delete_response = page.request.post(
        f"{base_url}/terapias/{terapia_id}/delete",
        form={"csrf_token": csrf_token},
    )
    assert delete_response.status == 303, (
        f"delete POST without recomendaciones must return 303, got "
        f"{delete_response.status}: {delete_response.text()[:300]!r}"
    )
    assert delete_response.headers.get("location", "").endswith("/terapias"), (
        f"delete POST must redirect to /terapias, got location="
        f"{delete_response.headers.get('location')!r}"
    )


__all__: list[Any] = [
    "test_list_terapias_renders_200",
    "test_create_terapia_redirects_to_detail",
    "test_detail_terapia_shows_data_and_recomendaciones_list",
    "test_create_recomendacion_appears_on_detail",
    "test_edit_terapia_updates_descripcion_and_redirects_to_detail",
    "test_delete_terapia_with_pending_recomendaciones_returns_409",
    "test_delete_terapia_without_recomendaciones_redirects_to_list",
]
