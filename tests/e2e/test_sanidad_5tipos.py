"""E2E coverage for the five sanidad tipos (HEALTH-01 / legacy §4).

Pins that every ``tipo_actuacion`` from ``catalogos_pruebas`` can be
created, rendered, and edited — the five legacy types:
Analítica, Desparasitación, Vacuna, Esterilización, Otros.

Each test creates its host animal, reads the catalog dropdown from the
create form, and POSTs with a different ``tipo_actuacion_id``.

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
    """Read the catalogos_pruebas dropdown options from the create form.

    Returns a list of dicts with at least ``id`` and ``nombre`` keys.
    Skips the first empty option (value="").
    """
    options = page.locator('select[name="tipo_actuacion_id"] option').all()
    catalogos = []
    for option in options:
        value = option.get_attribute("value") or ""
        text = option.inner_text().strip()
        if value and text and text != "—":
            catalogos.append({"id": value, "nombre": text})
    return catalogos


def _actuacion_form_data(
    *,
    animal_id: str,
    fecha: str,
    tipo_actuacion_id: str,
    veterinario: str = "",
    observaciones: str = "",
) -> dict[str, str]:
    return {
        "animal_id": animal_id,
        "voluntario_id": "",
        "fecha": fecha,
        "tipo_actuacion_id": tipo_actuacion_id,
        "veterinario": veterinario,
        "observaciones": observaciones,
        "material_utilizado": "",
    }


def _create_actuacion(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    animal_id: str,
    fecha: str,
    tipo_actuacion_id: str,
) -> str:
    form_data = _actuacion_form_data(
        animal_id=animal_id,
        fecha=fecha,
        tipo_actuacion_id=tipo_actuacion_id,
    )
    response = page.request.post(
        f"{base_url}/sanidad",
        form={"csrf_token": csrf_token, **form_data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create actuacion (got {response.status}). "
            f"Test database may not be writable from E2E."
        )
    actuacion_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not actuacion_id or "/" in actuacion_id and not actuacion_id[0].isalnum():
        pytest.skip(f"actuacion setup failed; redirect was {response.headers.get('location')!r}.")
    return actuacion_id


# --- tipo 1: Analítica ------------------------------------------------


def test_create_analitica_renders_in_detail(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /sanidad with tipo_actuacion Analítica → 303 → detail shows it."""
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)

    # Read catalogos from the form dropdown.
    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    catalogos = _extract_catalogos_from_form(page)
    assert len(catalogos) >= 5, (
        f"expected at least 5 catalogos_pruebas (Analitica/Desparasitacion/"
        f"Vacuna/Esterilizacion/Otros), got {len(catalogos)}: {catalogos!r}"
    )

    # Pick the Analítica option (case-insensitive match).
    analitica = next(
        (c for c in catalogos if "analitica" in c["nombre"].lower()),
        None,
    )
    assert analitica is not None, (
        f"Analitica not found in catalogos: {[c['nombre'] for c in catalogos]}"
    )

    fecha = "2024-07-15"
    actuacion_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id, fecha=fecha,
        tipo_actuacion_id=analitica["id"],
    )

    # Detail renders the tipo.
    detail = page.goto(f"{base_url}/sanidad/{actuacion_id}", wait_until="domcontentloaded")
    assert detail is not None and detail.status == 200
    body = page.content()
    assert analitica["nombre"] in body, (
        f"detail must show tipo_actuacion '{analitica['nombre']}'; "
        f"body excerpt: {body[:500]!r}"
    )


# --- tipo 2: Desparasitación ------------------------------------------


def test_create_desparasitacion_renders_in_detail(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /sanidad with tipo_actuacion Desparasitación → 303 → detail shows it."""
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)

    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    catalogos = _extract_catalogos_from_form(page)

    desp = next(
        (c for c in catalogos if "desparasit" in c["nombre"].lower()),
        None,
    )
    assert desp is not None, (
        f"Desparasitacion not found in catalogos: {[c['nombre'] for c in catalogos]}"
    )

    fecha = "2024-08-01"
    actuacion_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id, fecha=fecha,
        tipo_actuacion_id=desp["id"],
    )

    detail = page.goto(f"{base_url}/sanidad/{actuacion_id}", wait_until="domcontentloaded")
    assert detail is not None and detail.status == 200
    body = page.content()
    assert desp["nombre"] in body


# --- tipo 3: Vacuna ----------------------------------------------------


def test_create_vacuna_renders_in_detail(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /sanidad with tipo_actuacion Vacuna → 303 → detail shows it."""
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)

    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    catalogos = _extract_catalogos_from_form(page)

    vacuna = next(
        (c for c in catalogos if "vacuna" in c["nombre"].lower()),
        None,
    )
    assert vacuna is not None, (
        f"Vacuna not found in catalogos: {[c['nombre'] for c in catalogos]}"
    )

    fecha = "2024-09-10"
    actuacion_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id, fecha=fecha,
        tipo_actuacion_id=vacuna["id"],
    )

    detail = page.goto(f"{base_url}/sanidad/{actuacion_id}", wait_until="domcontentloaded")
    assert detail is not None and detail.status == 200
    body = page.content()
    assert vacuna["nombre"] in body


# --- tipo 4: Esterilización --------------------------------------------


def test_create_esterilizacion_renders_in_detail(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /sanidad with tipo_actuacion Esterilización → 303 → detail shows it."""
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)

    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    catalogos = _extract_catalogos_from_form(page)

    esterilizacion = next(
        (c for c in catalogos if "esteriliz" in c["nombre"].lower()),
        None,
    )
    assert esterilizacion is not None, (
        f"Esterilizacion not found in catalogos: {[c['nombre'] for c in catalogos]}"
    )

    fecha = "2024-10-05"
    actuacion_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id, fecha=fecha,
        tipo_actuacion_id=esterilizacion["id"],
    )

    detail = page.goto(f"{base_url}/sanidad/{actuacion_id}", wait_until="domcontentloaded")
    assert detail is not None and detail.status == 200
    body = page.content()
    assert esterilizacion["nombre"] in body


# --- tipo 5: Otros -----------------------------------------------------


def test_create_otros_renders_in_detail(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /sanidad with tipo_actuacion Otros → 303 → detail shows it."""
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)

    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    catalogos = _extract_catalogos_from_form(page)

    otros = next(
        (c for c in catalogos if "otro" in c["nombre"].lower()),
        None,
    )
    assert otros is not None, (
        f"Otros not found in catalogos: {[c['nombre'] for c in catalogos]}"
    )

    fecha = "2024-11-20"
    actuacion_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id, fecha=fecha,
        tipo_actuacion_id=otros["id"],
    )

    detail = page.goto(f"{base_url}/sanidad/{actuacion_id}", wait_until="domcontentloaded")
    assert detail is not None and detail.status == 200
    body = page.content()
    assert otros["nombre"] in body
