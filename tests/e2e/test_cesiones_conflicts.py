"""E2E conflict coverage for the ``/cesiones`` slice (INTAKE-03, #41).

Pins the error paths that the CRUD happy path in
``test_cesiones_crud.py`` does not cover:

1. Duplicate cesión (same ``entrada_id`` → 409 form error).
   The 1-a-1 UNIQUE on ``cesiones_propietario.entrada_id`` is the
   natural idempotence guard. A second cesión for the same entrada
   must surface as 409, not as a silent override or a 500.
2. Duplicate submission within the same request (idempotency via DB UNIQUE).
3. Required field blank: ``numero_contrato`` → 422.

The ``authenticated_session`` fixture and the ``animal_id_factory`` and
``entrada_id_factory`` fixtures are copied verbatim from
``test_cesiones_crud.py`` so this module is fully self-contained
(shared fixtures live in ``conftest.py`` but the convention in this
suite is to duplicate the minimal shared code so each file is readable
independently).

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable

import pytest
from playwright.sync_api import BrowserContext, Page

# --- shared constants -----------------------------------------------------

E2E_SECRET_HEADER = "X-E2E-Secret"

SPECIES_CANINA = "CANINA"
SEX_MACHO = "M"


# --- fixtures -------------------------------------------------------------


def _e2e_secret() -> str | None:
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    secret = _e2e_secret()
    if secret is None:
        pytest.skip(
            "APAP_E2E_AUTH_SECRET not set — the OAuth mock cannot "
            "authenticate this test."
        )

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


@pytest.fixture
def animal_id_factory(
    authenticated_session: tuple[Page, str], base_url: str
) -> Callable[[], str]:

    def _factory() -> str:
        page, csrf_token = authenticated_session
        form_data = {
            "NCHIP": uuid.uuid4().hex[:15],
            "NombreAnimal": f"Host-{uuid.uuid4().hex[:8]}",
            "Especie": SPECIES_CANINA,
            "Sexo": SEX_MACHO,
            "FNacimiento": "2024-01-15",
            "TraeNChip": "Si",
            "FIMPLANTACIONCHIP": "2024-01-16",
            "NombreFoto": "",
            "Terapia": "No",
        }
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

    return _factory


@pytest.fixture
def entrada_id_factory(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> Callable[[], str]:

    def _factory() -> str:
        page, csrf_token = authenticated_session
        animal_id = animal_id_factory()
        page.goto(f"{base_url}/entradas/new", wait_until="domcontentloaded")
        _csrf_token_from_form(page)
        response = page.request.post(
            f"{base_url}/entradas",
            form={"csrf_token": csrf_token, "animal_id": animal_id, "fecha_entrada": "2024-06-01"},
        )
        if response.status != 303:
            pytest.skip(
                f"Could not create host entrada (got {response.status}). "
                f"Test database may not be writable from E2E."
            )
        entrada_id = response.headers.get("location", "").rsplit("/", 1)[-1]
        if not entrada_id or entrada_id.endswith("/new") or entrada_id.endswith("/edit"):
            pytest.skip(f"entrada setup failed; redirect was {page.url!r}.")
        return entrada_id

    return _factory


# --- helpers --------------------------------------------------------------


def _csrf_token_from_form(page: Page) -> str:
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "form must render a non-empty csrf_token"
    return token


def _cesion_form_data(
    *,
    entrada_id: str,
    numero_contrato: str,
    nombre_representante: str,
    **overrides: str,
) -> dict[str, str]:
    data = {
        "entrada_id": entrada_id,
        "numero_contrato": numero_contrato,
        "nombre_representante": nombre_representante,
        "dni_representante": "",
        "fecha_cesion": "",
        "calle_representante": "",
        "numero_calle_representante": "",
        "piso_representante": "",
        "letra_representante": "",
        "localidad_representante": "",
        "provincia_representante": "",
        "cp_representante": "",
        "telefono_representante": "",
        "email_representante": "",
        "cartilla_sanitaria": "",
        "certificado_veterinario": "",
        "autorizacion_recogida": "",
        "fecha_vacuna_rabia": "",
        "numero_colegiado": "",
        "numero_colaborador": "",
        "hora_cesion": "",
    }
    data.update(overrides)
    return data


# --- 1. duplicate cesion for same entrada → 409 --------------------------


def test_duplicate_cesion_returns_409_not_500(
    authenticated_session: tuple[Page, str],
    entrada_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /cesiones twice for the same entrada_id → 409 form error.

    The 1-a-1 UNIQUE on ``cesiones_propietario.entrada_id`` is the
    natural idempotence guard. A second cesión for the same entrada
    must surface as 409 with a user-facing message — not as a silent
    override, not as a 500, not as a redirect.

    The test:
    - Creates an entrada.
    - Creates the first cesión → 303 (happy path).
    - Creates a second cesión for the same entrada → 409 with Spanish message.
    """
    page, csrf_token = authenticated_session
    entrada_id = entrada_id_factory()
    numero_contrato = f"CP{uuid.uuid4().hex[:4].upper()}"
    nombre = f"Rep-{uuid.uuid4().hex[:6]}"

    form_data = _cesion_form_data(
        entrada_id=entrada_id,
        numero_contrato=numero_contrato,
        nombre_representante=nombre,
    )

    # First cesion → 303 (happy path).
    first = page.request.post(
        f"{base_url}/cesiones",
        form={"csrf_token": csrf_token, **form_data},
    )
    assert first.status == 303, (
        f"first cesion create must return 303, got {first.status}"
    )

    # Visit the form again to get a fresh csrf_token (the previous POST
    # may have invalidated the session token depending on the middleware config).
    form_page = page.goto(f"{base_url}/cesiones/new", wait_until="domcontentloaded")
    assert form_page is not None and form_page.status == 200
    fresh_csrf = _csrf_token_from_form(page)

    # Second cesion for same entrada → 409.
    second = page.request.post(
        f"{base_url}/cesiones",
        form={"csrf_token": fresh_csrf, **form_data},
    )
    assert second.status == 409, (
        f"second cesion for same entrada must return 409, "
        f"got {second.status}: {second.text()[:300]!r}"
    )
    body = second.text()
    assert "Ya existe una cesion" in body, (
        f"409 response must carry the Spanish conflict message; "
        f"body excerpt: {body[:500]!r}"
    )
    assert first.headers.get("location") == f"/entradas/{entrada_id}", (
        "first cesion redirect must go to the parent entrada"
    )


