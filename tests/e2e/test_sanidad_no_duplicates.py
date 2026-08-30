"""E2E no-duplicate coverage for the ``/sanidad`` slice (D-24 / legacy §8.2).

Pins that creating two ``actuacion_sanitaria`` rows with the same
``animal_id`` + ``fecha`` + ``tipo_actuacion_id`` returns 409 (not 200
or 500). This is the ``MismaPruebaYFechaParaNChip`` constraint from
the legacy workflow (§8.2).

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset.
"""

from __future__ import annotations

import os
import uuid

import pytest
from playwright.sync_api import BrowserContext, Page

E2E_SECRET_HEADER = "X-E2E-Secret"

SPECIES_CANINA = "CANINA"
SEX_MACHO = "M"


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


def _animal_form_data(suffix: str) -> dict[str, str]:
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
    suffix = f"{uuid.uuid4().hex[:8]}"
    form_data = _animal_form_data(suffix)
    page.goto(f"{base_url}/animales/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create host animal (got {response.status}). "
            f"Test database may not be writable from E2E."
        )
    animal_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not animal_id or animal_id.endswith("/new") or animal_id.endswith("/edit"):
        pytest.skip(f"animal setup failed; redirect was {page.url!r}.")
    return animal_id


def _extract_catalogos_from_form(page: Page) -> list[dict[str, str]]:
    options = page.locator('select[name="tipo_actuacion_id"] option').all()
    catalogos = []
    for option in options:
        value = option.get_attribute("value") or ""
        text = option.inner_text().strip()
        if value and text and text != "—":
            catalogos.append({"id": value, "nombre": text})
    return catalogos


def _create_actuacion(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    animal_id: str,
    fecha: str,
    tipo_actuacion_id: str,
) -> str | None:
    """POST /sanidad. Returns actuacion_id on 303, None on non-303."""
    response = page.request.post(
        f"{base_url}/sanidad",
        form={
            "csrf_token": csrf_token,
            "animal_id": animal_id,
            "fecha": fecha,
            "tipo_actuacion_id": tipo_actuacion_id,
            "voluntario_id": "",
            "veterinario": "",
            "observaciones": "",
            "material_utilizado": "",
        },
    )
    if response.status != 303:
        return None
    actuacion_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not actuacion_id or "/" in actuacion_id and not actuacion_id[0].isalnum():
        return None
    return actuacion_id


# --- same animal + fecha + tipo → 409 on second create -----------------


def test_duplicate_same_animal_fecha_tipo_returns_409(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /sanidad twice with same animal_id + fecha + tipo_actuacion_id
    → first returns 303, second returns 409.

    D-24 / legacy §8.2: ``MismaPruebaYFechaParaNChip`` is enforced by a
    UNIQUE constraint on (animal_id, fecha, tipo_actuacion_id). The service
    translates InsForge's 409 into a 409 HTML response with a Spanish
    operator-facing message.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)

    # Read catalogos from the form to get a tipo_actuacion_id.
    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    catalogos = _extract_catalogos_from_form(page)
    assert catalogos, "expected at least one tipo_actuacion in catalogos"
    tipo_id = catalogos[0]["id"]

    fecha = "2024-07-15"

    # First create → 303.
    first_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id, fecha=fecha, tipo_actuacion_id=tipo_id,
    )
    assert first_id is not None, (
        "first actuacion create must succeed (303), got non-303: "
        "test setup may have failed"
    )

    # Second create with the same (animal, fecha, tipo) → 409.
    # Visit the form again to get a fresh csrf_token.
    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    fresh_csrf = _csrf_token_from_form(page)

    response = page.request.post(
        f"{base_url}/sanidad",
        form={
            "csrf_token": fresh_csrf,
            "animal_id": animal_id,
            "fecha": fecha,
            "tipo_actuacion_id": tipo_id,
            "voluntario_id": "",
            "veterinario": "",
            "observaciones": "",
            "material_utilizado": "",
        },
    )

    assert response.status == 409, (
        f"duplicate (animal_id + fecha + tipo_actuacion_id) must return 409, "
        f"got {response.status}: {response.text()[:300]!r}"
    )
    body = response.text()
    assert "Ya existe" in body or "duplicada" in body.lower() or "duplicate" in body.lower(), (
        f"409 response must carry a user-facing duplicate message; "
        f"body excerpt: {body[:500]!r}"
    )


# --- same animal + fecha but different tipo → both succeed ----------------


def test_same_animal_fecha_different_tipos_both_succeed(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """Two actuaciones with same animal_id + fecha but different tipo → both 303.

    The UNIQUE constraint is on (animal_id, fecha, tipo_actuacion_id).
    Using two different tipos should not conflict.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)

    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    catalogos = _extract_catalogos_from_form(page)
    assert len(catalogos) >= 2, (
        f"expected at least 2 tipo_actuacion in catalogos, got {len(catalogos)}"
    )

    tipo_a, tipo_b = catalogos[0]["id"], catalogos[1]["id"]
    fecha = "2024-08-15"

    first_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id, fecha=fecha, tipo_actuacion_id=tipo_a,
    )
    assert first_id is not None, "first actuacion must succeed"

    # Second create with different tipo → 303.
    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    fresh_csrf = _csrf_token_from_form(page)
    second_id = _create_actuacion(
        page, fresh_csrf, base_url,
        animal_id=animal_id, fecha=fecha, tipo_actuacion_id=tipo_b,
    )
    assert second_id is not None, (
        "second actuacion with different tipo must also succeed (303), "
        "got non-303 — the UNIQUE constraint should not fire for different tipos"
    )
    assert first_id != second_id, "two distinct actuaciones must have distinct IDs"
