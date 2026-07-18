"""Strict TDD atoms for the PR5 ``PUBLIC_PATHS`` auth invariant.

The PR5 spec (``live-migration-pii-controls/spec.md``) pins the
authorization invariant for every PII-displaying route, plus the
shape of ``PUBLIC_PATHS`` itself.

Spec scenarios pinned:

- ``PUBLIC_PATHS`` matches verified app behavior — exactly five
  entries (``/healthz``, ``/login``, ``/auth/google``,
  ``/auth/callback``, ``/logout``).
- Every PII-displaying route returns 302 to ``/login`` without a
  session.
- No PII route is in ``PUBLIC_PATHS`` (defense-in-depth — a
  refactor that accidentally relaxes the auth gate would surface
  here).

The atoms exercise the module-level ``app`` via the
``httpx.AsyncClient`` fixture (the canonical pattern across
``tests/test_*.py``). All assertions are concrete value checks
on the response (status_code + Location header), not absence-of-error.

The catalog of PII routes is per ``live-migration-pii-controls/spec.md``
(``Requirement: Authorization Required for All PII Routes``). A new
PII route that lands in a future PR MUST add an entry to
``PII_ROUTES`` below so the parametrised atom covers it; the atom
fails the build otherwise.
"""

from __future__ import annotations

import httpx
import pytest

from app.main import PUBLIC_PATHS, _is_public_path

# Verified canonical set per spec (``live-migration-pii-controls/spec.md``
# + ``app/main.py:148``). CodeGraph + Read on 2026-07-11 confirmed
# the on-disk surface.
EXPECTED_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/login",
        "/auth/google",
        "/auth/callback",
        "/logout",
    }
)

# PII routes the spec requires to be 302 to /login without a session.
# The mapping carries the parametrized id name so a failure message
# identifies the offending route. Order matters only for the
# parametrize id; the assertions are set-equality safe.
PII_ROUTES_PARAMETRIZE: tuple[str, ...] = (
    "/voluntarios",
    "/voluntarios/abc-123",
    "/animales",
    "/animales/abc-123/foto",
    "/entradas",
)


# --- shape invariants ----------------------------------------------------


def test_public_paths_has_exactly_five_entries() -> None:
    """``PUBLIC_PATHS`` matches the verified canonical set.

    Spec scenario: ``PUBLIC_PATHS matches verified app behavior``.
    The atom asserts the on-disk ``PUBLIC_PATHS`` frozenset equals
    exactly the five entries the spec pins. A refactor that adds
    or removes an entry fails the atom immediately.
    """
    assert PUBLIC_PATHS == EXPECTED_PUBLIC_PATHS, (
        f"PUBLIC_PATHS drifted from the verified set; "
        f"got {sorted(PUBLIC_PATHS)!r}, expected {sorted(EXPECTED_PUBLIC_PATHS)!r}. "
        f"Update this atom AND the spec doc together — they MUST agree."
    )
    assert len(PUBLIC_PATHS) == 5, (
        f"PUBLIC_PATHS must have exactly 5 entries (verified on 2026-07-11); "
        f"got {len(PUBLIC_PATHS)}"
    )


def test_is_public_path_recognises_every_canonical_entry() -> None:
    """``_is_public_path`` returns True for every canonical entry.

    Defence-in-depth: the middleware consults ``_is_public_path``
    on every request. The atom asserts the helper recognises every
    entry in the verified set — a typo on the canonical set would
    otherwise leak through (e.g. ``/healthz`` vs ``/healtz``).
    """
    for path in EXPECTED_PUBLIC_PATHS:
        assert _is_public_path(path) is True, (
            f"_is_public_path({path!r}) returned False; "
            f"the canonical PUBLIC_PATHS entry was not recognised"
        )


def test_public_paths_no_pii_route() -> None:
    """No PII-displaying route is in ``PUBLIC_PATHS``.

    Spec scenario: ``no PII route is in the public set``. The atom
    is the defense-in-depth companion to
    ``test_pii_routes_require_auth`` — even if a refactor
    accidentally adds a PII route to ``PUBLIC_PATHS``, this atom
    catches it.
    """
    for path in PII_ROUTES_PARAMETRIZE:
        assert path not in PUBLIC_PATHS, (
            f"PII route {path!r} is in PUBLIC_PATHS; "
            f"PUBLIC_PATHS leaked the auth gate. "
            f"Current PUBLIC_PATHS: {sorted(PUBLIC_PATHS)!r}"
        )


# --- PII routes require auth (302 to /login) ---------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PII_ROUTES_PARAMETRIZE)
async def test_pii_routes_require_auth(
    path: str,
    client: httpx.AsyncClient,
) -> None:
    """An unauthenticated GET to a PII-displaying route returns
    302 to ``/login``.

    Spec scenario: ``Unauthenticated volunteer list redirects`` and
    the table of PII routes that ``require_authorized_user``
    protects. The atom covers the spec's full PII-route surface
    (5 entries); a future PII route that lands in a future PR
    MUST add an entry to ``PII_ROUTES_PARAMETRIZE``.
    """
    response = await client.get(path, follow_redirects=False)
    assert response.status_code == 302, (
        f"GET {path!r} without session returned {response.status_code}; "
        f"expected 302 to /login"
    )
    assert response.headers.get("location") == "/login", (
        f"GET {path!r} without session redirected to "
        f"{response.headers.get('location')!r}; expected '/login'"
    )


# --- happy-path invariants (sanity) -------------------------------------


@pytest.mark.asyncio
async def test_healthz_does_not_redirect(client: httpx.AsyncClient) -> None:
    """``/healthz`` is in ``PUBLIC_PATHS``; anonymous requests
    return 200 (or whatever the liveness handler emits) without
    a redirect.

    Sanity invariant: the liveness probe is reachable without a
    session. The exact status code is the probe's contract; the
    atom only asserts the route does NOT redirect to ``/login``.
    """
    response = await client.get("/healthz", follow_redirects=False)
    assert response.status_code != 302, (
        f"/healthz redirected ({response.status_code} → "
        f"{response.headers.get('location')!r}); the liveness "
        f"probe must remain reachable without a session"
    )
    assert response.headers.get("location") != "/login", (
        "/healthz leaked the auth gate; the liveness probe must "
        "remain reachable without a session"
    )


@pytest.mark.asyncio
async def test_login_does_not_redirect(client: httpx.AsyncClient) -> None:
    """``/login`` is in ``PUBLIC_PATHS``; anonymous requests
    render the login page without a redirect.

    Sanity invariant: the login UI is the canonical public
    application-content path. The probe emits 200 (or 503 when
    Google OAuth is not configured); the atom only asserts the
    route does NOT redirect to ``/login`` (no infinite loop).
    """
    response = await client.get("/login", follow_redirects=False)
    # 200 (happy) or 503 (Google OAuth not configured) are both
    # acceptable; 302 → /login would be a contract bug.
    assert response.status_code in (200, 503), (
        f"/login returned {response.status_code}; "
        f"expected 200 (happy) or 503 (Google OAuth not configured). "
        f"A 302 to /login would be a redirect loop."
    )
    assert response.headers.get("location") != "/login", (
        "/login redirected to itself; would produce a redirect loop"
    )