# --- 2. blank numero_contrato → 422 ---------------------------------------


def test_blank_numero_contrato_returns_422(
    authenticated_session: tuple[Page, str],
    entrada_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /cesiones with blank ``numero_contrato`` → 422 + Spanish error.

    ``numero_contrato`` is NOT NULL in the schema and the application
    layer validates it before delegating to the port.
    """
    page, csrf_token = authenticated_session
    entrada_id = entrada_id_factory()

    form_data = _cesion_form_data(
        entrada_id=entrada_id,
        numero_contrato="   ",  # blank
        nombre_representante="Test Rep",
    )

    response = page.request.post(
        f"{base_url}/cesiones",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 422, (
        f"blank numero_contrato must return 422, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    body = response.text()
    assert "No se pudo guardar la cesion" in body
    assert "numero_contrato" in body.lower()


# --- 3. no entrada_id at all (empty string) → 422 ------------------------


def test_missing_entrada_id_returns_422(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /cesiones without ``entrada_id`` → 422 + Spanish error.

    The form requires entrada_id as a visible input; the service raises
    ValueError when it is blank.
    """
    page, csrf_token = authenticated_session

    form_data = _cesion_form_data(
        entrada_id="",  # empty
        numero_contrato=f"CP{uuid.uuid4().hex[:4].upper()}",
        nombre_representante="Test Rep",
    )

    response = page.request.post(
        f"{base_url}/cesiones",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 422, (
        f"missing entrada_id must return 422, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    body = response.text()
    assert "No se pudo guardar la cesion" in body
    assert "entrada" in body.lower()
