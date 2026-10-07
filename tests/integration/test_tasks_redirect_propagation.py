"""Integration tests: auth-denial redirect propagation on /tareas (issue #1002).

JD-B-001 (judgment-day of #917): ``require_authorized_user`` returns a
``RedirectResponse`` to ``/unauthorized`` when the user was deactivated,
but the handlers in ``app/modules/tasks/routes.py`` ignored it. Verified
probe (real app, real Postgres, ``APAP_AUTH_CACHE_TTL_SECONDS=0``): a
minted session for a user set ``activo=false`` got **200 with the page
rendered** on ``GET /tareas`` — and, worse, the POST routes silently
executed the write before redirecting. The ``auth.denied`` audit event
fired; the authorization guarantee did not hold.

These tests mint a REAL session (magic-link) for an ACTIVE user, then
deactivate the user and hit all five ``/tareas`` routes. With the auth
cache disabled the per-request DB revalidation denies immediately; the
handler must propagate the 302 ``/unauthorized`` redirect instead of
touching business logic. A positive control pins that a fresh active
user still gets the normal 200 — the fix must not break the happy path.

Runs against ``app.main.create_app()`` with the real lifespan, real
Postgres and the full middleware chain, reusing the harness from
``tests.integration.test_magic_link_real_app`` (same fixture pattern;
no duplication for the JSCPD ratchet).
"""

from __future__ import annotations

import uuid

import httpx
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

_EMAIL = f"tasks-redirect-{uuid.uuid4().hex[:8]}@test.com"


async def _login_seed_and_deactivate(real_app_harness) -> str:
    """Mint a session for an active user, create one tarea, deactivate the user.

    Returns the id of the tarea created while the user was still active
    (so detail/asignar/cerrar target a real row).
    """
    harness = real_app_harness
    _seed_user(harness.executor, _EMAIL, "key_user")
    verify = await _magic_link_login(harness, _EMAIL)
    assert verify.status_code == 302

    csrf_token = _session_cookie(harness).get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token
    create = await harness.client.post(
        "/tareas", data={"tipo": "manual", "csrf_token": csrf_token}
    )
    assert create.status_code == 302, create.text
    assert create.headers["location"] == "/tareas"
    rows = harness.executor.execute_sql("SELECT id FROM tarea")
    assert len(rows) == 1
    tarea_id = str(rows[0]["id"])

    # Deactivate AFTER the session was minted. TTL=0 in the harness, so
    # the per-request revalidation observes it immediately.
    harness.executor.execute_sql(
        "UPDATE usuarios_autorizados SET activo = false WHERE email = $1",
        [_EMAIL],
    )
    return tarea_id


@pytest.mark.asyncio
async def test_deactivated_user_get_tareas_redirects_not_renders(
    real_app_harness,
) -> None:
    """RED (issue #1002): deactivated user gets 302, not a rendered page.

    Pre-fix: ``GET /tareas`` returned 200 with the list rendered because
    ``listar_tareas`` passed ``current_user`` straight to the template.
    """
    await _login_seed_and_deactivate(real_app_harness)
    response = await real_app_harness.client.get("/tareas")
    assert response.status_code == 302, (
        f"expected 302 redirect for deactivated user, got "
        f"{response.status_code}: {response.text[:200]!r}"
    )
    assert response.headers["location"] == "/unauthorized"


@pytest.mark.asyncio
async def test_deactivated_user_get_tarea_detail_redirects(
    real_app_harness,
) -> None:
    """RED (issue #1002): ``GET /tareas/{id}`` redirects instead of rendering."""
    tarea_id = await _login_seed_and_deactivate(real_app_harness)
    response = await real_app_harness.client.get(f"/tareas/{tarea_id}")
    assert response.status_code == 302, (
        f"expected 302 redirect for deactivated user, got "
        f"{response.status_code}: {response.text[:200]!r}"
    )
    assert response.headers["location"] == "/unauthorized"


@pytest.mark.asyncio
async def test_deactivated_user_post_tareas_redirects_and_does_not_write(
    real_app_harness,
) -> None:
    """RED (issue #1002): deactivated user's POST is redirected, not executed.

    Pre-fix: ``POST /tareas`` created the tarea and then redirected to
    ``/tareas`` — a state mutation by a deactivated user.
    """
    await _login_seed_and_deactivate(real_app_harness)
    harness = real_app_harness

    csrf_token = _session_cookie(harness).get("csrf_token")
    response = await harness.client.post(
        "/tareas", data={"tipo": "manual", "csrf_token": csrf_token or ""}
    )
    assert response.status_code == 302, (
        f"expected 302 redirect for deactivated user, got "
        f"{response.status_code}: {response.text[:200]!r}"
    )
    assert response.headers["location"] == "/unauthorized"
    # The write must NOT land: still exactly the one seed tarea.
    rows = harness.executor.execute_sql("SELECT id FROM tarea")
    assert len(rows) == 1, "deactivated user's POST /tareas must not create rows"


@pytest.mark.asyncio
async def test_deactivated_user_post_asignar_redirects_and_does_not_write(
    real_app_harness,
) -> None:
    """RED (issue #1002): ``POST /tareas/{id}/asignar`` redirects, not mutates."""
    tarea_id = await _login_seed_and_deactivate(real_app_harness)
    harness = real_app_harness

    csrf_token = _session_cookie(harness).get("csrf_token")
    response = await harness.client.post(
        f"/tareas/{tarea_id}/asignar",
        data={"responsable_id": "", "csrf_token": csrf_token or ""},
    )
    assert response.status_code == 302, (
        f"expected 302 redirect for deactivated user, got "
        f"{response.status_code}: {response.text[:200]!r}"
    )
    assert response.headers["location"] == "/unauthorized"


@pytest.mark.asyncio
async def test_deactivated_user_post_cerrar_redirects_and_does_not_write(
    real_app_harness,
) -> None:
    """RED (issue #1002): ``POST /tareas/{id}/cerrar`` redirects, not mutates."""
    tarea_id = await _login_seed_and_deactivate(real_app_harness)
    harness = real_app_harness

    csrf_token = _session_cookie(harness).get("csrf_token")
    response = await harness.client.post(
        f"/tareas/{tarea_id}/cerrar",
        data={"comentario": "x", "csrf_token": csrf_token or ""},
    )
    assert response.status_code == 302, (
        f"expected 302 redirect for deactivated user, got "
        f"{response.status_code}: {response.text[:200]!r}"
    )
    assert response.headers["location"] == "/unauthorized"


@pytest.mark.asyncio
async def test_active_user_still_gets_tareas_page(real_app_harness) -> None:
    """Positive control: a fresh ACTIVE user still gets 200 on ``GET /tareas``."""
    harness = real_app_harness
    _seed_user(harness.executor, _EMAIL, "key_user")
    verify = await _magic_link_login(harness, _EMAIL)
    assert verify.status_code == 302

    response: httpx.Response = await harness.client.get("/tareas")
    assert response.status_code == 200, (
        f"active user must still get the tareas page, got "
        f"{response.status_code}: {response.text[:200]!r}"
    )
