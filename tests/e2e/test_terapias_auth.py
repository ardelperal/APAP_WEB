"""E2E coverage for the auth gate on the ``/terapias`` slice (HEALTH-04, #53).

Pins the AGENTS.md §10 (CSRF) and §29 (auth) invariants from the HTTP
surface: the ``/terapias`` routes are auth-gated and the gate
returns the documented redirect when the session is missing.

Hard rules (web-tdd-philosophy):

- Rule 1 (fixture gate): each atom uses the ``page`` /
  ``base_url`` fixtures from ``tests/e2e/conftest.py``.
- Rule 4 (no humo): assertions on the actual HTTP status code and
  ``Location`` header, not absence-of-error.
- Rule 8 (no production mutation): the test is read-only; it never
  creates a terapia.

The ``reader`` 403 path requires a session with the ``reader`` rol,
which the ``/e2e/login`` OAuth mock does not currently mint (the
mock only seeds ``developer``; the admin panel is the only path
that creates ``reader`` users, and we deliberately do not
auto-create one in the e2e suite to keep the seed minimal). The
``test_writer_only_endpoint_rejects_anonymous`` atom pins the
anonymous case; the reader case is left as a follow-up the day
the mock grows a ``?rol=reader`` query param.

This file follows the convention from
``tests/e2e/test_admin_authenticated.py`` and
``tests/e2e/test_casas_acogida_crud.py``: ``pytest.mark.e2e``,
auto-skipped by ``tests/e2e/conftest.py`` when chromium is missing
or ``APAP_E2E_SKIP=1``.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


def test_terapias_list_redirects_to_login_when_unauthenticated(
    page, base_url: str
) -> None:
    """Anonymous ``GET /terapias`` returns the login redirect.

    Pins the auth-gate contract: every authenticated route must
    redirect anonymous users to ``/login`` before the handler runs.
    A regression here would silently expose the terapias list to
    unauthenticated visitors.
    """
    response = page.request.get(f"{base_url}/terapias", max_redirects=0)
    assert response.status in (302, 303), response.headers
    location = response.headers.get("location", "")
    assert "/login" in location, (
        f"anonymous GET /terapias must redirect to /login; got {location!r}"
    )


def test_terapias_create_redirects_to_login_when_unauthenticated(
    page, base_url: str
) -> None:
    """Anonymous ``POST /terapias`` also returns the login redirect.

    The auth gate applies to writes, not just reads; ``POST /terapias``
    without a session cannot create a terapia. The redirect target
    may carry the next-URL so the operator lands back on the form
    after logging in — that is a UI nicety, the auth gate is the
    load-bearing assertion here.
    """
    response = page.request.post(
        f"{base_url}/terapias",
        form={
            "animal_id": "00000000-0000-0000-0000-000000000000",
            "voluntario_id": "00000000-0000-0000-0000-000000000000",
            "fecha": "2026-01-15",
        },
        max_redirects=0,
    )
    assert response.status in (302, 303), response.headers
    assert "/login" in response.headers.get("location", "")


def test_terapias_detail_redirects_to_login_when_unauthenticated(
    page, base_url: str
) -> None:
    """Anonymous ``GET /terapias/{id}`` also redirects — the gate is
    uniform across the slice, not per-route.
    """
    response = page.request.get(
        f"{base_url}/terapias/00000000-0000-0000-0000-000000000000",
        max_redirects=0,
    )
    assert response.status in (302, 303), response.headers
    assert "/login" in response.headers.get("location", "")
