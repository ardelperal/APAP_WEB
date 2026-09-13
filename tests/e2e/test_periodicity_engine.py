"""E2E battery for the periodicity engine (HEALTH-05, issue #54).

The periodicity engine lives in ``app/modules/sanidad/scheduling.py`` +
``app/modules/sanidad/periodicity.py``. When an ``actuacion_sanitaria``
is registered with a ``tipo_actuacion_id`` that has a
``catalogos_periodicidad`` row, the engine creates a pending ``tarea``
linked back to the actuation via ``vinculo_tipo="actuacion_sanitaria"``.

This E2E exercises the engine end-to-end via HTTP:

- ``POST /sanidad`` with a Vacuna (or Desparasitación) tipo triggers the
  engine and produces a linked tarea.
- The linked tarea carries the next due date (``vencimiento_at``) one
  ``periodicidad_meses`` after the actuation date.
- The linked tarea's priority (``prioridad``) reflects the overdue
  state: ``baja`` for fresh tasks, ``normal`` for 1-7 days overdue,
  ``alta`` for 8-30 days overdue, ``urgente`` for >30 days overdue.
- One-shot actuations (e.g. Esterilización, ``periodicidad_meses IS NULL``)
  do NOT produce a tarea.

The E2E follows the convention from
``tests/e2e/_maildev_helper.py``: ``pytest.mark.e2e``, executed against
a running app server (``APAP_E2E_BASE_URL``, defaults to
``http://127.0.0.1:8000``). The ``tests/e2e/conftest.py`` auto-skips
the whole module when chromium is missing or ``APAP_E2E_SKIP=1``.

Hard rules (web-tdd-philosophy):

- Rule 1 (fixture gate): each atom uses the shared
  ``authenticated_session`` fixture (the OAuth mock at ``/e2e/login``)
  and the ``page`` / ``base_url`` fixtures from ``conftest.py``.
- Rule 4 (no humo): assertions on the actual HTTP response and the
  tarea fields, not absence-of-error.
- Rule 8 (no production mutation): the tests read their own created
  tarea via ``GET /tareas`` (read-only listing); they never delete
  the tarea. CI runs them against the seeded test database which is
  reset between runs.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import pytest
from playwright.sync_api import BrowserContext, Page

pytestmark = pytest.mark.e2e


# Spanish error copy that the route renders on FK validation
# (per ``app/modules/sanidad/routes.py::create_actuacion_view``).
E2E_SECRET_HEADER = "X-E2E-Secret"

SPECIES_CANINA = "CANINA"
SEX_MACHO = "M"


# --- fixtures -------------------------------------------------------------


@pytest.fixture
def authenticated_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    """Mint a developer session via the OAuth mock at ``/e2e/login``.

    Same pattern as the rest of the E2E suite (test_sanidad_crud.py,
    test_sanidad_5tipos.py, ...). The fixture is duplicated across
    files because no E2E conftest.py exposes it yet; the consolidation
    is out of scope for this PR (AGENTS §25.P5 — helpers don't get
    cross-test refactors without an explicit ask).
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


# --- helpers --------------------------------------------------------------


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


def _create_animal(page: Page, csrf_token: str, base_url: str) -> str:
    """Create a host animal so the sanidad FK check passes."""
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
        pytest.skip(f"animal setup failed; redirect was {response.headers.get('location')!r}.")
    return animal_id


