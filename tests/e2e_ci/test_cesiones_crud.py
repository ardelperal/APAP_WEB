"""E2E CRUD coverage for the ``/cesiones`` slice under the CI browser gate.

Port of ``tests/e2e/test_cesiones_crud.py`` (issue #1095, slice 2) so the
fail-closed CI smoke suite (``tests/e2e_ci/``) actually exercises the
owner-surrender (cesión por propietario) flow.

Five cases pin the cesiones CRUD contract end-to-end:

1. Form renders (GET /cesiones/new -> 200; h1 + all 21 legacy
   fields present — P1 fidelity to ``TbCesionPorPropietario``).
2. CSRF token present in form (regression sentinel for AGENTS.md
   rule 10 — every form must carry the token, otherwise the
   middleware rejects every POST).
3. Create happy path (POST /cesiones with valid entrada_id ->
   303 to /entradas/{entrada_id}; the cesión lives 1-a-1 with its
   intake per P1 fidelity).
4. Create with non-existent ``entrada_id`` -> 422 with the Spanish
   form error header.
5. Create with blank ``nombre_representante`` -> 422 with the
   Spanish form error header.

The ``/cesiones`` slice requires a pre-existing ``entrada_id`` row
because the FK validation rejects ``entrada_id`` values that do not
reference an existing entrada row. The entrada in turn requires a
pre-existing ``animal_id``. Both come from the shared factories in
``tests/e2e_ci/conftest.py`` (``animal_id_factory`` chains into
``entrada_id_factory``).

The shared constants and form-data builders
(``CESION_LEGACY_FIELDS``, ``CESION_FORM_H1_LOWER_FRAGMENT``,
``CESION_SAVE_FAILED_SPANISH``, ``cesion_form_data``) live in
``tests/e2e_ci/_crud_helpers.py``. The session fixture and factories
live in ``tests/e2e_ci/conftest.py``.

Fail-closed contract: under this gate a missing
``APAP_E2E_AUTH_SECRET``, a failed ``/e2e/login``, or a non-303 on
a happy path is a HARD failure, never a skip. The original
``tests/e2e/test_cesiones_crud.py`` skipped when
``APAP_E2E_AUTH_SECRET`` was unset and when the host animal or
host entrada could not be created; the port removes every
``pytest.skip`` so the gate stays loud.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from playwright.sync_api import Page

from tests.e2e_ci._crud_helpers import (
    CESION_FORM_H1_LOWER_FRAGMENT,
    CESION_LEGACY_FIELDS,
    CESION_SAVE_FAILED_SPANISH,
    cesion_form_data,
    csrf_token_from_form,
)

# --- 1. form renders (21 legacy fields) -----------------------------------


def test_form_renders_200_with_all_legacy_fields(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /cesiones/new -> 200; the surrender form renders with every
    legacy ``TbCesionPorPropietario`` column as a named input.

    P1 fidelity: every legacy column must be visible on the form so
    the operator can capture the full superset. The
    ``CESION_LEGACY_FIELDS`` constant in ``tests/e2e_ci/_crud_helpers.py``
    carries 21 names (one per legacy column plus the ``hora_cesion``
    time field). Slice 2 preserves the list and its count intact.
    """
    page, _csrf = authenticated_session

    response = page.goto(
        f"{base_url}/cesiones/new", wait_until="domcontentloaded"
    )
    assert response is not None
    assert response.status == 200, (
        f"GET /cesiones/new must return 200, got {response.status}"
    )

    # h1 confirms the correct page rendered (not an error page).
    h1 = page.locator("h1").first.inner_text().strip()
    assert CESION_FORM_H1_LOWER_FRAGMENT in h1.lower(), (
        f"form page must render a '{CESION_FORM_H1_LOWER_FRAGMENT}' heading; "
        f"got {h1!r}"
    )

    # Every legacy column present as a named input.
    for field in CESION_LEGACY_FIELDS:
        locator = page.locator(f'[name="{field}"]')
        assert locator.count() > 0, (
            f"cesiones form missing legacy field {field!r}; "
            f"P1 fidelity requires every TbCesionPorPropietario column."
        )


# --- 2. form includes CSRF token ------------------------------------------


