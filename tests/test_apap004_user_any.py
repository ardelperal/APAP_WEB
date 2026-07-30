"""Tests for APAP004: user: Any must not appear in auth route signatures.

Issue #330: ``user: Any`` erases the mypy gate at the auth boundary.
This module tests:
1. Behavioral: the AuthenticatedUser TypedDict + TypeGuard are correctly defined.
2. Behavioral: no ``user: Any`` annotation exists in any app/ route file.
3. Behavioral: is_authenticated_user() correctly narrows dict-shaped payloads.
4. Behavioral: the TypeGuard is added to CRITICAL_HELPERS and fully covered.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Target files: all route files under app/ + app/main.py


def _iter_route_files(repo_root: Path) -> list[Path]:
    """Walk repo_root/app/ and return every route file path."""
    app = repo_root / "app"
    if not app.is_dir():
        return []
    # routes*.py files under app/modules/<M>/  +  app/main.py
    routes: list[Path] = []
    for pattern in ["routes*.py", "batch_routes.py", "assignment_routes.py"]:
        routes.extend(app.rglob(pattern))
    # Also include app/main.py
    main = app / "main.py"
    if main.is_file():
        routes.append(main)
    return sorted(set(routes))


class TestAuthenticatedUserType:
    """Behavioral: AuthenticatedUser is correctly defined and exported."""

    def test_authenticated_user_typeddict_exists(self) -> None:
        """AuthenticatedUser must be defined as a TypedDict in auth_dependencies."""
        from app.core.auth_dependencies import AuthenticatedUser

        # Must have these keys
        assert "user_id" in AuthenticatedUser.__annotations__
        assert "email" in AuthenticatedUser.__annotations__
        assert "rol" in AuthenticatedUser.__annotations__
        assert "is_authorized" in AuthenticatedUser.__annotations__

    def test_is_authenticated_user_function_exists(self) -> None:
        """is_authenticated_user() TypeGuard must be importable from auth_dependencies."""
        from app.core.auth_dependencies import is_authenticated_user

        assert callable(is_authenticated_user)

    def test_is_authenticated_user_narrows_valid_payload(self) -> None:
        """TypeGuard narrows a correctly-shaped dict to AuthenticatedUser."""
        from app.core.auth_dependencies import (
            is_authenticated_user,
        )

        valid_payload: dict = {
            "user_id": "abc-123",
            "email": "test@example.com",
            "rol": "developer",
            "is_authorized": True,
        }
        assert is_authenticated_user(valid_payload) is True

    def test_is_authenticated_user_rejects_non_dict(self) -> None:
        """TypeGuard returns False for non-dict objects."""
        from app.core.auth_dependencies import is_authenticated_user

        assert is_authenticated_user("not a dict") is False
        assert is_authenticated_user(None) is False
        assert is_authenticated_user(42) is False

    def test_is_authenticated_user_rejects_missing_keys(self) -> None:
        """TypeGuard returns False for dicts missing required keys."""
        from app.core.auth_dependencies import is_authenticated_user

        partial: dict = {"user_id": "abc-123", "email": "test@example.com"}
        assert is_authenticated_user(partial) is False


# Regex-based scan is more robust than AST for annotation inspection
# because Python 3.11's AST stores annotations differently for
# ``from __future__ import annotations`` (PEP 563).
_USER_ANY_RE = re.compile(
    r"\buser\s*:\s*Any\b"
)


class TestNoUserAnyInRoutes:
    """Behavioral: zero user: Any annotations must remain in app/ route files."""

    @pytest.mark.parametrize(
        "route_file",
        [
            pytest.param(p, id=str(p.relative_to(Path.cwd())))
            for p in _iter_route_files(Path.cwd())
        ],
    )
    def test_no_user_any_annotation(self, route_file: Path) -> None:
        """Assert that no route file contains ``user: Any`` annotation.

        This is the behavioral gate for APAP004: any ``user: Any`` in a
        FastAPI route handler parameter erases the mypy type boundary.
        The detector in scripts/check_rules.py catches these statically;
        this test provides a behavioural regression guard.
        """
        src = route_file.read_text(encoding="utf-8")
        violations: list[tuple[int, str]] = []

        for lineno, line in enumerate(src.splitlines(), start=1):
            # Skip comment-only lines
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _USER_ANY_RE.search(line):
                violations.append((lineno, line.strip()))

        assert not violations, (
            f"Found 'user: Any' in {route_file.name} at line(s): "
            f"{[ln for ln, _ in violations]}. "
            f"Replace with 'user: AuthenticatedUser' and import it from "
            f"app.core.auth_dependencies."
        )


class TestCriticalHelpersCoverage:
    """APAP004 TypeGuard must have 100% line coverage (Rule 11)."""

    def test_is_authenticated_user_in_critical_helpers(self) -> None:
        """is_authenticated_user must be in CRITICAL_HELPERS."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from pytest_plugin.coverage_gate import CRITICAL_HELPERS

        assert "is_authenticated_user" in CRITICAL_HELPERS, (
            "is_authenticated_user must be added to CRITICAL_HELPERS in "
            "scripts/pytest_plugin/coverage_gate.py so 100% line coverage is enforced."
        )
