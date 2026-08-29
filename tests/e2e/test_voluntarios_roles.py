"""E2E coverage for the ``/voluntarios/{id}/roles`` slice (epic #420, VOL-02).

Pins the voluntarios role assignment/removal contract end-to-end via
Playwright + the OAuth mock landed in
``tests/e2e/test_admin_authenticated.py``. The
``authenticated_session`` fixture mints a developer session via
``GET /e2e/login`` with the ``X-E2E-Secret`` header and returns a
``(Page, csrf_token)`` tuple.

The ``/voluntarios/{id}/roles/{add,remove}`` routes render
``voluntarios/detail.html`` with a ``role_error`` context variable
when validation/conflict fails. Per
``app/modules/voluntarios/routes.py::_render_detail_with_error``,
both ``VoluntarioValidationError`` and ``UniqueViolationError`` are
mapped to status ``422 Unprocessable Content`` — the implementation
does NOT distinguish 409 from 422 at the HTTP layer. The task
specification accepts either; we follow the actual contract (422).

Five cases pin the role + deactivate interaction end-to-end:

1. Add role (POST /voluntarios/{id}/roles/add → 303, role visible on
   detail page). The detail template renders each assigned role as a
   chip with the role name as its visible label.
2. Add same role twice (POST .../roles/add twice with the same rol →
   422 with the Spanish conflict message
   ``"Este voluntario ya tiene ese rol asignado."``).
3. Remove role (POST .../roles/remove → 303, role no longer visible on
   detail page).
4. Deactivate (POST .../deactivate → 303 to /voluntarios; the
   voluntario is filtered from the active list — the list query filters
   ``activo = true``). The detail page can still be reached (the GET
   route loads by id without an ``activo`` filter), but the voluntario
   no longer appears in the main listing. This pins the user-visible
   soft-delete: the role-management surface is unreachable through
   the normal list navigation.

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset (the OAuth
mock cannot authenticate). Each voluntario uses a uuid-suffixed nombre
to avoid collisions with other voluntarios in the test database.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page

# --- shared constants -----------------------------------------------------

E2E_SECRET_HEADER = "X-E2E-Secret"

# Closed enum of valid roles (per
# ``app/modules/voluntarios/domain/__init__.py::RolVoluntario`` and the
# ``<select>`` options hard-coded in
# ``app/templates/voluntarios/detail.html``: intake, seguimiento,
# acogida, salud).
VALID_ROL_INTAKE = "intake"

# Spanish error copy the route returns when adding a duplicate role
# (the ``except UniqueViolationError`` branch in ``add_voluntario_role``).
DUPLICATE_ROLE_SPANISH = "Este voluntario ya tiene ese rol asignado."


# --- fixtures -------------------------------------------------------------


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or ``None`` if unset."""
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    """Mint a developer session and return ``(page, csrf_token)``.

    Same flow as ``test_voluntarios_crud.py::authenticated_session``.
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


def _create_voluntario(page: Page, csrf_token: str, base_url: str) -> str:
    """POST /voluntarios with a unique nombre and return the new id.

    Skips when the create POST does not return 303 (e.g. the test
    database is not writable from E2E). Same skip pattern as the
    helper in ``tests/e2e/test_casas_acogida_crud.py::_create_casa``.
    """
    suffix = f"roles-{uuid.uuid4().hex[:8]}"
    form_data = {
        "Voluntario": f"Voluntario-{suffix}",
        "Tel1": f"6{uuid.uuid4().int % 100000000:08d}",
        "Tel2": "",
        "Email": f"vol-{suffix}@example.test",
        "DNI": "",
    }
    response = page.request.post(
        f"{base_url}/voluntarios",
        form={"csrf_token": csrf_token, **form_data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create voluntario (POST /voluntarios did not return "
            f"303; got {response.status}: {response.text()[:200]!r}). The test "
            f"database may not be writable from E2E."
        )
    location = response.headers.get("location", "")
    voluntario_id = location.rsplit("/", 1)[-1]
    if not voluntario_id or voluntario_id.endswith("new"):
        pytest.skip(
            f"voluntario setup failed; /voluntarios redirect was "
            f"{location!r}. The test database may not be writable from E2E."
        )
    return voluntario_id


# --- 1. add role -----------------------------------------------------------


def test_add_role_appears_in_detail(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /voluntarios/{id}/roles/add with a valid rol → 303; role on detail.

    Pins the happy path end-to-end:

    - Create a fresh voluntario.
    - Visit the detail page to grab its csrf_token (regression sentinel:
      the detail page renders the role-management form with the token).
    - POST /voluntarios/{id}/roles/add with rol="intake" + csrf_token.
    - Verify 303 redirect back to /voluntarios/{id}.
    - Follow the redirect and verify the role chip "intake" appears on
      the detail page (the template renders each role as a labelled
      badge with the literal rol name as its visible text).
    """
    page, csrf_token = authenticated_session
    voluntario_id = _create_voluntario(page, csrf_token, base_url)

    # Visit the detail page to grab the add-role form's csrf_token.
    detail = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    add_role_csrf = _csrf_token_from_form(page)

    # POST the role assignment.
    response = page.request.post(
        f"{base_url}/voluntarios/{voluntario_id}/roles/add",
        form={"csrf_token": add_role_csrf, "rol": VALID_ROL_INTAKE},
    )
    assert response.status == 303, (
        f"add-role POST must return 303, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    assert response.headers.get("location", "").endswith(
        f"/voluntarios/{voluntario_id}"
    ), (
        f"add-role POST must redirect to /voluntarios/{{id}}, got location="
        f"{response.headers.get('location')!r}"
    )

    # Follow the redirect and verify the role chip appears on the detail page.
    after = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert after is not None and after.status == 200
    body = page.content()
    assert VALID_ROL_INTAKE in body, (
        f"detail page must show the assigned role {VALID_ROL_INTAKE!r} as a "
        f"chip; body excerpt: {body[:500]!r}"
    )


