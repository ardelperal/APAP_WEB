"""Tests for the RBAC model (issue #66).

Covers:
- Role enum: admin, voluntario, staff
- Permission enum: all declared values
- PERMISSIONS matrix shape: every role has >= 1 permission; ADMIN has all
- require_permission: returns user when role has permission
- require_permission: 403s when role lacks permission
- Route-level: 403 when called without correct role
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth_dependencies import AuthenticatedUser
from app.core.rbac import (
    _LEGACY_READ_MATRIX,
    _LEGACY_READ_ROLES,
    PERMISSIONS,
    Permission,
    Role,
    require_permission,
)

#: All read-scope permissions currently in the enum (issue #923 guard).
READ_PERMISSIONS: frozenset[Permission] = frozenset(
    p for p in Permission if p.value.startswith("read:")
)

#: All non-read (write + delete) permissions currently in the enum (issue #923 pin).
NON_READ_PERMISSIONS: frozenset[Permission] = frozenset(
    p for p in Permission
    if p.value.startswith("write:") or p.value.startswith("delete:")
)

#: Legacy roles that must have an explicit read decision (issue #923).
LEGACY_ROLES: tuple[str, ...] = ("developer", "key_user", "reader")


def _missing_legacy_read_decisions(
    matrix: dict[str, frozenset[Permission]],
    roles: tuple[str, ...] | frozenset[str],
) -> dict[str, list[str]]:
    """Return ``{role: [missing read permission values]}`` for ``matrix``.

    The legacy read-matrix guard test (issue #923) uses this helper twice:
    once against a fixture-derived fake matrix to prove the guard detects a
    missing pair, and once against the real ``_LEGACY_READ_MATRIX`` to fail
    when a new read permission lands without an explicit legacy decision.
    """
    missing: dict[str, list[str]] = {}
    for role in roles:
        decided = matrix.get(role, frozenset())
        gaps = READ_PERMISSIONS - decided
        if gaps:
            missing[role] = sorted(p.value for p in gaps)
    return missing


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_for_role_permission(role: str, permission: Permission) -> TestClient:
    """Return a TestClient guarding a route with ``permission`` for ``role``."""
    app = FastAPI()

    @app.get("/guarded")
    def guarded(user: AuthenticatedUser = Depends(require_permission(permission))):
        return {"user_id": user["user_id"], "rol": user["rol"]}

    from app.core.auth_dependencies import require_authorized_user

    def _fake_session():
        return {"user_id": f"u-{role}", "email": f"{role}@test.com", "rol": role, "is_authorized": True}

    app.dependency_overrides[require_authorized_user] = _fake_session
    return TestClient(app)


def _mock_local_backend_handler():
    """Returns a handler that always returns an empty list (no real SQL needed for these tests)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(200, [])

    return handler


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("expected", ["admin", "voluntario", "staff"])
def test_role_enum_has_expected_values(expected: str) -> None:
    """Role enum has admin, voluntario, staff members."""
    assert expected in [r.value for r in Role]


def test_role_enum_count() -> None:
    """Role enum has exactly 3 members (admin, voluntario, staff)."""
    assert len(Role) == 3


# ---------------------------------------------------------------------------
# Permission enum
# ---------------------------------------------------------------------------


def test_permission_enum_has_animals_permissions() -> None:
    """Permission enum has read:animales and write:animales and delete:animales."""
    values = [p.value for p in Permission]
    assert "read:animales" in values
    assert "write:animales" in values
    assert "delete:animales" in values


def test_permission_enum_has_voluntarios_permissions() -> None:
    """Permission enum has read:voluntarios and write:voluntarios."""
    values = [p.value for p in Permission]
    assert "read:voluntarios" in values
    assert "write:voluntarios" in values


def test_permission_enum_has_adopciones_permissions() -> None:
    """Permission enum has read:adopciones and write:adopciones."""
    values = [p.value for p in Permission]
    assert "read:adopciones" in values
    assert "write:adopciones" in values


def test_permission_enum_has_acogidas_permissions() -> None:
    """Permission enum has read:acogidas and write:acogidas."""
    values = [p.value for p in Permission]
    assert "read:acogidas" in values
    assert "write:acogidas" in values


def test_permission_enum_has_sanidad_permissions() -> None:
    """Permission enum has read:salud and write:salud."""
    values = [p.value for p in Permission]
    assert "read:salud" in values
    assert "write:salud" in values


def test_permission_enum_has_reportes_permissions() -> None:
    """Permission enum has read:reportes and write:reportes."""
    values = [p.value for p in Permission]
    assert "read:reportes" in values
    assert "write:reportes" in values


def test_permission_enum_has_manage_users_permission() -> None:
    """Permission enum has manage:users."""
    values = [p.value for p in Permission]
    assert "manage:users" in values


# ---------------------------------------------------------------------------
# PERMISSIONS matrix
# ---------------------------------------------------------------------------


def test_permissions_matrix_every_role_has_at_least_one_permission() -> None:
    """Every role in Role has at least one entry in PERMISSIONS."""
    for role in Role:
        perms = PERMISSIONS.get(role, frozenset())
        assert len(perms) > 0, f"Role {role.value} has no permissions"


def test_permissions_matrix_admin_has_all_permissions() -> None:
    """ADMIN has all permissions from the Permission enum."""
    admin_perms = PERMISSIONS[Role.ADMIN]
    all_permissions = frozenset(Permission)
    assert admin_perms == all_permissions, (
        f"ADMIN should have all permissions but is missing: "
        f"{all_permissions - admin_perms}"
    )


def test_permissions_matrix_staff_has_more_than_voluntario() -> None:
    """STAFF has strictly more permissions than VOLUNTARIO."""
    staff_perms = PERMISSIONS[Role.STAFF]
    vol_perms = PERMISSIONS[Role.VOLUNTARIO]
    assert len(staff_perms) > len(vol_perms)


def test_permissions_matrix_staff_has_manage_users() -> None:
    """STAFF does NOT have manage:users (admin-only)."""
    staff_perms = PERMISSIONS[Role.STAFF]
    assert Permission.MANAGE_USERS not in staff_perms


# ---------------------------------------------------------------------------
# require_permission — unit tests via FastAPI TestClient
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/test-read-animales")
    def read_animales(user: AuthenticatedUser = Depends(require_permission(Permission.READ_ANIMALES))):
        return {"user_id": user["user_id"], "rol": user["rol"]}

    @app.get("/test-manage-users")
    def manage_users(user: AuthenticatedUser = Depends(require_permission(Permission.MANAGE_USERS))):
        return {"user_id": user["user_id"], "rol": user["rol"]}

    return app


def _client_with_user(role: str) -> TestClient:
    """Return a TestClient with a session cookie for a user of the given role."""

    app = _build_app()

    # We need to mock the auth dependency. Use dependency_overrides.
    from app.core.auth_dependencies import require_authorized_user

    def _fake_session():
        return {"user_id": f"u-{role}", "email": f"{role}@test.com", "rol": role, "is_authorized": True}

    app.dependency_overrides[require_authorized_user] = _fake_session
    return TestClient(app)


def test_require_permission_read_animales_allows_staff() -> None:
    """Staff can read animales."""
    from starlette.testclient import TestClient as StarletteClient

    app = _build_app()
    from app.core.auth_dependencies import require_authorized_user

    def _fake_session():
        return {"user_id": "u-staff", "email": "staff@test.com", "rol": "staff", "is_authorized": True}

    app.dependency_overrides[require_authorized_user] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-read-animales")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


def test_require_permission_read_animales_allows_voluntario() -> None:
    """Voluntario can read animales."""
    from starlette.testclient import TestClient as StarletteClient

    app = _build_app()
    from app.core.auth_dependencies import require_authorized_user

    def _fake_session():
        return {"user_id": "u-vol", "email": "vol@test.com", "rol": "voluntario", "is_authorized": True}

    app.dependency_overrides[require_authorized_user] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-read-animales")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


def test_require_permission_manage_users_denies_voluntario() -> None:
    """Voluntario cannot manage users (403)."""
    from starlette.testclient import TestClient as StarletteClient

    app = _build_app()
    from app.core.auth_dependencies import require_authorized_user

    def _fake_session():
        return {"user_id": "u-vol", "email": "vol@test.com", "rol": "voluntario", "is_authorized": True}

    app.dependency_overrides[require_authorized_user] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-manage-users")
    assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"


def test_require_permission_manage_users_allows_admin() -> None:
    """Admin can manage users."""
    from starlette.testclient import TestClient as StarletteClient

    app = _build_app()
    from app.core.auth_dependencies import require_authorized_user

    def _fake_session():
        return {"user_id": "u-admin", "email": "admin@test.com", "rol": "admin", "is_authorized": True}

    app.dependency_overrides[require_authorized_user] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-manage-users")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


def test_require_permission_write_animales_allows_voluntario() -> None:
    """Voluntario can write animales (has write:animales per issue #66 matrix)."""
    from starlette.testclient import TestClient as StarletteClient

    app = FastAPI()

    @app.get("/test-write-animales")
    def write_animales(user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_ANIMALES))):
        return {"user_id": user["user_id"]}

    from app.core.auth_dependencies import require_authorized_user

    def _fake_session():
        return {"user_id": "u-vol", "email": "vol@test.com", "rol": "voluntario", "is_authorized": True}

    app.dependency_overrides[require_authorized_user] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-write-animales")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# Legacy read mapping — issue #923 (finding A-11, epic #911)
