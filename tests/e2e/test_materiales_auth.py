"""E2E coverage for the auth gate on the ``/materiales`` slice.

Pins the AGENTS.md §10 (CSRF) and §29 (auth) invariants from the
HTTP surface: the ``/materiales`` catalog and
``/acogidas/{id}/materiales`` assignment routes are auth-gated
and redirect anonymous users to ``/login``.

Hard rules (web-tdd-philosophy):

- Rule 1 (fixture gate): the shared ``page`` / ``base_url``
  fixtures from ``tests/e2e/conftest.py`` are the entry point.
- Rule 4 (no humo): assertions on the HTTP status code and
  ``Location`` header, not absence-of-error.
- Rule 8 (no production mutation): the test is read-only.

Follows the same pattern as
``tests/e2e/test_terapias_auth.py`` (the terapias slice gate
test). A ``reader`` 403 atom is left as a follow-up the day the
``/e2e/login`` OAuth mock grows a ``?rol=reader`` query param.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


def test_materiales_list_redirects_to_login_when_unauthenticated(
    page, base_url: str
) -> None:
    """Anonymous ``GET /materiales`` returns the login redirect."""
    response = page.request.get(f"{base_url}/materiales", max_redirects=0)
    assert response.status in (302, 303), response.headers
    assert "/login" in response.headers.get("location", "")


def test_materiales_detail_redirects_to_login_when_unauthenticated(
    page, base_url: str
) -> None:
    """Anonymous ``GET /materiales/{id}`` also redirects — the gate is
    uniform across the catalog and the assignment routes."""
    response = page.request.get(
        f"{base_url}/materiales/00000000-0000-0000-0000-000000000000",
        max_redirects=0,
    )
    assert response.status in (302, 303), response.headers
    assert "/login" in response.headers.get("location", "")


def test_assignment_list_redirects_to_login_when_unauthenticated(
    page, base_url: str
) -> None:
    """Anonymous ``GET /acogidas/{id}/materiales`` also redirects —
    the per-stancia junction routes live under the same auth gate."""
    response = page.request.get(
        f"{base_url}/acogidas/00000000-0000-0000-0000-000000000000/materiales",
        max_redirects=0,
    )
    assert response.status in (302, 303), response.headers
    assert "/login" in response.headers.get("location", "")
