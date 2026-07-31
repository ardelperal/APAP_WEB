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
    PERMISSIONS,
    Permission,
    Role,
    require_permission,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _mock_insforge_handler():
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
    from app.core.auth_dependencies import get_current_user_optional

    def _fake_session():
        return {"user_id": f"u-{role}", "email": f"{role}@test.com", "rol": role, "is_authorized": True}

    app.dependency_overrides[get_current_user_optional] = _fake_session
    return TestClient(app)


def test_require_permission_read_animales_allows_staff() -> None:
    """Staff can read animales."""
    from starlette.testclient import TestClient as StarletteClient

    app = _build_app()
    from app.core.auth_dependencies import get_current_user_optional

    def _fake_session():
        return {"user_id": "u-staff", "email": "staff@test.com", "rol": "staff", "is_authorized": True}

    app.dependency_overrides[get_current_user_optional] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-read-animales")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


def test_require_permission_read_animales_allows_voluntario() -> None:
    """Voluntario can read animales."""
    from starlette.testclient import TestClient as StarletteClient

    app = _build_app()
    from app.core.auth_dependencies import get_current_user_optional

    def _fake_session():
        return {"user_id": "u-vol", "email": "vol@test.com", "rol": "voluntario", "is_authorized": True}

    app.dependency_overrides[get_current_user_optional] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-read-animales")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


def test_require_permission_manage_users_denies_voluntario() -> None:
    """Voluntario cannot manage users (403)."""
    from starlette.testclient import TestClient as StarletteClient

    app = _build_app()
    from app.core.auth_dependencies import get_current_user_optional

    def _fake_session():
        return {"user_id": "u-vol", "email": "vol@test.com", "rol": "voluntario", "is_authorized": True}

    app.dependency_overrides[get_current_user_optional] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-manage-users")
    assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"


def test_require_permission_manage_users_allows_admin() -> None:
    """Admin can manage users."""
    from starlette.testclient import TestClient as StarletteClient

    app = _build_app()
    from app.core.auth_dependencies import get_current_user_optional

    def _fake_session():
        return {"user_id": "u-admin", "email": "admin@test.com", "rol": "admin", "is_authorized": True}

    app.dependency_overrides[get_current_user_optional] = _fake_session
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

    from app.core.auth_dependencies import get_current_user_optional

    def _fake_session():
        return {"user_id": "u-vol", "email": "vol@test.com", "rol": "voluntario", "is_authorized": True}

    app.dependency_overrides[get_current_user_optional] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-write-animales")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


def test_require_permission_write_animales_denies_unknown_role() -> None:
    """A user with an unknown role cannot write animales (default deny)."""
    from starlette.testclient import TestClient as StarletteClient

    app = FastAPI()

    @app.get("/test-write-animales")
    def write_animales(user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_ANIMALES))):
        return {"user_id": user["user_id"]}

    from app.core.auth_dependencies import get_current_user_optional

    def _fake_session():
        return {"user_id": "u-unknown", "email": "unk@test.com", "rol": "unknown_role", "is_authorized": True}

    app.dependency_overrides[get_current_user_optional] = _fake_session
    client = StarletteClient(app)

    response = client.get("/test-write-animales")
    assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