def test_form_includes_csrf_token(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /cesiones/new renders a hidden csrf_token input.

    AGENTS.md rule 10: every POST form must carry a csrf_token; the
    CsrfMiddleware validates it before the handler runs. This is a
    regression sentinel — if the form template stops rendering the
    token, every POST returns 403 and the whole slice breaks.
    """
    page, _ = authenticated_session

    page.goto(f"{base_url}/cesiones/new", wait_until="domcontentloaded")
    token = csrf_token_from_form(page)
    assert token, "form must render a non-empty csrf_token hidden input"


# --- 3. create happy path --------------------------------------------------


def test_create_cesion_redirects_to_parent_entrada(
    authenticated_session: tuple[Page, str],
    entrada_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /cesiones with valid payload -> 303 to /entradas/{entrada_id}.

    The cesión is 1-a-1 with the intake (FK UNIQUE on ``entrada_id``
    per P1 fidelity, see ``app/modules/cesiones/service.py``); the
    operator inspects the surrender from the existing intake detail
    page. A standalone ``/cesiones/{id}`` view is deferred to Fase 7.

    The test pins:
    - 303 redirect target is ``/entradas/{entrada_id}``.
    - The parent entrada detail page renders (200).
    - No 422 / 409 on the first cesion for this entrada.
    """
    page, csrf_token = authenticated_session
    entrada_id = entrada_id_factory()
    numero_contrato = f"CP{uuid.uuid4().hex[:4].upper()}"
    nombre = f"Representante {uuid.uuid4().hex[:6]}"

    # Visit the form first (regression sentinel: page must render + csrf present).
    form_page = page.goto(
        f"{base_url}/cesiones/new", wait_until="domcontentloaded"
    )
    assert form_page is not None and form_page.status == 200
    csrf_token_from_form(page)

    # POST the surrender form directly via the request client (mirroring the
    # unit-test pattern) because the form action is self-submitting.
    form_data = cesion_form_data(
        entrada_id=entrada_id,
        numero_contrato=numero_contrato,
        nombre_representante=nombre,
    )
    response = page.request.post(
        f"{base_url}/cesiones",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )

    assert response.status == 303, (
        f"create POST must return 303, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location == f"/entradas/{entrada_id}", (
        f"create POST must redirect to /entradas/{{entrada_id}}, "
        f"got {location!r}"
    )

    # Follow the redirect and verify the parent entrada detail page renders.
    detail = page.goto(
        f"{base_url}/entradas/{entrada_id}", wait_until="domcontentloaded"
    )
    assert detail is not None
    assert detail.status == 200, (
        f"parent entrada detail must return 200 after cesion create, "
        f"got {detail.status}"
    )
    body = page.content()
    assert entrada_id in body, (
        f"entrada detail page must show the entrada_id {entrada_id!r}"
    )


# --- 4. create with non-existent entrada_id -> 422 -------------------------


def test_create_cesion_with_nonexistent_entrada_returns_422(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /cesiones with a bogus ``entrada_id`` -> 422 + Spanish error.

    The service validates the FK before INSERT; without a matching
    entrada row, the route re-renders the form with 422 and the
    Spanish error message exposed to the operator. Mirrors the
    422 path the entrada battery exercises for its FK check.
    """
    page, csrf_token = authenticated_session
    bogus_entrada_id = str(uuid.uuid4())  # well-formed UUID, never inserted
    form_data = cesion_form_data(
        entrada_id=bogus_entrada_id,
        numero_contrato=f"CP{uuid.uuid4().hex[:4].upper()}",
        nombre_representante="Test Rep",
    )

    response = page.request.post(
        f"{base_url}/cesiones",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )

    assert response.status == 422, (
        f"POST /cesiones with bogus entrada_id must return 422, "
        f"got {response.status}: {response.text()[:300]!r}"
    )
    body = response.text()
    assert CESION_SAVE_FAILED_SPANISH in body, (
        f"422 response must carry the Spanish form error header; "
        f"body excerpt: {body[:500]!r}"
    )
    # The service raises ValueError with a message about entrada_id
    # not referencing; the original test asserts the substring
    # ``"entrada"`` is in the response body.
    assert "entrada" in body.lower(), (
        f"422 response must mention entrada_id validation; "
        f"body excerpt: {body[:500]!r}"
    )


# --- 5. create with blank nombre_representante -> 422 ----------------------


def test_create_cesion_with_blank_nombre_raises_422(
    authenticated_session: tuple[Page, str],
    entrada_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /cesiones with blank ``nombre_representante`` -> 422 + Spanish error.

    ``nombre_representante`` is NOT NULL in the web even though the
    legacy DDL marks it as required=False (P1 fidelity deviation
    documented in docs/architecture/decisiones-proyecto.md). The
    application layer's ``create_cesion`` validates the field before
    delegating to the port — a blank value raises ``ValueError``
    which the route maps to 422.
    """
    page, csrf_token = authenticated_session
    entrada_id = entrada_id_factory()
    form_data = cesion_form_data(
        entrada_id=entrada_id,
        numero_contrato=f"CP{uuid.uuid4().hex[:4].upper()}",
        nombre_representante="   ",  # blank — should be rejected
    )

    response = page.request.post(
        f"{base_url}/cesiones",
        form={"csrf_token": csrf_token, **form_data},
        max_redirects=0,
    )

    assert response.status == 422, (
        f"POST /cesiones with blank nombre_representante must return 422, "
        f"got {response.status}: {response.text()[:300]!r}"
    )
    body = response.text()
    assert CESION_SAVE_FAILED_SPANISH in body, (
        f"422 response must carry the Spanish form error header; "
        f"body excerpt: {body[:500]!r}"
    )
    assert "nombre_representante" in body.lower(), (
        f"422 response must mention nombre_representante; "
        f"body excerpt: {body[:500]!r}"
    )
