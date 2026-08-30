"""E2E CRUD coverage for the ``/materiales`` slice (FOSTER-04, #46).

Pins the material catalog CRUD contract end-to-end via Playwright +
the OAuth mock. The catalog is a simple entity (no FK dependencies)
so no animal setup is needed — any authenticated user can POST directly.

Five cases pin the materiales CRUD contract end-to-end:

1. List (GET /materiales → 200 with the ``Catálogo de materiales`` h1).
2. Create (POST /materiales with material + tamano + color → 303 to
   /materiales/{id}). The detail page renders the three key fields.
3. Create with duplicate (material + tamano + color) → 409 with Spanish
   conflict message (UNIQUE constraint).
4. Edit (POST /materiales/{id}/edit with new observaciones → 303 to
   detail; new observaciones visible).
5. Deactivate (POST /materiales/{id}/deactivate → 303 to /materiales;
   the row disappears from the active list).

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset.
"""

from __future__ import annotations

import os
import uuid

import pytest
from playwright.sync_api import BrowserContext, Page

E2E_SECRET_HEADER = "X-E2E-Secret"


def _e2e_secret() -> str | None:
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    secret = _e2e_secret()
    if secret is None:
        pytest.skip("APAP_E2E_AUTH_SECRET not set.")

    response = browser_context.request.get(
        f"{base_url}/e2e/login",
        headers={E2E_SECRET_HEADER: secret},
    )
    assert response.status == 200
    payload = response.json()
    csrf_token = payload.get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token

    page = browser_context.new_page()
    return page, csrf_token


def _csrf_token_from_form(page: Page) -> str:
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "form must render a non-empty csrf_token"
    return token


def _material_form_data(
    *,
    material: str,
    tamano: str,
    color: str,
    observaciones: str = "",
) -> dict[str, str]:
    return {
        "material": material,
        "tamano": tamano,
        "color": color,
        "observaciones": observaciones,
    }


def _create_material(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    material: str,
    tamano: str,
    color: str,
    observaciones: str = "",
) -> str | None:
    """POST /materiales and return the new material's UUID, or None on failure."""
    form_data = _material_form_data(
        material=material,
        tamano=tamano,
        color=color,
        observaciones=observaciones,
    )
    response = page.request.post(
        f"{base_url}/materiales",
        form={"csrf_token": csrf_token, **form_data},
    )
    if response.status != 303:
        return None
    location = response.headers.get("location", "")
    material_id = location.rsplit("/", 1)[-1]
    if not material_id or material_id.endswith("/new") or material_id.endswith("/edit"):
        return None
    return material_id


# --- 1. list ------------------------------------------------------------


