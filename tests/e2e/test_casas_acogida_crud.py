"""E2E CRUD coverage for the ``/casas-acogida`` slice (FOSTER-01, #598 follow-up).

Pins the casas de acogida CRUD contract end-to-end via Playwright + the
OAuth mock landed in ``tests/e2e/test_admin_authenticated.py``. The
``authenticated_session`` fixture mints a developer session (the mock's
default rol — see ``app/core/e2e_auth.py::MOCK_USER_ROL``) via
``GET /e2e/login`` with the ``X-E2E-Secret`` header, then returns a
``(Page, csrf_token)`` tuple so the csrf_token can be threaded into
the form-encoded POSTs the routes require (the form template's
``action=""`` quirk used by the animales slice does NOT apply here:
``casas_acogida/form.html`` posts to ``{{ form_action }}`` which the
route renders as ``/casas-acogida`` for create and
``/casas-acogida/{id}/update`` for edit, so the form submits directly
to the right endpoint and we still POST via the request client to
capture the status code).

Seven cases:

1. List (GET /casas-acogida → 200 with the ``Casas de acogida`` h1).
2. Create (GET /casas-acogida/new → POST /casas-acogida → 303 to detail).
3. Create with non-integer ``capacidad`` → Pydantic 422 (JSON body, NOT
   the service's HTML re-render — the int-coercion error surfaces at
   parse time per #140 W2).
4. List with ``?especie=FELINA`` filter → only FELINA casa in the
   table. Note: the task description uses ``?especie=gato`` as a
   colloquial label; the actual route contract (per
   ``app/modules/foster/service.py::_LIST_CASAS_BY_ESPECIE_SQL``)
   accepts ``CANINA`` or ``FELINA`` (the legacy enum values), NOT
   ``"gato"`` or ``"perro"``. ``?especie=gato`` would return an empty
   list because no row has ``especie_preferente = 'gato'``.
5. Detail (GET /casas-acogida/{id} → 200, ``Capacidad:`` value visible
   in the header subtitle).
6. Edit (change ``telefono`` → POST /casas-acogida/{id}/update → 303
   to detail; new telefono visible on the detail page).
7. Soft-delete (POST /casas-acogida/{id}/delete → 303 to /casas-acogida;
   the casa no longer appears in the list).

Each casa uses a uuid-suffixed name to avoid collisions with other
casas that may exist in the test database (E2E flows run against a
real InsForge backend, unlike the unit-test spies in
``tests/test_foster_routes.py``).

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset (the OAuth
mock cannot authenticate).
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page

# --- shared constants -----------------------------------------------------

E2E_SECRET_HEADER = "X-E2E-Secret"

# Species enum values (per app/modules/animals/domain/animal.py::Especie).
# The /casas-acogida?especie= filter accepts these two values; casas with
# ``especie_preferente IS NULL`` are match-all (per
# ``app/modules/foster/service.py::_LIST_CASAS_BY_ESPECIE_SQL``).
SPECIES_CANINA = "CANINA"
SPECIES_FELINA = "FELINA"


# --- fixtures -------------------------------------------------------------


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or ``None`` if unset."""
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    """Mint a developer session and return ``(page, csrf_token)``.

    Same flow as ``tests/e2e/test_admin_authenticated.py::authenticated_page``
    (POST-via-GET ``/e2e/login`` with the ``X-E2E-Secret`` header) but
    additionally captures the csrf_token the mock mints in the response
    payload. The csrf_token is what the form-encoded POSTs need (the
    form template renders it as ``<input type="hidden" name="csrf_token"
    value="...">``; submitting via the browser would auto-include it,
    but we POST via the request client to capture status codes, so we
    thread the token manually).
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
    csrf_token. Returns the token so callers can either use it
    directly (request-client POSTs) or just assert it's present
    (browser-submitted POSTs pick it up from the form automatically).
    """
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "every form page must render a non-empty csrf_token hidden input"
    return token


def _casa_form_data(name_suffix: str, *, especie_preferente: str = "") -> dict[str, str]:
    """Build a valid CasaAcogidaForm payload with a unique suffix.

    All 6 required fields are filled (per
    ``app/modules/foster/forms.py::CasaAcogidaForm``):
    ``nombre``, ``apellidos``, ``calle``, ``telefono``, ``coche``,
    ``capacidad``. The 13 optional fields are empty strings (the
    service's ``_opt`` helper in ``app/core/forms.py`` converts them
    to ``None`` so the service stores NULL).
    """
    return {
        "nombre": f"Casa-{name_suffix}",
        "apellidos": f"Apellido-{name_suffix}",
        "dni_acogedor": "",
        "calle": f"Calle-{name_suffix}",
        "numero": "12",
        "piso": "",
        "letra": "",
        "localidad": "Madrid",
        "provincia": "Madrid",
        "cp": "28001",
        "telefono": "600123456",
        "telefono2": "",
        "email": "",
        "vinculacion": "",
        "caracteristicas": "",
        "coche": "Sí",
        "especie_preferente": especie_preferente,
        "observaciones": "",
        "capacidad": "3",
    }