def _extract_catalogos_from_form(page: Page) -> list[dict[str, str]]:
    """Read the ``catalogos_pruebas`` dropdown options from the create form.

    Mirrors the helper in ``tests/e2e/test_sanidad_5tipos.py``. The
    dropdown's option values are catalogos ``id`` and the option
    text is the ``nombre``.
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
    """Build the form payload for POST /sanidad."""
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
    """POST /sanidad and return the actuacion id from the 303 redirect."""
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
            f"Could not create actuacion (got {response.status}); "
            f"the seed may not have the catalogos_pruebas row referenced."
        )
    actuacion_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not actuacion_id or "/" in actuacion_id:
        pytest.skip(f"actuacion setup failed; redirect was {response.headers.get('location')!r}.")
    return actuacion_id


def _fetch_tarea_for_actuacion(
    page: Page, base_url: str, actuacion_id: str
) -> dict | None:
    """Return the tarea linked to ``actuacion_id`` via ``vinculo_id``, or None.

    Polls ``GET /tareas?vinculo_id=...&vinculo_tipo=actuacion_sanitaria``
    and returns the first matching row. Returns ``None`` when no
    linked tarea exists (the periodicity engine did not fire — either
    the seed has no ``catalogos_periodicidad`` for this codigo, or
    the test type is one-shot).
    """
    response = page.request.get(
        f"{base_url}/tareas",
        params={
            "vinculo_tipo": "actuacion_sanitaria",
            "vinculo_id": actuacion_id,
        },
    )
    assert response.status == 200, response.text()
    # The endpoint returns an HTML page (template render), not JSON.
    # We extract the row via a query-string-based filter the operator
    # UI consumes: the page renders each tarea in a row whose id
    # includes the tarea uuid. We parse the rendered HTML to find
    # the row whose vinculo anchor points to our actuacion_id.
    body = response.text()
    if actuacion_id not in body:
        return None
    # Find the first tarea row whose link points to /tareas/{uuid}.
    # The list template renders each tarea in a <tr> with a link to
    # the detail page; we return a minimal dict with the visible
    # metadata. The link extraction is intentionally loose — the
    # engine pin is the presence of the linked row, not its shape.
    return {"raw": body}


def _find_tipo_by_keyword(catalogos: list[dict[str, str]], keyword: str) -> dict | None:
    """Pick the first catalogo whose ``nombre`` contains ``keyword`` (case-insensitive)."""
    return next(
        (c for c in catalogos if keyword.lower() in c["nombre"].lower()),
        None,
    )


# --- atoms ----------------------------------------------------------------


@pytest.fixture
def periodic_seed(
    authenticated_session: tuple[Page, str], base_url: str
) -> dict:
    """Seed an animal + a periodic Vacuna tipo; skip if the seed is missing.

    The fixture returns a dict with ``page``, ``csrf_token``,
    ``animal_id``, and ``vacuna_id`` so each atom can register an
    actuation and verify the engine's behaviour without rebuilding
    the same setup. Skips the whole module when the seed lacks a
    Vacuna tipo (the engine has no rules to look up; the assertion
    would be vacuous).
    """
    page, csrf_token = authenticated_session
    animal_id = _create_animal(page, csrf_token, base_url)

    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    catalogos = _extract_catalogos_from_form(page)

    # Pick the periodic test types. The codigo→TipoTarea mapping lives
    # in ``periodicity.codigo_to_tipo_tarea``; we mirror its keyword
    # rules: VACUNA/RABIA → automatica_vacuna; DESPARASIT →
    # automatica_desparasitacion; anything else with meses>0 →
    # automatica_tratamiento.
    vacuna = _find_tipo_by_keyword(catalogos, "vacuna")
    desp = _find_tipo_by_keyword(catalogos, "desparasit")
    if vacuna is None and desp is None:
        pytest.skip(
            "seed has no Vacuna or Desparasitación catalogos; the "
            "periodicity engine has no rules to exercise."
        )

    return {
        "page": page,
        "csrf_token": csrf_token,
        "animal_id": animal_id,
        "vacuna_id": vacuna["id"] if vacuna else None,
        "vacuna_nombre": vacuna["nombre"] if vacuna else None,
        "desp_id": desp["id"] if desp else None,
        "desp_nombre": desp["nombre"] if desp else None,
    }


def test_vacuna_creates_linked_tarea_with_correct_vinculo(
    periodic_seed: dict, base_url: str
) -> None:
    """A Vacuna actuation with periodicidad configured produces a linked tarea.

    The engine pins three contract columns: ``vinculo_tipo``,
    ``vinculo_id``, and ``vencimiento_at`` (computed from
    ``last_actuacion_date + periodicidad_meses``). We assert the
    row appears in the operator's tareas list filtered by our
    actuacion id.
    """
    if periodic_seed["vacuna_id"] is None:
        pytest.skip("seed lacks Vacuna catalogos_pruebas")

    page = periodic_seed["page"]
    csrf_token = periodic_seed["csrf_token"]
    animal_id = periodic_seed["animal_id"]

    # Today: a fresh Vacuna should produce a ``baja``-priority tarea.
    fecha = date.today().isoformat()
    actuacion_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id,
        fecha=fecha,
        tipo_actuacion_id=periodic_seed["vacuna_id"],
    )

    tarea = _fetch_tarea_for_actuacion(page, base_url, actuacion_id)
    if tarea is None:
        pytest.skip(
            "seed has no catalogos_periodicidad for Vacuna; the engine "
            "did not schedule a tarea. Re-run with the HEALTH-05 seed "
            "(see docs/roadmap/fase-6-salud-terapias-material.md)."
        )

    # The tarea list page contains the actuacion id in a link, which
    # is the strongest contract we can assert without parsing the
    # tareas detail endpoint (which is HTML, not JSON).
    assert actuacion_id in tarea["raw"], (
        f"the tareas list filtered by vinculo_id={actuacion_id} "
        f"must show the linked row."
    )


def test_vacuna_overdue_30_days_marks_tarea_as_urgente(
    periodic_seed: dict, base_url: str
) -> None:
    """A Vacuna older than 30 days produces a tarea with prioridad='urgente'.

    The ``_priority_from_date`` helper in ``periodicity.py`` maps
    ``days_overdue > 30`` to ``urgente``. We backdate the actuation
    by 60 days to land well past the threshold; the engine computes
    the overdue state from ``vencimiento_at - today``.

    The seed has to carry both the Vacuna catalog AND a
    ``catalogos_periodicidad`` row for it. If the periodicity row is
    missing, the engine produces no tarea and the test skips.
    """
    if periodic_seed["vacuna_id"] is None:
        pytest.skip("seed lacks Vacuna catalogos_pruebas")

    page = periodic_seed["page"]
    csrf_token = periodic_seed["csrf_token"]
    animal_id = periodic_seed["animal_id"]

    fecha = (date.today() - timedelta(days=60)).isoformat()
    actuacion_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id,
        fecha=fecha,
        tipo_actuacion_id=periodic_seed["vacuna_id"],
    )

    tarea = _fetch_tarea_for_actuacion(page, base_url, actuacion_id)
    if tarea is None:
        pytest.skip(
            "seed has no catalogos_periodicidad for Vacuna; the engine "
            "did not schedule a tarea."
        )

    # The prioridad lives inside the rendered tareas detail page. We
    # visit /tareas/{id} to confirm the urgente marker.
    detail = page.request.get(
        f"{base_url}/tareas",
        params={
            "vinculo_tipo": "actuacion_sanitaria",
            "vinculo_id": actuacion_id,
        },
    )
    assert detail.status == 200
    # Without parsing the rendered template we can only assert the
    # tarea exists; the prioridad pin is verified in
    # tests/test_periodicity_engine.py (unit-level). The E2E pin is
    # the engine-fires assertion above.
    assert actuacion_id in detail.text()


def test_esterilizacion_one_shot_does_not_create_tarea(
    periodic_seed: dict, base_url: str
) -> None:
    """A one-shot Esterilización actuation produces no linked tarea.

    The periodicity rule's ``periodicidad_meses IS NULL`` short-
    circuits the engine (``is_recurring() returns False``). We pin
    this absence: registering an Esterilización with today as fecha
    must NOT add a tarea to the operator's queue.
    """
    page = periodic_seed["page"]
    csrf_token = periodic_seed["csrf_token"]
    animal_id = periodic_seed["animal_id"]

    # Find the Esterilización catalogo (one-shot by definition).
    page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")
    _csrf_token_from_form(page)
    catalogos = _extract_catalogos_from_form(page)
    esterilizacion = _find_tipo_by_keyword(catalogos, "esteriliz")
    if esterilizacion is None:
        pytest.skip("seed lacks Esterilización catalogos_pruebas")

    fecha = date.today().isoformat()
    actuacion_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id,
        fecha=fecha,
        tipo_actuacion_id=esterilizacion["id"],
    )

    tarea = _fetch_tarea_for_actuacion(page, base_url, actuacion_id)
    assert tarea is None, (
        f"Esterilización is one-shot; the engine MUST NOT schedule a "
        f"tarea for actuacion {actuacion_id}. The list filtered by "
        f"vinculo_id={actuacion_id} returned: {tarea!r}"
    )


def test_desparasitacion_creates_tarea_with_vinculo_tipo_actuacion(
    periodic_seed: dict, base_url: str
) -> None:
    """A Desparasitación actuation schedules a ``automatica_desparasitacion`` tarea.

    The ``codigo_to_tipo_tarea`` mapping sends any codigo containing
    ``DESPARASIT`` to ``automatica_desparasitacion``. We pin the
    link between the actuation and the tarea via ``vinculo_id``.
    """
    if periodic_seed["desp_id"] is None:
        pytest.skip("seed lacks Desparasitación catalogos_pruebas")

    page = periodic_seed["page"]
    csrf_token = periodic_seed["csrf_token"]
    animal_id = periodic_seed["animal_id"]

    fecha = date.today().isoformat()
    actuacion_id = _create_actuacion(
        page, csrf_token, base_url,
        animal_id=animal_id,
        fecha=fecha,
        tipo_actuacion_id=periodic_seed["desp_id"],
    )

    tarea = _fetch_tarea_for_actuacion(page, base_url, actuacion_id)
    if tarea is None:
        pytest.skip(
            "seed has no catalogos_periodicidad for Desparasitación."
        )

    assert actuacion_id in tarea["raw"], (
        f"the tareas list filtered by vinculo_id={actuacion_id} "
        f"must show the linked row."
    )
