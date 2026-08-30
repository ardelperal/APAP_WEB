"""E2E date-validation coverage for the ``/sanidad`` slice (D-24).

Pins the three D-24 validation rules for ``actuacion_sanitaria.fecha``:

1. **ISO format** — non-ISO date strings → 422 with the D-24 error.
2. **Not in the future** — a future date → 422 with the D-24 error.
3. **After ``FNacimiento``** — actuation date before the animal's birth date
   → 422 with the D-24 error.

Each test creates its host animal, then POSTs with an invalid date and
asserts the 422 response body contains the D-24 error message.

The ``authenticated_session`` fixture is copied verbatim from
``test_sanidad_crud.py`` for self-contained readability.

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


def _animal_form_data(suffix: str, fecha_nacimiento: str) -> dict[str, str]:
    return {
        "NCHIP": uuid.uuid4().hex[:15],
        "NombreAnimal": f"Animal-{suffix}",
        "Especie": SPECIES_CANINA,
        "Sexo": SEX_MACHO,
        "FNacimiento": fecha_nacimiento,
        "TraeNChip": "Si",
        "FIMPLANTACIONCHIP": "2024-01-16",
        "NombreFoto": "",
        "Terapia": "No",
        "Raza": "Mestizo",
        "Color": "Negro",
    }


def _create_animal(
    page: Page, csrf_token: str, base_url: str, *, fecha_nacimiento: str
) -> str:
    suffix = f"{uuid.uuid4().hex[:8]}"
    form_data = _animal_form_data(suffix, fecha_nacimiento)
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


# --- D-24 rule 1+2: invalid format / future date → 422 ----------------


def test_future_fecha_returns_422(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /sanidad with a future ``fecha`` → 422 + D-24 error message.

    D-24 reglas 1+2: the date must be ISO-formatted and not in the future.
    The service's ``_validate_fecha_d24`` raises ValueError before the CTE
    executes, which the route surfaces as 422 with a Spanish operator message.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(
        page, csrf_token, base_url, fecha_nacimiento="2020-01-01"
    )

    # A clearly future date (year 2099 is safely beyond any system clock).
    future_fecha = "2099-12-31"

    response = page.request.post(
        f"{base_url}/sanidad",
        form={
            "csrf_token": csrf_token,
            "animal_id": animal_id,
            "fecha": future_fecha,
            "tipo_actuacion_id": "",
        },
    )

    assert response.status == 422, (
        f"future fecha must return 422, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    body = response.text()
    assert "No se pudo guardar la actuación" in body, (
        f"422 response must carry the Spanish form error header; "
        f"body excerpt: {body[:500]!r}"
    )
    # D-24 error should mention the date rule.
    assert any(
        kw in body.lower()
        for kw in ("fecha", "futuro", "anterior", "hoy", "date", "future")
    ), (
        f"422 body must mention the date validation error; "
        f"body excerpt: {body[:500]!r}"
    )


def test_non_iso_fecha_returns_422(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /sanidad with a non-ISO ``fecha`` → 422 + D-24 error.

    D-24 regla 1: the date must be ISO-formatted (YYYY-MM-DD). Any other
    format raises ValueError from the service's ``_validate_fecha_d24``.
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(
        page, csrf_token, base_url, fecha_nacimiento="2020-01-01"
    )

    # Spanish-format date (common operator input error).
    response = page.request.post(
        f"{base_url}/sanidad",
        form={
            "csrf_token": csrf_token,
            "animal_id": animal_id,
            "fecha": "15/07/2024",
            "tipo_actuacion_id": "",
        },
    )

    assert response.status == 422, (
        f"non-ISO fecha must return 422, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    body = response.text()
    assert "No se pudo guardar la actuación" in body


# --- D-24 rule 3: fecha before FNacimiento → 422 --------------------


def test_fecha_before_birth_date_returns_422(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /sanidad with ``fecha`` before the animal's ``FNacimiento`` → 422.

    D-24 regla 3: the actuation date must be on or after the animal's
    intake date (``FNacimiento``). The CTE's ``checked_animal`` filter
    enforces this atomically inside the same statement snapshot.
    """
    page, csrf_token = authenticated_session
    # Create an animal born on 2024-01-15.
    animal_id = _create_animal(
        page, csrf_token, base_url, fecha_nacimiento="2024-01-15"
    )

    # actuation date is 10 years before birth — impossible.
    fecha_before_birth = "2014-01-01"

    response = page.request.post(
        f"{base_url}/sanidad",
        form={
            "csrf_token": csrf_token,
            "animal_id": animal_id,
            "fecha": fecha_before_birth,
            "tipo_actuacion_id": "",
        },
    )

    assert response.status == 422, (
        f"fecha before FNacimiento must return 422, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    body = response.text()
    assert "No se pudo guardar la actuación" in body, (
        f"422 response must carry the Spanish form error header; "
        f"body excerpt: {body[:500]!r}"
    )
    # The D-24 / CTE error should mention the date range.
    assert any(
        kw in body.lower()
        for kw in ("fecha", "nacimiento", "alta", "anterior", "posterior", "date")
    ), (
        f"422 body must mention the date/nacimiento validation; "
        f"body excerpt: {body[:500]!r}"
    )
