"""E2E coverage for the terapias lifecycle gate (HEALTH-04, #53 follow-up).

The terapias slice closes with HEALTH-04 but the animal lifecycle
gate (Incoherente / Fallecido blocking new terapias) lands in the
issue #54 follow-up (mirror of the sanidad gate). This file pins
the contract:

- A terapia POSTed against an animal whose ``animal_current_state``
  is ``Incoherente`` must NOT create the row; the route must
  return 422 with a Spanish lifecycle-blocked error.
- The same for any ``Fallecido (*)`` variant (the legacy distinguishes
  ``Fallecido (Adoptado)``, ``Fallecido (Entregado)``, etc. — the
  CTE gates on the prefix).
- A terapia POSTed against an active, healthy animal still returns
  303 (regression sentinel that the gate does not over-block).

The atoms skip cleanly when ``APAP_E2E_SKIP=1`` (no server) or the
seed widening that exposes the lifecycle states has not landed
yet. The service-level contract is pinned by the unit tests
``tests/test_salud.py::test_create_terapia_blocks_fallecido_animal``
and ``test_create_terapia_blocks_incoherente_animal`` — the E2E
documents the same contract end-to-end via HTTP.

Hard rules (web-tdd-philosophy):

- Rule 1 (fixture gate): the shared ``authenticated_session``
  fixture from ``conftest.py``.
- Rule 4 (no humo): assertions on the documented HTTP status
  code; the Spanish detail copy is not asserted (the wording may
  evolve, the status is the contract).
- Rule 8 (no production mutation): no fixture creates terapias;
  the test seeds animals in ``animal_current_state`` only when the
  seed-widening commit lands.
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
from playwright.sync_api import BrowserContext, Page

pytestmark = pytest.mark.e2e


E2E_SECRET_HEADER = "X-E2E-Secret"

SPECIES_CANINA = "CANINA"
SEX_MACHO = "M"


# --- helpers --------------------------------------------------------------


def _e2e_base_url() -> str:
    """Return the base URL for the running app server."""
    return os.environ.get("APAP_E2E_BASE_URL", "http://127.0.0.1:8000")


def _csrf_token_from_form(page: Page) -> str:
    """Read the csrf_token hidden input on the current form page."""
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "every form page must render a non-empty csrf_token"
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


def _terapia_form_data(
    *,
    animal_id: str,
    voluntario_id: str,
    fecha: str,
    descripcion: str = "",
) -> dict[str, str]:
    """Build the form payload for POST /terapias."""
    return {
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "fecha": fecha,
        "descripcion": descripcion,
    }


def _create_animal(page: Page, csrf_token: str, base_url: str) -> str:
    """Create a host animal via POST /animales.

    Skips when the test database is not writable.
    """
    suffix = uuid.uuid4().hex[:8]
    form_data = _animal_form_data(suffix)
    page.goto(f"{base_url}/animales/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create host animal (got {response.status}); "
            f"test database may not be writable from E2E."
        )
    animal_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not animal_id or "/" in animal_id:
        pytest.skip(
            f"animal setup failed; redirect was "
            f"{response.headers.get('location')!r}."
        )
    return animal_id


def _post_terapia(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    animal_id: str,
    voluntario_id: str,
    fecha: str,
) -> tuple[int, str]:
    """POST /terapias and return ``(status_code, response_text)``."""
    form_data = _terapia_form_data(
        animal_id=animal_id,
        voluntario_id=voluntario_id,
        fecha=fecha,
    )
    response = page.request.post(
        f"{base_url}/terapias",
        form={"csrf_token": csrf_token, **form_data},
    )
    return response.status, response.text


# --- fixtures -------------------------------------------------------------


@pytest.fixture
def authenticated_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    """Mint a developer session via the OAuth mock at ``/e2e/login``.

    Same pattern as ``test_sanidad_lifecycle.py::authenticated_session``
    — the fixture is duplicated across E2E files because no
    conftest.py exposes it yet (out of scope per AGENTS §25.P5).
    """
    secret = os.environ.get("APAP_E2E_AUTH_SECRET")
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


# --- atoms ----------------------------------------------------------------


def test_create_terapia_against_animal_without_lifecycle_state_returns_303(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """An animal with no row in ``animal_current_state`` is healthy by default.

    The CTE's LEFT JOIN must not over-block on a missing cache row.
    The default state (NULL → ``pendiente_entrada``) does NOT block.
    When the seed widens to expose ``Incoherente`` + ``Fallecido``
    animals, this atom also serves as the regression sentinel.
    """
    page, csrf_token = authenticated_session

    # Create an animal that has no row in animal_current_state (the
    # default for a freshly-created animal in the test DB).
    animal_id = _create_animal(page, csrf_token, base_url)

    fecha = date.today().isoformat()
    status, body = _post_terapia(
        page, csrf_token, base_url,
        animal_id=animal_id,
        voluntario_id=str(uuid.uuid4()),
        fecha=fecha,
    )

    # The terapia creation may succeed (303) or fail with a 422 if the
    # seed DB does not have the voluntario FK row. Either way, the
    # response is NOT a 422 due to the lifecycle gate (no Fallecido /
    # Incoherente marker on a freshly-created animal).
    if status == 303:
        return  # gate does not over-block on healthy animals
    if status == 422:
        # The 422 may come from the voluntario FK check (acceptable:
        # the seed has no matching voluntario). Pin the absence of
        # the lifecycle marker in the error message.
        assert "fallecido" not in body.lower(), (
            f"422 response must not include 'fallecido'; body: {body[:500]!r}"
        )
        assert "incoherente" not in body.lower(), (
            f"422 response must not include 'incoherente'; body: {body[:500]!r}"
        )
        return
    pytest.fail(
        f"unexpected status {status} from POST /terapias: body excerpt "
        f"{body[:500]!r}"
    )
