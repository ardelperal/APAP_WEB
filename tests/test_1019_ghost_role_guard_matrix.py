"""Ghost-rol guard matrix for the routes promoted in issue #1019.

A session whose ``rol`` is an unknown string must get 403 on every route
issue #1019 promoted out of the session-only guard. The check pins the
route GUARD decision (``require_permission`` fail-closed legacy branch /
``require_writer_user`` / ``require_known_rol``) by injecting the ghost
session at the ``require_authorized_user`` seam — the same seam the real
session revalidation feeds.

Why not a real-DB session (D-44 boundary, issue #1032): the per-request
DB revalidation resolves the user through ``AuthorizedUser.from_row``
(``app/core/domain/auth/user.py``), which silently promotes an unknown
``rol`` string to ``key_user`` BEFORE the route guard runs. That
upstream promotion is issue #1032's documented gap and lives in
``app/core/`` (out of scope here); end-to-end, a ghost DB row is
indistinguishable from ``key_user``. This test pins the part issue
#1019 owns: from the moment a session payload carries an unknown
``rol`` value, every promoted route answers 403.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Request

from app.core.auth_dependencies import require_authorized_user
from app.core.config import get_settings
from app.core.session import read_session, session_cookie_name, write_session
from app.main import app as _app
from tests.conftest import make_csrf_request

_GHOST_ROL = "ghost_role"
_GHOST_PAYLOAD: dict[str, object] = {
    "email": "ghost@test.com",
    "rol": _GHOST_ROL,
    "user_id": "u-ghost",
    "is_authorized": True,
    "csrf_token": "ghost-csrf-token",
}

# Every route issue #1019 promoted out of the session-only guard
# (guardian: tests/test_rbac_route_guardian.py). Row lookups use random
# UUIDs: the 403 must fire in the dependency, BEFORE the handler.
_GHOST_PROBES: list[tuple[str, str]] = [
    ("GET", "/animales/search"),
    ("GET", f"/animales/{uuid.uuid4()}/salud/resumen"),
    ("GET", "/tareas"),
    ("GET", f"/tareas/{uuid.uuid4()}"),
    ("GET", f"/acogidas/{uuid.uuid4()}/materiales"),
    ("GET", "/entradas/batch/new"),
    ("GET", f"/entradas/batch/{uuid.uuid4()}"),
    ("GET", f"/casas-acogida/{uuid.uuid4()}/asignar"),
    ("PATCH", f"/adopciones/{uuid.uuid4()}/seguimiento"),
    ("POST", "/tareas"),
]


@pytest.fixture
async def ghost_session(client):
    """Inject a REAL signed ghost-rol session at the revalidation seam.

    The middleware requires a valid signed cookie, so the fixture mints
    one via ``write_session`` and then replaces ONLY the DB revalidation
    step: ``require_authorized_user`` is overridden with a dep that
    decodes the cookie and returns the payload verbatim, mirroring the
    contract ``session_di`` has after a successful revalidation (it
    would otherwise overwrite ``rol`` with the #1032-promoted value).
    """
    token = write_session(dict(_GHOST_PAYLOAD), secret=get_settings().session_secret)
    client.cookies.set(session_cookie_name(), token)

    def _revalidated_session(request: Request) -> dict[str, object]:
        payload = read_session(
            request.cookies.get(session_cookie_name()) or "",
            secret=get_settings().session_secret,
        )
        assert payload is not None, "signed ghost session cookie did not decode"
        return payload

    _app.dependency_overrides[require_authorized_user] = _revalidated_session
    yield
    _app.dependency_overrides.pop(require_authorized_user, None)
    client.cookies.clear()


@pytest.mark.asyncio
async def test_ghost_rol_gets_403_on_every_promoted_route(client, ghost_session) -> None:
    """RED (issue #1019): unknown rol string is denied on all promoted routes.

    Pre-fix these routes only validated the session, so a ghost-rol
    payload got 200 (reads), 302 (POST /tareas) or 404 (detail routes
    whose row was missing) instead of the fail-closed 403.
    """
    failures: list[str] = []
    for method, path in _GHOST_PROBES:
        response = await make_csrf_request(
            client, method, path, csrf_token="ghost-csrf-token"
        )
        if response.status_code != 403:
            failures.append(
                f"{method} {path} → {response.status_code} (expected 403 fail-closed)"
            )
    assert not failures, "ghost-rol sessions reached guarded routes:\n" + "\n".join(
        failures
    )