# ---------------------------------------------------------------------------


def test_require_permission_read_animales_denies_unknown_role() -> None:
    """An unrecognized role string is denied on reads too (fail-closed, #923)."""
    client = _client_for_role_permission("ghost_role", Permission.READ_ANIMALES)
    response = client.get("/guarded")
    assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"


def test_legacy_read_matrix_guard_detects_missing_pair_in_fake_matrix() -> None:
    """The guard reports a missing pair in a synthetic matrix (failure-mode demo).

    Without touching ``app/``: derive a fake matrix that drops one read
    permission and assert the guard names the missing pair for every role.
    """
    fake_matrix: dict[str, frozenset[Permission]] = {
        role: READ_PERMISSIONS - {Permission.READ_SALUD} for role in LEGACY_ROLES
    }
    missing = _missing_legacy_read_decisions(fake_matrix, LEGACY_ROLES)
    assert missing == {
        "developer": ["read:salud"],
        "key_user": ["read:salud"],
        "reader": ["read:salud"],
    }


def test_legacy_read_matrix_covers_every_read_permission() -> None:
    """Every read permission has an explicit decision for every legacy role (#923).

    Guard test: if a new ``read:*`` permission is added to the enum/matrix
    without extending ``_LEGACY_READ_MATRIX`` in ``app/core/rbac.py``, this
    fails naming the missing (role, permission) pairs.
    """
    missing = _missing_legacy_read_decisions(_LEGACY_READ_MATRIX, _LEGACY_READ_ROLES)
    assert not missing, (
        "Legacy read mapping is incomplete; add an explicit decision in "
        f"_LEGACY_READ_MATRIX (app/core/rbac.py) for the missing pairs: {missing}"
    )
    assert set(_LEGACY_READ_MATRIX) == set(_LEGACY_READ_ROLES), (
        "_LEGACY_READ_MATRIX keys must exactly match _LEGACY_READ_ROLES; "
        "a matrix key without a tracked legacy role is a drift"
    )