def _create_casa(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    name_suffix: str,
    especie_preferente: str = "",
    capacidad: str = "3",
) -> str:
    """POST /casas-acogida and return the new casa's UUID.

    Skips when the create POST does not return 303 (e.g. the test
    database is not writable from E2E). Same skip pattern as
    ``tests/e2e/test_entradas_crud.py::_create_animal``.
    """
    data = _casa_form_data(name_suffix, especie_preferente=especie_preferente)
    data["capacidad"] = capacidad
    response = page.request.post(
        f"{base_url}/casas-acogida",
        form={"csrf_token": csrf_token, **data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create casa (POST /casas-acogida did not return 303; "
            f"got {response.status}: {response.text()[:200]!r}). The test "
            f"database may not be writable from E2E."
        )
    location = response.headers.get("location", "")
    casa_id = location.rsplit("/", 1)[-1]
    if not casa_id or "/new" in casa_id or "/edit" in casa_id:
        pytest.skip(
            f"casa setup failed; /casas-acogida redirect was {location!r}. "
            f"The test database may not be writable from E2E."
        )
    return casa_id


# --- 1. list ---------------------------------------------------------------


def test_list_casas_acogida_renders_200(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /casas-acogida → 200 with the ``Casas de acogida`` h1.

    Pins the list surface: either the table (``<table>``) OR the
    empty-state card is a valid contract — both render on a 200
    response. The h1 assertion confirms the route rendered (not an
    error page).
    """
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/casas-acogida", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, f"/casas-acogida must return 200, got {response.status}"
    assert page.locator("h1").first.inner_text().strip() == "Casas de acogida", (
        "list page must render the 'Casas de acogida' h1"
    )


# --- 2. create -------------------------------------------------------------


def test_create_casa_acogida_redirects_to_detail(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /casas-acogida/new → POST /casas-acogida → 303 to detail page.

    Pins the full create flow: the form is reachable (GET 200 + a
    rendered csrf_token), the POST accepts the form payload (303
    redirect), and the redirect target's detail page shows the casa
    name we just submitted.
    """
    page, csrf_token = authenticated_session
    suffix = f"create-{uuid.uuid4().hex[:8]}"
    form_data = _casa_form_data(suffix)

    # Visit the form first (regression sentinel — the page must
    # render + carry a csrf_token).
    form_page = page.goto(f"{base_url}/casas-acogida/new", wait_until="domcontentloaded")
    assert form_page is not None
    assert form_page.status == 200, f"/casas-acogida/new must return 200, got {form_page.status}"
    _csrf_token_from_form(page)

    # POST directly to the create endpoint (the form template's
    # ``action="{{ form_action }}"`` resolves to ``/casas-acogida`` per
    # the route's ``_render_form`` call, but we POST via the request
    # client to capture the status code).
    response = page.request.post(
        f"{base_url}/casas-acogida",
        form={"csrf_token": csrf_token, **form_data},
    )
    assert response.status == 303, (
        f"create POST must return 303, got {response.status}: {response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/casas-acogida/"), (
        f"create POST must redirect to /casas-acogida/{{id}}, got {location!r}"
    )
    casa_id = location.rsplit("/", 1)[-1]
    assert casa_id and not casa_id.endswith("new") and not casa_id.endswith("edit"), (
        f"create POST must not redirect back to a form URL: {location!r}"
    )

    # Follow the redirect to the detail page and verify the casa name.
    detail = page.goto(
        f"{base_url}/casas-acogida/{casa_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert f"Casa-{suffix}" in body, (
        f"detail page must show the casa nombre; body excerpt: {body[:500]!r}"
    )


# --- 3. non-integer capacidad → 422 ----------------------------------------


def test_create_casa_acogida_with_non_integer_capacidad_returns_422(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /casas-acogida with ``capacidad="abc"`` → 422 from Pydantic.

    ``capacidad`` is declared as ``int`` in
    ``app/modules/foster/forms.py::CasaAcogidaForm``, so Pydantic
    rejects the non-integer string at parse time (BEFORE the handler
    runs) and FastAPI returns a 422 with a JSON body — NOT the
    service's HTML re-render. The actual JSON envelope is
    ``{"detail": [{"loc": ["body", "capacidad"], ...}]}``.

    This pins the #140 W2 contract: the silent try/except on
    ``int(capacidad_raw)`` was retired in favour of Pydantic's
    explicit int coercion, so a malformed value surfaces as 422 here
    rather than as a downstream service-layer ``ValueError``.
    """
    page, csrf_token = authenticated_session
    suffix = f"bad-cap-{uuid.uuid4().hex[:8]}"
    form_data = _casa_form_data(suffix)
    form_data["capacidad"] = "abc"  # Pydantic rejects at parse time

    response = page.request.post(
        f"{base_url}/casas-acogida",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 422, (
        f"POST with non-integer capacidad must return 422, got {response.status}"
    )
    body: Any = response.json()
    # Pydantic's 422 carries a ``detail`` envelope; at least one entry
    # must point at ``capacidad`` so the operator can see which field
    # was malformed.
    assert "detail" in body, f"422 response must carry a 'detail' envelope, got {body!r}"
    detail = body["detail"]
    assert isinstance(detail, list) and detail, f"detail must be a non-empty list, got {detail!r}"
    # ``loc`` includes "body" and "capacidad" — Pydantic v2 reports the
    # field location that failed validation.
    assert any(
        "capacidad" in (entry.get("loc") or []) for entry in detail
    ), f"422 detail must reference 'capacidad' field; got {detail!r}"


# --- 4. list with especie filter -------------------------------------------


def test_list_casas_acogida_filtered_by_especie_felina(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /casas-acogida?especie=FELINA → 200; only FELINA casa in the table.

    Setup creates one CANINA and one FELINA casa. The filtered list
    must contain the FELINA apellidos but NOT the CANINA apellidos.
    Note: a casa with ``especie_preferente IS NULL`` would also match
    per the SQL contract (``OR especie_preferente IS NULL``), but this
    test does not create any such casa to keep the assertion tight.
    """
    page, csrf_token = authenticated_session
    suffix_canina = f"canina-{uuid.uuid4().hex[:8]}"
    suffix_felina = f"felina-{uuid.uuid4().hex[:8]}"

    _create_casa(
        page,
        csrf_token,
        base_url,
        name_suffix=suffix_canina,
        especie_preferente=SPECIES_CANINA,
    )
    _create_casa(
        page,
        csrf_token,
        base_url,
        name_suffix=suffix_felina,
        especie_preferente=SPECIES_FELINA,
    )

    response = page.goto(
        f"{base_url}/casas-acogida",
        params={"especie": SPECIES_FELINA},
        wait_until="domcontentloaded",
    )
    assert response is not None
    assert response.status == 200
    body = page.content()

    assert f"Apellido-{suffix_felina}" in body, (
        f"FELINA casa must appear in the filtered list; body excerpt: {body[:500]!r}"
    )
    assert f"Apellido-{suffix_canina}" not in body, (
        f"CANINA casa must NOT appear when filtering by FELINA; "
        f"body excerpt: {body[:500]!r}"
    )


# --- 5. detail -------------------------------------------------------------


def test_detail_casa_acogida_shows_capacidad(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /casas-acogida/{id} → 200; ``Capacidad:`` value visible in the header.

    Pins the detail surface: the detail template renders ``Capacidad:
    <span>{{ casa.capacidad }}</span>`` in the header subtitle, so
    when ``capacidad=3`` is submitted at create time, the detail page
    shows ``Capacidad: 3``.
    """
    page, csrf_token = authenticated_session
    suffix = f"detail-{uuid.uuid4().hex[:8]}"
    casa_id = _create_casa(page, csrf_token, base_url, name_suffix=suffix)

    response = page.goto(
        f"{base_url}/casas-acogida/{casa_id}", wait_until="domcontentloaded"
    )
    assert response is not None
    assert response.status == 200, (
        f"/casas-acogida/{{id}} must return 200, got {response.status}"
    )
    body = page.content()
    # The detail template renders ``Capacidad:`` literal + the integer
    # inside a font-semibold span. We look for the literal label + the
    # digit (not inside a JSON-style quoted string) to keep the
    # assertion specific.
    assert "Capacidad:" in body, (
        f"detail page must show 'Capacidad:' label; body excerpt: {body[:500]!r}"
    )
    assert ">3<" in body, (
        f"detail page must show the capacidad value 3 in a span; body excerpt: {body[:500]!r}"
    )


# --- 6. edit ---------------------------------------------------------------


def test_edit_casa_acogida_updates_telefono_and_redirects_to_detail(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """Edit form: change ``telefono`` → POST update → 303 to detail page.

    Pins the edit path end-to-end: GET /casas-acogida/{id}/edit renders
    the prefilled form (csrf_token + pre-filled values), POST
    /casas-acogida/{id}/update returns 303 to /casas-acogida/{id}, and
    the detail page shows the updated telefono in the ``Contacto``
    section (where the detail template renders
    ``<dd class="text-text font-mono">{{ casa.telefono }}</dd>``).

    The Pydantic ``CasaAcogidaForm`` requires ALL 19 fields, so the
    update POST sends every field (the helper builds the dict; only
    telefono differs from the create-time value).
    """
    page, csrf_token = authenticated_session
    suffix = f"edit-{uuid.uuid4().hex[:8]}"
    casa_id = _create_casa(page, csrf_token, base_url, name_suffix=suffix)
    # New telefono: 9-digit Spanish-style number, generated from a uuid
    # int so the assertion is robust against pre-existing casas in the
    # test DB.
    new_telefono = f"6{uuid.uuid4().int % 100000000:08d}"

    # Visit the edit form (regression sentinel: form renders + csrf_token present).
    edit_page = page.goto(
        f"{base_url}/casas-acogida/{casa_id}/edit", wait_until="domcontentloaded"
    )
    assert edit_page is not None
    assert edit_page.status == 200, (
        f"/casas-acogida/{{id}}/edit must return 200, got {edit_page.status}"
    )
    edit_csrf = _csrf_token_from_form(page)

    # Submit the update with the new telefono (other fields unchanged).
    update_data = _casa_form_data(suffix)
    update_data["telefono"] = new_telefono
    response = page.request.post(
        f"{base_url}/casas-acogida/{casa_id}/update",
        form={"csrf_token": edit_csrf, **update_data},
    )

    assert response.status == 303, (
        f"update POST must return 303, got {response.status}: {response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location.endswith(f"/casas-acogida/{casa_id}"), (
        f"update POST must redirect to /casas-acogida/{{id}}, got {location!r}"
    )

    # Follow the redirect and verify the detail page shows the new telefono.
    detail = page.goto(
        f"{base_url}/casas-acogida/{casa_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert new_telefono in body, (
        f"detail page must show the updated telefono {new_telefono!r}"
    )


# --- 7. soft-delete --------------------------------------------------------


def test_soft_delete_casa_acogida_redirects_to_list(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /casas-acogida/{id}/delete → 303 to /casas-acogida; casa gone.

    Pins the soft-delete contract end-to-end:

    - Create a casa with a unique suffix.
    - Visit the detail page to grab its csrf_token (the detail page
      renders the delete form with the token; this also confirms the
      detail page is reachable before we delete).
    - POST /casas-acogida/{id}/delete via the request client with the
      form-encoded csrf_token (the detail page's delete form has the
      correct ``action="/casas-acogida/{{id}}/delete"``).
    - Verify 303 redirect to /casas-acogida.
    - Visit /casas-acogida and verify the unique apellidos is no
      longer in the list (the list query filters ``activo = true``
      per ``_LIST_CASAS_SQL`` in
      ``app/modules/foster/service.py``).
    """
    page, csrf_token = authenticated_session
    suffix = f"delete-{uuid.uuid4().hex[:8]}"
    casa_id = _create_casa(page, csrf_token, base_url, name_suffix=suffix)

    # Visit the detail page to grab the delete form's csrf_token.
    detail = page.goto(
        f"{base_url}/casas-acogida/{casa_id}", wait_until="domcontentloaded"
    )
    assert detail is not None
    assert detail.status == 200, (
        f"/casas-acogida/{{id}} must return 200 before delete, got {detail.status}"
    )
    delete_csrf = _csrf_token_from_form(page)

    # The detail page's delete form has an ``onsubmit="return confirm(...)"``.
    # We don't click via the browser (which would block on the confirm
    # dialog); we POST via the request client with the csrf_token so
    # the test does not need to handle a JS dialog.
    response = page.request.post(
        f"{base_url}/casas-acogida/{casa_id}/delete",
        form={"csrf_token": delete_csrf},
    )
    assert response.status == 303, (
        f"delete POST must return 303, got {response.status}"
    )
    location = response.headers.get("location", "")
    assert location.endswith("/casas-acogida"), (
        f"delete POST must redirect to /casas-acogida, got {location!r}"
    )

    # Verify the casa is gone from the list.
    list_page = page.goto(f"{base_url}/casas-acogida", wait_until="domcontentloaded")
    assert list_page is not None and list_page.status == 200
    body = page.content()
    assert f"Apellido-{suffix}" not in body, (
        "deleted casa's apellidos must not appear in /casas-acogida"
    )
