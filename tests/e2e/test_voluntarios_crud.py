"""E2E CRUD coverage for the ``/voluntarios`` slice (epic #420, VOL-01).

Pins the voluntarios CRUD contract end-to-end via Playwright + the
OAuth mock landed in ``tests/e2e/test_admin_authenticated.py``. The
``authenticated_session`` fixture mints a developer session via
``GET /e2e/login`` with the ``X-E2E-Secret`` header and returns a
``(Page, csrf_token)`` tuple so the csrf_token can be threaded into
the form-encoded POSTs the routes require.

Five cases pin the voluntarios CRUD contract end-to-end:

1. List (GET /voluntarios → 200 with the ``Voluntarios`` h1).
2. Create (POST /voluntarios with nombre + telefono + email → 303 to
   detail). The voluntarios form template uses ``action=""`` (resolves
   to the document URL — i.e. on /voluntarios/new the form would post
   to /voluntarios/new), so the test POSTs directly to ``/voluntarios``
   via the request client (mirroring the unit-test pattern in
   ``tests/test_voluntarios_routes.py``). The form page is still
   visited first to verify it renders + carries a csrf_token.
3. Create with empty ``Voluntario`` (nombre) → 422 with the Spanish
   ``VoluntarioValidationError`` message
   ``"Nombre es obligatorio y no puede estar vacio"`` per
   ``app/modules/voluntarios/domain/voluntario_validation.py::_require_non_blank``.
4. Detail (GET /voluntarios/{id} → 200, body contains the submitted
   nombre + email + telefono).
5. Deactivate (POST /voluntarios/{id}/deactivate → 303 to /voluntarios;
   the voluntario no longer appears in the active list — the list
   query filters ``activo = true`` per ``LIST_VOLUNTARIOS_SQL`` in
   ``app/modules/voluntarios/adapters/local-backend/voluntarios_local_backend_queries.py``).

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset (the OAuth
mock cannot authenticate). Each voluntario uses a uuid-suffixed nombre
to avoid collisions with other voluntarios that may exist in the test
database.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page

# --- shared constants -----------------------------------------------------

E2E_SECRET_HEADER = "X-E2E-Secret"

# Spanish error copy that ``_require_non_blank`` raises when the nombre
# field is empty (per app/modules/voluntarios/domain/voluntario_validation.py).
# The form template wraps it under "No se pudo guardar el voluntario".
VOLUNTARIO_REQUIRED_FIELD_SPANISH = "Nombre es obligatorio"


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
    (GET ``/e2e/login`` with the ``X-E2E-Secret`` header) but
    additionally captures the csrf_token the mock mints in the response
    payload. The csrf_token is what the form-encoded POSTs need — the
    voluntarios form template renders it as a hidden input, but we POST
    via the request client to capture status codes, so we thread the
    token manually.
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


def _voluntario_form_data(name_suffix: str, *, telefono: str | None = None) -> dict[str, str]:
    """Build a valid Voluntario form payload with a unique nombre suffix.

    The form template renders five fields (per
    ``app/modules/voluntarios/routes.py::create_voluntario_view``):
    ``Voluntario`` (required), ``Tel1``, ``Tel2``, ``Email``, ``DNI``.
    Only ``Voluntario`` is required; the others are optional. We fill
    nombre + tel1 + email so the detail-page test (#4) has multiple
    fields to assert on, and leave tel2 + DNI blank.
    """
    if telefono is None:
        telefono = f"6{uuid.uuid4().int % 100000000:08d}"
    return {
        "Voluntario": f"Voluntario-{name_suffix}",
        "Tel1": telefono,
        "Tel2": "",
        "Email": f"vol-{name_suffix}@example.test",
        "DNI": "",
    }


# --- 1. list ---------------------------------------------------------------


def test_list_voluntarios_renders_200(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /voluntarios → 200 with the ``Voluntarios`` h1.

    Pins the list surface: either the ``<table>`` OR the empty-state
    card is a valid contract — both render on a 200 response. The h1
    assertion confirms the route rendered (not an error page).
    """
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/voluntarios", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, f"/voluntarios must return 200, got {response.status}"
    assert page.locator("h1").first.inner_text().strip() == "Voluntarios", (
        "list page must render the 'Voluntarios' h1"
    )


# --- 2. create -------------------------------------------------------------


def test_create_voluntario_redirects_to_detail(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /voluntarios with valid payload → 303 to /voluntarios/{id}.

    Pins the full create flow: the form is reachable (GET 200 + a
    rendered csrf_token), the POST accepts the form payload (303
    redirect), and the redirect target's detail page shows the
    voluntario's nombre + telefono + email we just submitted.

    The voluntarios form template uses ``action=""`` (resolves to the
    document URL — i.e. on /voluntarios/new the form would post to
    /voluntarios/new), so the create POST would actually go to the
    wrong endpoint if submitted through the browser. The test
    therefore visits the form page (regression sentinel) and POSTs to
    ``/voluntarios`` directly via the request client, mirroring the
    unit-test pattern in ``tests/test_voluntarios_routes.py``.
    """
    page, csrf_token = authenticated_session
    suffix = f"create-{uuid.uuid4().hex[:8]}"
    form_data = _voluntario_form_data(suffix)

    # Visit the form first (regression sentinel — the page must render +
    # carry a csrf_token).
    form_page = page.goto(f"{base_url}/voluntarios/new", wait_until="domcontentloaded")
    assert form_page is not None
    assert form_page.status == 200, (
        f"/voluntarios/new must return 200, got {form_page.status}"
    )
    _csrf_token_from_form(page)

    # POST directly to the create endpoint. csrf_token is sent as a form
    # field so CsrfMiddleware accepts the request.
    response = page.request.post(
        f"{base_url}/voluntarios",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 303, (
        f"create POST must return 303, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/voluntarios/"), (
        f"create POST must redirect to /voluntarios/{{id}}, got {location!r}"
    )
    voluntario_id = location.rsplit("/", 1)[-1]
    assert voluntario_id and not voluntario_id.endswith("new"), (
        f"create POST must not redirect back to a form URL: {location!r}"
    )

    # Follow the redirect to the detail page and verify all submitted fields.
    detail = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert form_data["Voluntario"] in body, (
        f"detail page must show the voluntario's nombre {form_data['Voluntario']!r}; "
        f"body excerpt: {body[:500]!r}"
    )
    assert form_data["Email"] in body, (
        f"detail page must show the voluntario's email {form_data['Email']!r}"
    )
    assert form_data["Tel1"] in body, (
        f"detail page must show the voluntario's Tel1 {form_data['Tel1']!r}"
    )


# --- 3. create with empty nombre → 422 -------------------------------------


def test_create_voluntario_with_empty_nombre_returns_422(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /voluntarios with empty ``Voluntario`` → 422 + Spanish error.

    The route's ``create_voluntario`` use case calls
    ``_require_non_blank(nombre, "Nombre")`` which raises
    ``VoluntarioValidationError("Nombre es obligatorio y no puede estar
    vacio")`` on an empty string. The route catches the
    ``VoluntarioValidationError`` in its try/except and re-renders the
    form template with status ``422 Unprocessable Content`` and the
    Spanish message preserved under the form's ``error`` context.

    The form template renders the error inside a rose-coloured banner
    prefixed with the literal ``"No se pudo guardar el voluntario"``,
    and the Spanish message itself contains the ``"Nombre"`` literal.
    The test asserts both copies are present so it stays useful if the
    exact wording is tweaked but the contract is preserved.
    """
    page, csrf_token = authenticated_session
    suffix = f"empty-{uuid.uuid4().hex[:8]}"
    form_data = _voluntario_form_data(suffix)
    form_data["Voluntario"] = ""  # trigger VoluntarioValidationError

    response = page.request.post(
        f"{base_url}/voluntarios",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 422, (
        f"create POST with empty nombre must return 422, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    body = response.text()
    assert "No se pudo guardar el voluntario" in body, (
        f"422 response must carry the Spanish form error header, "
        f"got body excerpt: {body[:500]!r}"
    )
    assert VOLUNTARIO_REQUIRED_FIELD_SPANISH in body, (
        f"422 response must carry the VoluntarioValidationError Spanish message "
        f"({VOLUNTARIO_REQUIRED_FIELD_SPANISH!r}), got body excerpt: {body[:500]!r}"
    )


# --- 4. detail -------------------------------------------------------------


def test_detail_voluntario_page_shows_voluntario_data(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /voluntarios/{id} → 200, body contains the submitted data.

    Pins the detail surface: the detail template renders the
    voluntario's nombre as the page h1, plus email / DNI / Tel1 / Tel2
    in labelled divs. We submit nombre + tel1 + email (DNI and Tel2
    blank) and assert all three are visible on the detail page.
    """
    page, csrf_token = authenticated_session
    suffix = f"detail-{uuid.uuid4().hex[:8]}"
    form_data = _voluntario_form_data(suffix)

    # Create the voluntario first.
    create_response = page.request.post(
        f"{base_url}/voluntarios",
        form={"csrf_token": csrf_token, **form_data},
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    voluntario_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert voluntario_id and not voluntario_id.endswith("new"), (
        f"setup failed; create redirect was {create_response.headers.get('location')!r}"
    )

    # Visit the detail page.
    response = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert response is not None
    assert response.status == 200, (
        f"/voluntarios/{{id}} must return 200, got {response.status}"
    )
    body = page.content()
    assert form_data["Voluntario"] in body, (
        f"detail page must show the voluntario's nombre {form_data['Voluntario']!r}"
    )
    assert form_data["Email"] in body, (
        f"detail page must show the voluntario's email {form_data['Email']!r}"
    )
    assert form_data["Tel1"] in body, (
        f"detail page must show the voluntario's Tel1 {form_data['Tel1']!r}"
    )


# --- 5. deactivate (soft) --------------------------------------------------


def test_deactivate_voluntario_removes_from_active_list(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /voluntarios/{id}/deactivate → 303 to /voluntarios; gone from list.

    Pins the soft-delete contract end-to-end:

    - Create a voluntario with a unique suffix.
    - Visit the detail page to grab its csrf_token (the detail page
      renders the deactivate form with the token; this also confirms
      the detail page is reachable before we deactivate).
    - POST /voluntarios/{id}/deactivate via the request client with
      the form-encoded csrf_token. The detail page's deactivate form
      has the correct ``action="/voluntarios/{{id}}/deactivate"`` so
      this is a form-encoded POST to the right endpoint.
    - Verify 303 redirect to /voluntarios.
    - Visit /voluntarios and verify the unique nombre is no longer in
      the list (the list query filters ``activo = true``).
    """
    page, csrf_token = authenticated_session
    suffix = f"deactivate-{uuid.uuid4().hex[:8]}"
    form_data = _voluntario_form_data(suffix)

    # Create the voluntario first.
    create_response = page.request.post(
        f"{base_url}/voluntarios",
        form={"csrf_token": csrf_token, **form_data},
    )
    assert create_response.status == 303, (
        f"setup failed: create POST must return 303, got {create_response.status}"
    )
    voluntario_id = create_response.headers.get("location", "").rsplit("/", 1)[-1]
    assert voluntario_id and not voluntario_id.endswith("new"), (
        f"setup failed; create redirect was {create_response.headers.get('location')!r}"
    )

    # Visit the detail page to grab the deactivate form's csrf_token.
    detail = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert detail is not None
    assert detail.status == 200, (
        f"/voluntarios/{{id}} must return 200 before deactivate, got {detail.status}"
    )
    deactivate_csrf = _csrf_token_from_form(page)

    # The detail page's deactivate form has an ``onsubmit="return confirm(...)"``.
    # We don't click via the browser (which would block on the confirm
    # dialog); we POST via the request client with the csrf_token so
    # the test does not need to handle a JS dialog.
    deactivate_response = page.request.post(
        f"{base_url}/voluntarios/{voluntario_id}/deactivate",
        form={"csrf_token": deactivate_csrf},
    )
    assert deactivate_response.status == 303, (
        f"deactivate POST must return 303, got {deactivate_response.status}"
    )
    location = deactivate_response.headers.get("location", "")
    assert location.endswith("/voluntarios"), (
        f"deactivate POST must redirect to /voluntarios, got {location!r}"
    )

    # Verify the voluntario is gone from the active list.
    list_response = page.goto(f"{base_url}/voluntarios", wait_until="domcontentloaded")
    assert list_response is not None and list_response.status == 200
    body = page.content()
    assert form_data["Voluntario"] not in body, (
        f"deactivated voluntario's nombre {form_data['Voluntario']!r} must not "
        f"appear in /voluntarios; body excerpt: {body[:500]!r}"
    )


__all__: list[Any] = [
    "test_list_voluntarios_renders_200",
    "test_create_voluntario_redirects_to_detail",
    "test_create_voluntario_with_empty_nombre_returns_422",
    "test_detail_voluntario_page_shows_voluntario_data",
    "test_deactivate_voluntario_removes_from_active_list",
]
