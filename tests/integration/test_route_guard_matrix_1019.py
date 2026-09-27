"""Route guard decision matrix for user-facing routes (issue #1019, D-44).

``require_authorized_user`` validates the session but never checks the
``rol`` VALUE: any authenticated session (unknown rol string, ``reader``)
reaches the handler. Issue #1019 promotes every user-facing route that
was guarded only by ``require_authorized_user`` to an explicit guard
decision: ``require_permission(Permission.<X>)`` from the RBAC matrix
(D-44 legacy mapping keeps developer/key_user/reader working on reads)
or, where the matrix has no domain permission (``/tareas`` reads), a
fail-closed rol-value check; ``/tareas`` writes land on
``require_writer_user`` (``_LEGACY_WRITER_ROLES``).

Real app, real Postgres, ``APAP_AUTH_CACHE_TTL_SECONDS=0`` — same harness
as ``tests.integration.test_magic_link_real_app`` (fixture re-export, no
duplication for the JSCPD ratchet).

RED contract (pre-fix): ghost_role sessions got 200/302 on every route
below instead of 403; ``reader`` could execute the seguimiento PATCH.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.test_magic_link_real_app import (
    _magic_link_login,
    _seed_user,
    _session_cookie,
    real_app_harness,
)

# Fixture re-export (pytest resolves parameters by module-namespace
# name; ruff's F811 would flag the parameter shadowing an "unused"
# import, so the binding is declared as intentional re-export here).
__all__ = ["real_app_harness"]

pytestmark = pytest.mark.integration

# NOTE (issue #1032 boundary): a ghost DB rol cannot be observed
# end-to-end here — the per-request revalidation resolves the user via
# ``AuthorizedUser.from_row``, which silently promotes an unknown rol
# string to ``key_user`` before the route guard runs. The ghost-rol
# guard matrix is therefore pinned at the ``require_authorized_user``
# seam in ``tests/test_1019_ghost_role_guard_matrix.py`` (unit level).

# Route inventory of issue #1019: (method, path) → expected status for a
# reader session on the write routes after the fix. ``{id}`` placeholders
# are filled with random UUIDs: the 403 must fire in the dependency,
# BEFORE the handler looks up the (nonexistent) row.

_SEGUIMIENTO_ID = str(uuid.uuid4())
_POST_TAREAS_BODY = {"tipo": "manual"}


async def _login_as(real_app_harness, rol: str) -> dict[str, object]:
    """Seed an active user with ``rol`` and mint a real session for it."""
    harness = real_app_harness
    email = f"guard-{rol}-{uuid.uuid4().hex[:8]}@test.com"
    _seed_user(harness.executor, email, rol)
    verify = await _magic_link_login(harness, email)
    assert verify.status_code == 302, verify.text
    return _session_cookie(harness)


@pytest.mark.asyncio
async def test_reader_forbidden_on_seguimiento_patch(real_app_harness) -> None:
    """RED (issue #1019): ``reader`` is read-only — PATCH seguimiento → 403.

    Pre-fix: the PATCH handler ran for ``reader`` (404 for the missing
    row, 409/303 for a real one) because only the session was validated.
    """
    await _login_as(real_app_harness, "reader")
    harness = real_app_harness
    csrf_token = _session_cookie(harness).get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token
    response = await harness.client.patch(
        f"/adopciones/{_SEGUIMIENTO_ID}/seguimiento",
        data={"action": "marcar_entregado"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert response.status_code == 403, (
        f"reader must be rejected on PATCH /adopciones/{{id}}/seguimiento; "
        f"got {response.status_code}: {response.text[:200]!r}"
    )


@pytest.mark.asyncio
async def test_reader_forbidden_on_tareas_writes(real_app_harness) -> None:
    """RED (issue #1019): ``/tareas`` writes land on ``require_writer_user``.

    ``reader`` is intentionally excluded from ``writer_rols``; pre-fix the
    POST routes ran for any authenticated session.
    """
    await _login_as(real_app_harness, "reader")
    harness = real_app_harness
    csrf_token = _session_cookie(harness).get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token
    response = await harness.client.post(
        "/tareas",
        data={**_POST_TAREAS_BODY, "csrf_token": csrf_token},
        headers={"X-CSRFToken": csrf_token},
    )
    assert response.status_code == 403, (
        f"reader must be rejected on POST /tareas; got {response.status_code}: "
        f"{response.text[:200]!r}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["developer", "key_user", "reader"])
async def test_legacy_roles_keep_read_access(rol: str, real_app_harness) -> None:
    """D-44 no-impact pin: developer/key_user/reader keep 200 on reads.

    Detail routes whose row does not exist return 404 (auth passed, the
    handler answered) — accepted as positive evidence; 403 would mean the
    legacy mapping regressed.
    """
    await _login_as(real_app_harness, rol)
    harness = real_app_harness
    expected_200 = [
        ("GET", "/animales/search"),
        ("GET", "/tareas"),
        ("GET", "/entradas/batch/new"),
        ("GET", f"/animales/{uuid.uuid4()}/salud/resumen"),
    ]
    expected_not_403 = [
        ("GET", f"/tareas/{uuid.uuid4()}"),
        ("GET", f"/entradas/batch/{uuid.uuid4()}"),
        ("GET", f"/casas-acogida/{uuid.uuid4()}/asignar"),
        ("GET", f"/acogidas/{uuid.uuid4()}/materiales"),
    ]
    failures: list[str] = []
    for method, path in expected_200:
        response = await harness.client.request(method, path)
        if response.status_code != 200:
            failures.append(f"{method} {path} → {response.status_code} (expected 200)")
    for method, path in expected_not_403:
        response = await harness.client.request(method, path)
        if response.status_code == 403:
            failures.append(
                f"{method} {path} → 403 for legacy rol '{rol}' (D-44 regression)"
            )
    assert not failures, f"legacy rol '{rol}' lost read access:\n" + "\n".join(failures)


@pytest.mark.asyncio
async def test_writer_still_reaches_seguimiento_patch(real_app_harness) -> None:
    """Positive control: ``key_user`` passes the write guard (404, not 403).

    The seguimiento PATCH must deny ``reader``/ghost roles but keep the
    legacy writer roles working (D-44 write contract unchanged).
    """
    await _login_as(real_app_harness, "key_user")
    harness = real_app_harness
    csrf_token = _session_cookie(harness).get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token
    response = await harness.client.patch(
        f"/adopciones/{_SEGUIMIENTO_ID}/seguimiento",
        data={"action": "marcar_entregado"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert response.status_code == 404, (
        f"key_user must pass the write guard on PATCH seguimiento (404 for the "
        f"missing row); got {response.status_code}: {response.text[:200]!r}"
    )