def test_legacy_read_matrix_contains_only_read_permissions() -> None:
    """The legacy read mapping never grants write, delete or manage scopes."""
    for role, granted in _LEGACY_READ_MATRIX.items():
        extra = granted - READ_PERMISSIONS
        assert not extra, f"Legacy role {role!r} grants non-read permissions: {sorted(p.value for p in extra)}"


@pytest.mark.parametrize("permission", sorted(READ_PERMISSIONS, key=lambda p: p.value))
@pytest.mark.parametrize("role", LEGACY_ROLES)
def test_legacy_role_allowed_on_all_reads(role: str, permission: Permission) -> None:
    """Each legacy role keeps its full current read access (zero user impact)."""
    client = _client_for_role_permission(role, permission)
    response = client.get("/guarded")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


@pytest.mark.parametrize("permission", sorted(NON_READ_PERMISSIONS, key=lambda p: p.value))
def test_reader_denied_on_every_write_permission(permission: Permission) -> None:
    """The reader legacy role stays read-only (403 on every write/delete permission)."""
    client = _client_for_role_permission("reader", permission)
    response = client.get("/guarded")
    assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"


@pytest.mark.parametrize("role", ["developer", "key_user"])
def test_legacy_writer_roles_retain_delete_animales(role: str) -> None:
    """DEVELOPER and KEY_USER keep DELETE_ANIMALES (contributor checklist requirement)."""
    client = _client_for_role_permission(role, Permission.DELETE_ANIMALES)
    response = client.get("/guarded")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


def test_require_permission_write_animales_denies_unknown_role() -> None:
    """A user with an unknown role cannot write animales (default deny)."""
    from starlette.testclient import TestClient as StarletteClient

    app = FastAPI()

    @app.get("/test-write-animales")
    def write_animales(user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_ANIMALES))):
        return {"user_id": user["user_id"]}

    from app.core.auth_dependencies import require_authorized_user

    def _fake_session():
        return {"user_id": "u-unknown", "email": "unk@test.com", "rol": "unknown_role", "is_authorized": True}

    app.dependency_overrides[require_authorized_user] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-write-animales")
    assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