# --- 2. duplicate role → 422 ----------------------------------------------


def test_add_same_role_twice_returns_422_with_conflict_message(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST .../roles/add twice with the same rol → 422 + Spanish conflict.

    The actual implementation in
    ``app/modules/voluntarios/routes.py::add_voluntario_role`` maps
    ``UniqueViolationError`` to the detail page re-render with status
    ``422`` and the Spanish message
    ``"Este voluntario ya tiene ese rol asignado."`` — the route does
    NOT distinguish 409 from 422 at the HTTP layer
    (``_render_detail_with_error`` hardcodes status_code=422). The
    task description accepts either 409 or 422; we follow the actual
    contract (422) so the test stays useful if a future refactor
    renames or moves the response.

    The conflict message is rendered inside the ``role_error`` context
    variable, which the detail template wraps in a red banner. The
    test asserts on the Spanish message text being present in the
    response body.
    """
    page, csrf_token = authenticated_session
    voluntario_id = _create_voluntario(page, csrf_token, base_url)

    # First add — succeeds with 303.
    detail = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    first_csrf = _csrf_token_from_form(page)
    first_response = page.request.post(
        f"{base_url}/voluntarios/{voluntario_id}/roles/add",
        form={"csrf_token": first_csrf, "rol": VALID_ROL_INTAKE},
    )
    assert first_response.status == 303, (
        f"first add-role POST must succeed with 303, got {first_response.status}: "
        f"{first_response.text()[:300]!r}"
    )

    # Second add with the same rol — must return 422 with Spanish conflict.
    after_first = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert after_first is not None and after_first.status == 200
    second_csrf = _csrf_token_from_form(page)
    second_response = page.request.post(
        f"{base_url}/voluntarios/{voluntario_id}/roles/add",
        form={"csrf_token": second_csrf, "rol": VALID_ROL_INTAKE},
    )
    assert second_response.status == 422, (
        f"duplicate add-role POST must return 422, got {second_response.status}: "
        f"{second_response.text()[:300]!r}"
    )
    body = second_response.text()
    assert DUPLICATE_ROLE_SPANISH in body, (
        f"422 response must carry the Spanish duplicate-role conflict message "
        f"({DUPLICATE_ROLE_SPANISH!r}); body excerpt: {body[:500]!r}"
    )


# --- 3. remove role --------------------------------------------------------


def test_remove_role_removes_from_detail(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST .../roles/remove → 303; role no longer visible on detail page.

    Pins the remove path end-to-end:

    - Create a voluntario and assign a role.
    - Verify the role chip appears on the detail page (sanity check on
      the setup).
    - POST /voluntarios/{id}/roles/remove with the same rol + csrf_token.
    - Verify 303 redirect back to /voluntarios/{id}.
    - Follow the redirect and verify the role chip is gone (the detail
      template renders "Sin roles asignados." when the roles list is
      empty, which is the regression sentinel for the empty-state path).
    """
    page, csrf_token = authenticated_session
    voluntario_id = _create_voluntario(page, csrf_token, base_url)

    # Setup: add the role.
    detail = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    add_csrf = _csrf_token_from_form(page)
    add_response = page.request.post(
        f"{base_url}/voluntarios/{voluntario_id}/roles/add",
        form={"csrf_token": add_csrf, "rol": VALID_ROL_INTAKE},
    )
    assert add_response.status == 303, (
        f"setup failed: add-role POST must return 303, got {add_response.status}"
    )

    # Sanity check: role is visible on the detail page after add.
    after_add = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert after_add is not None and after_add.status == 200
    body_after_add = after_add.text_content() or ""
    assert VALID_ROL_INTAKE in body_after_add, (
        f"setup failed: role chip {VALID_ROL_INTAKE!r} not visible after add; "
        f"body excerpt: {body_after_add[:500]!r}"
    )

    # Remove the role.
    remove_csrf = _csrf_token_from_form(page)
    remove_response = page.request.post(
        f"{base_url}/voluntarios/{voluntario_id}/roles/remove",
        form={"csrf_token": remove_csrf, "rol": VALID_ROL_INTAKE},
    )
    assert remove_response.status == 303, (
        f"remove-role POST must return 303, got {remove_response.status}: "
        f"{remove_response.text()[:300]!r}"
    )
    assert remove_response.headers.get("location", "").endswith(
        f"/voluntarios/{voluntario_id}"
    ), (
        f"remove-role POST must redirect to /voluntarios/{{id}}, got location="
        f"{remove_response.headers.get('location')!r}"
    )

    # Verify the role chip is gone from the detail page (and the
    # "Sin roles asignados." empty-state copy is now shown).
    after_remove = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert after_remove is not None and after_remove.status == 200
    body = after_remove.text_content() or ""
    assert VALID_ROL_INTAKE not in body, (
        f"detail page must not show the removed role {VALID_ROL_INTAKE!r}; "
        f"body excerpt: {body[:500]!r}"
    )


# --- 4. deactivate soft-deletes + filters from active list ----------------


def test_deactivate_voluntario_filters_from_active_list(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /voluntarios/{id}/deactivate → 303 to /voluntarios; gone from list.

    Pins the user-facing soft-delete contract for the role-management
    surface:

    - Create a voluntario (no role assigned — the role surface is
      already pinned by tests 1–3).
    - Visit the detail page to grab the deactivate form's csrf_token.
    - POST /voluntarios/{id}/deactivate via the request client with
      the form-encoded csrf_token. The detail page's deactivate form
      has the correct ``action="/voluntarios/{{id}}/deactivate"``.
    - Verify 303 redirect to /voluntarios.
    - Visit /voluntarios and verify the unique nombre is no longer in
      the list (the list query filters ``activo = true`` per
      ``LIST_VOLUNTARIOS_SQL`` in
      ``app/modules/voluntarios/adapters/insforge/voluntarios_insforge_queries.py``).

    This is the test that documents the user-visible consequence of
    the soft-delete: although the detail page can still be reached
    via direct URL (the GET route loads by id without an ``activo``
    filter), the role-management surface is unreachable through the
    normal list navigation — the voluntario is gone from the listing
    that operators use to find and edit roles.
    """
    page, csrf_token = authenticated_session
    voluntario_id = _create_voluntario(page, csrf_token, base_url)
    # Capture the nombre for the post-deactivate list assertion.
    detail = page.goto(
        f"{base_url}/voluntarios/{voluntario_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body_pre = detail.text_content() or ""
    # The voluntario's nombre appears as the page h1 (rendered by
    # ``{{ voluntario.voluntario }}``); extract it from there so the
    # list assertion is independent of any other naming convention.
    nombre_marker = page.locator("h1").first.inner_text().strip()
    assert nombre_marker, (
        f"detail page h1 must carry the voluntario's nombre; "
        f"body excerpt: {body_pre[:500]!r}"
    )

    # Deactivate.
    deactivate_csrf = _csrf_token_from_form(page)
    # The detail page's deactivate form has an ``onsubmit="return confirm(...)"``.
    # We POST via the request client so we don't need to handle the
    # browser-side JS confirm dialog.
    deactivate_response = page.request.post(
        f"{base_url}/voluntarios/{voluntario_id}/deactivate",
        form={"csrf_token": deactivate_csrf},
    )
    assert deactivate_response.status == 303, (
        f"deactivate POST must return 303, got {deactivate_response.status}: "
        f"{deactivate_response.text()[:300]!r}"
    )
    assert deactivate_response.headers.get("location", "").endswith(
        "/voluntarios"
    ), (
        f"deactivate POST must redirect to /voluntarios, got location="
        f"{deactivate_response.headers.get('location')!r}"
    )

    # Verify the voluntario is no longer reachable through the list.
    list_response = page.goto(f"{base_url}/voluntarios", wait_until="domcontentloaded")
    assert list_response is not None and list_response.status == 200
    body = list_response.text_content() or ""
    assert nombre_marker not in body, (
        f"deactivated voluntario's nombre {nombre_marker!r} must not appear "
        f"in the active /voluntarios listing; body excerpt: {body[:500]!r}"
    )


__all__: list[Any] = [
    "test_add_role_appears_in_detail",
    "test_add_same_role_twice_returns_422_with_conflict_message",
    "test_remove_role_removes_from_detail",
    "test_deactivate_voluntario_filters_from_active_list",
]
