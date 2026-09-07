"""Detail-integration tests for FOSTER-04 (#46) materiales on the stay view.

PR C scope: extend ``app/templates/acogidas/detail.html`` with a
"Materiales asignados" section that links to the per-stay junction
view (``/acogidas/{id}/materiales``). The section is a thin slice of
the detail page — the actual list + assign form + delete button live
on the dedicated junction page (the "@router.get(
/acogidas/{id}/materiales)" handler in
``app/modules/materiales/acogida_routes.py`` + the
``app/templates/acogidas/materiales.html`` template). The detail page
section exists because:

1. Operators expect every related-action to be one click away from
   the stay detail (issue #16 / FOSTER-02 acceptance).
2. A link-only section avoids coupling ``acogida_detail`` to the
   materiales service (the detail handler in
   ``app/modules/acogidas/routes.py`` is owned by the FOSTER-02
   slice, not PR C; touching it would violate the chained-PR scope).

Mirrors the existing route-test pattern from
``tests/test_acogidas_routes.py``: routes are pure HTTP / auth /
template glue. The fixture ``_NoSqlRouteClient`` enforces the AGENTS.md
layer-boundary rule (no ``client.execute_sql`` in routes). All data
access goes through ``app.modules.acogidas.service``.

Coverage (1 atom):

1. ``GET /acogidas/{id}`` renders a "Materiales asignados" section
   that links to the per-stay junction view (PR C scope). The
   section is read-only — form mutations live on the dedicated page.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_local_backend_client_dep
from app.core.config import get_settings
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app, get_local_backend_client
from app.modules.acogidas import service as acogidas_service
from tests.conftest import auth_reval_rows

# --- helpers --------------------------------------------------------------


class _NoSqlRouteClient(LocalPostgresExecutor):
    """Client spy that fails if a route executes SQL directly.

    Mirrors the same pattern in ``tests/test_acogidas_routes.py``.
    The single legitimate SELECT is the per-request authorization
    revalidation answered by ``auth_reval_rows``.
    """

    def __init__(self) -> None:
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")
        self.auth_reval_rol: str = "key_user"

    def execute_sql(self, query: str, params: Any = None):
        _reval = auth_reval_rows(query, params, rol=self.auth_reval_rol)
        if _reval is not None:
            return _reval
        raise AssertionError(
            f"routes must not execute SQL directly: {query!r}"
        )


@pytest.fixture
def route_client() -> _NoSqlRouteClient:
    spy = _NoSqlRouteClient()
    app.state.sql_executor = spy
    app.dependency_overrides[get_local_backend_client] = lambda: spy
    app.dependency_overrides[get_local_backend_client_dep] = lambda: spy
    yield spy
    app.dependency_overrides.pop(get_local_backend_client, None)
    app.dependency_overrides.pop(get_local_backend_client_dep, None)


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    """Mint a writer session cookie (CSRF-bound)."""
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-acogidas-detail",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_reader(client: httpx.AsyncClient) -> None:
    """Mint a reader session cookie (CSRF-bound).

    ``reader`` is NOT in :attr:`Settings.writer_rols` (issue #144), so
    writer-gated affordances must NOT be rendered. Caller MUST flip
    ``route_client.auth_reval_rol = "reader"`` BEFORE this helper so
    the per-request revalidation SELECT echoes the cookie's rol.
    """
    token = write_session(
        {
            "email": "rocio@example.com",
            "rol": "reader",
            "user_id": "u-rocio",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-acogidas-detail",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _acogida() -> acogidas_service.Acogida:
    """Canonical Acogida fixture for assertions."""
    return acogidas_service.Acogida(
        id="acog-123",
        animal_id="11111111-1111-1111-1111-111111111111",
        casa_acogida_id="33333333-3333-3333-3333-333333333333",
        voluntario_acogida_id="vol-acog",
        voluntario_seguimiento1_id="vol-seg1",
        voluntario_seguimiento2_id=None,
        voluntario_sanitario_id="vol-san",
        fecha_inicio="2026-07-04",
        fecha_final=None,
        entrada_origen_id=None,
        direccion="Calle Mayor 12, Alcalá de Henares",
        telefono="600123456",
        observaciones="Animal tranquilo, sin medicación",
    )


# --- 1. Detail integration: Materiales asignados section -----------------


async def test_acogidas_detail_renders_assigned_materials_section(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR C: the stay detail page surfaces a 'Materiales asignados' section.

    The section is a navigation slice — a heading + a CTA link to
    ``/acogidas/{id}/materiales`` where the operator actually
    manages the assignments. The detail handler in
    ``app/modules/acogidas/routes.py`` is left untouched (PR C's
    scope per the chained-PR split); the materiales service is NOT
    queried from the detail view. The link is the user-visible
    surface the operator clicks through.

    The existing detail view (``acogidas/detail.html``) renders the
    stay's data via ``acogidas_service.get_acogida_by_id`` + the
    computed ``duracion`` and ``active`` flags — we mock the same
    ``get_acogida_by_id`` here so the test passes the existing
    ``acogida_detail`` handler unchanged.
    """
    _login_as_key_user(client)
    estancia = _acogida()
    monkeypatch.setattr(
        acogidas_service,
        "get_acogida_by_id",
        lambda _c, _id: estancia,
    )

    response = await client.get("/acogidas/acog-123")

    assert response.status_code == 200
    body = response.text
    # PR C section heading: the per-stay junction view link is here.
    assert "Materiales asignados" in body, (
        "detail page MUST carry a 'Materiales asignados' section "
        "linking to /acogidas/{id}/materiales"
    )
    # The CTA navigates to the per-stay junction view (PR C scope).
    assert 'href="/acogidas/acog-123/materiales"' in body
    # The existing detail fields are still rendered (regression check):
    # the section addition MUST NOT clobber the canonical stay data.
    assert "Voluntarios" in body


# --- 2. CRITICAL-3 regression (jd-judge-a, PR #171) ----------------------


async def test_acogidas_detail_hides_materiales_card_from_reader(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reader MUST NOT see the writer-only 'Materiales asignados' card.

    CRITICAL-3 (jd-judge-a, PR #171): the per-stay detail page
    surfaces a 'Materiales asignados' link to the junction view
    (``/acogidas/{id}/materiales``). That link is a writer-only
    affordance — the junction view itself is reachable by any
    authorized user, but the writer-gated surface on the detail page
    must NOT advertise a management action to a reader.

    Mirrors the RBAC pattern used by every other writer-gated section
    in the project (``materiales/list.html``,
    ``materiales/detail.html``, the per-stay materiales list itself):
    the link is wrapped in ``{% if user and user.rol in ("developer",
    "admin", "key_user") %} ... {% endif %}`` so the card disappears
    for readers.

    The flipped ``route_client.auth_reval_rol = "reader"`` mirrors the
    pattern in ``tests/test_materiales_routes.py`` —
    ``require_authorized_user`` re-validates against the authoritative
    store on every request, so the cookie's rol and the per-request
    SELECT must agree.
    """
    route_client.auth_reval_rol = "reader"
    _login_as_reader(client)
    estancia = _acogida()
    monkeypatch.setattr(
        acogidas_service,
        "get_acogida_by_id",
        lambda _c, _id: estancia,
    )

    response = await client.get("/acogidas/acog-123")

    assert response.status_code == 200
    body = response.text
    # Reader MUST NOT see the writer-only card.
    assert "Materiales asignados" not in body, (
        "reader MUST NOT see the writer-only 'Materiales asignados' "
        "card on the stay detail page; wrap the section in the same "
        "{% if user and user.rol in (...) %} guard used by every "
        "other writer-gated affordance in the project."
    )
    # Belt and braces: the CTA href into the per-stay junction view
    # also disappears with the card.
    assert 'href="/acogidas/acog-123/materiales"' not in body
    # Regression check: the canonical stay data is still rendered.
    assert "Voluntarios" in body