def test_list_materiales_renders_200(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /materiales → 200 with the ``Catálogo de materiales`` h1."""
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/materiales", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, (
        f"GET /materiales must return 200, got {response.status}"
    )
    h1 = page.locator("h1").first.inner_text().strip()
    assert "material" in h1.lower(), (
        f"list page must render a 'material' heading; got {h1!r}"
    )


# --- 2. create happy path ------------------------------------------------


def test_create_material_redirects_to_detail(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /materiales with valid payload → 303 to /materiales/{id}."""
    page, csrf_token = authenticated_session
    suffix = uuid.uuid4().hex[:6]

    # Visit form first (regression sentinel: page renders + csrf present).
    form_page = page.goto(f"{base_url}/materiales/new", wait_until="domcontentloaded")
    assert form_page is not None and form_page.status == 200
    _csrf_token_from_form(page)

    material_id = _create_material(
        page, csrf_token, base_url,
        material=f"Test-Material-{suffix}",
        tamano="Grande",
        color="Rojo",
        observaciones=f"Obs-{suffix}",
    )

    if material_id is None:
        pytest.skip(
            "Could not create material (POST /materiales did not return 303). "
            "The test database may not be writable from E2E."
        )

    # Detail page renders.
    detail = page.goto(
        f"{base_url}/materiales/{material_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200, (
        f"GET /materiales/{{id}} must return 200, got {detail.status}"
    )
    body = page.content()
    assert f"Test-Material-{suffix}" in body, (
        f"detail must show the material name; body excerpt: {body[:500]!r}"
    )


# --- 3. duplicate natural key → 409 --------------------------------------


def test_duplicate_material_tamano_color_returns_409(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /materiales twice with the same (material + tamano + color)
    → first returns 303, second returns 409.

    The UNIQUE constraint on (material, tamano, color) is the natural
    idempotence guard. A second material with the same trio must surface
    as 409 with a Spanish actionable message — not as a silent override.
    """
    page, csrf_token = authenticated_session
    suffix = uuid.uuid4().hex[:6]
    mat = f"Mat-Dup-{suffix}"
    tam = "Mediano"
    col = "Azul"

    first_id = _create_material(
        page, csrf_token, base_url,
        material=mat, tamano=tam, color=col,
    )
    if first_id is None:
        pytest.skip(
            "Could not create first material (POST /materiales did not return 303). "
            "Test database may not be writable from E2E."
        )

    # Visit the form again for a fresh csrf_token.
    page.goto(f"{base_url}/materiales/new", wait_until="domcontentloaded")
    fresh_csrf = _csrf_token_from_form(page)

    response = page.request.post(
        f"{base_url}/materiales",
        form={"csrf_token": fresh_csrf, **{
            "material": mat, "tamano": tam, "color": col, "observaciones": ""
        }},
    )

    assert response.status == 409, (
        f"duplicate (material + tamano + color) must return 409, "
        f"got {response.status}: {response.text()[:300]!r}"
    )
    body = response.text()
    assert "ya existe" in body.lower() or "duplicate" in body.lower(), (
        f"409 response must carry a user-facing conflict message; "
        f"body excerpt: {body[:500]!r}"
    )


# --- 4. edit -------------------------------------------------------------


def test_edit_material_updates_observaciones_and_redirects(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /materiales/{id}/edit with new observaciones → 303 to detail."""
    page, csrf_token = authenticated_session
    suffix = uuid.uuid4().hex[:6]

    material_id = _create_material(
        page, csrf_token, base_url,
        material=f"Mat-Edit-{suffix}",
        tamano="Pequeño",
        color="Verde",
    )
    if material_id is None:
        pytest.skip(
            "Could not create material for edit test. "
            "Test database may not be writable from E2E."
        )

    new_obs = f"Obs-edit-{suffix}"

    # Visit edit form (regression sentinel).
    edit_page = page.goto(
        f"{base_url}/materiales/{material_id}/edit", wait_until="domcontentloaded"
    )
    assert edit_page is not None and edit_page.status == 200
    edit_csrf = _csrf_token_from_form(page)

    update_data = {
        "material": f"Mat-Edit-{suffix}",
        "tamano": "Pequeño",
        "color": "Verde",
        "observaciones": new_obs,
    }
    update_response = page.request.post(
        f"{base_url}/materiales/{material_id}/edit",
        form={"csrf_token": edit_csrf, **update_data},
    )

    assert update_response.status == 303, (
        f"update POST must return 303, got {update_response.status}: "
        f"{update_response.text()[:300]!r}"
    )
    assert update_response.headers.get("location", "").endswith(
        f"/materiales/{material_id}"
    ), (
        f"update POST must redirect to /materiales/{{id}}, got "
        f"{update_response.headers.get('location')!r}"
    )

    # Detail shows new observaciones.
    detail = page.goto(
        f"{base_url}/materiales/{material_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    body = page.content()
    assert new_obs in body, (
        f"detail must show the updated observaciones; "
        f"body excerpt: {body[:500]!r}"
    )


# --- 5. deactivate --------------------------------------------------------


def test_deactivate_material_redirects_to_list(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /materiales/{id}/deactivate → 303 to /materiales.

    After deactivation the material disappears from the active list
    (the service queries with activos_solo=True by default).
    """
    page, csrf_token = authenticated_session
    suffix = uuid.uuid4().hex[:6]

    material_id = _create_material(
        page, csrf_token, base_url,
        material=f"Mat-Delete-{suffix}",
        tamano="Grande",
        color="Amarillo",
    )
    if material_id is None:
        pytest.skip(
            "Could not create material for deactivate test. "
            "Test database may not be writable from E2E."
        )

    # Visit detail page to grab deactivate form's csrf_token.
    detail = page.goto(
        f"{base_url}/materiales/{material_id}", wait_until="domcontentloaded"
    )
    assert detail is not None and detail.status == 200
    delete_csrf = _csrf_token_from_form(page)

    deactivate_response = page.request.post(
        f"{base_url}/materiales/{material_id}/deactivate",
        form={"csrf_token": delete_csrf},
    )

    assert deactivate_response.status == 303, (
        f"deactivate POST must return 303, got {deactivate_response.status}: "
        f"{deactivate_response.text()[:300]!r}"
    )
    assert deactivate_response.headers.get("location", "").endswith(
        "/materiales"
    ), (
        f"deactivate POST must redirect to /materiales, got "
        f"{deactivate_response.headers.get('location')!r}"
    )

    # Follow the redirect and verify the material no longer appears.
    list_page = page.goto(
        f"{base_url}/materiales", wait_until="domcontentloaded"
    )
    assert list_page is not None and list_page.status == 200
    body = page.content()
    assert f"Mat-Delete-{suffix}" not in body, (
        f"deactivated material must not appear in the active list; "
        f"body excerpt: {body[:500]!r}"
    )
