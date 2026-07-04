"""Regression tests for the ``is_authorized`` default-flip (PR-3 of hardening-2026-q2).

Closes the P0 window from engram:14516 / engram:14518 (a deactivated user
kept a valid session for up to 7 days because the default was True). The
dependency-side regression lives in tests/test_auth_dependencies.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client


def _read(rel: str) -> str:
    return (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")


def test_middleware_default_false_en_fuente() -> None:
    """app/main.py carries payload.get("is_authorized", False)."""
    src = _read("app/main.py")
    assert 'payload.get("is_authorized", False)' in src
    assert 'payload.get("is_authorized", True)' not in src


def test_solo_dos_call_sites_en_app() -> None:
    """Exactly two `if` call sites of payload.get("is_authorized"...) in app/.

    The regex matches the call-site shape so docstring mentions don't
    produce false positives. The PR-1A linter (Detector 2) pins the same
    property; this is the pre-merge fallback.
    """
    repo_root = Path(__file__).resolve().parents[1]
    pat = re.compile(r'if not payload\.get\("is_authorized"')
    matches = [
        (py.relative_to(repo_root).as_posix(), n, line.strip())
        for py in (repo_root / "app").rglob("*.py")
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), start=1)
        if pat.search(line)
    ]
    assert len(matches) == 2, f"expected 2 call sites, got {len(matches)}: {matches}"
    assert {m[0] for m in matches} == {"app/main.py", "app/core/auth_dependencies.py"}


class _Spy(InsForgeClient):
    """InsForge stand-in: [] from execute_sql, no HTTP I/O."""

    def __init__(self) -> None:  # type: ignore[override]
        self._client = None

    def execute_sql(self, query, params=None):  # type: ignore[override]
        from tests.conftest import auth_reval_rows

        _reval = auth_reval_rows(query if isinstance(query, str) else "", params)
        if _reval is not None:
            return _reval
        return []

    def close(self) -> None:  # type: ignore[override]
        return None


@pytest.fixture
def spy_insforge() -> _Spy:
    s = _Spy()
    app.dependency_overrides[get_insforge_client] = lambda: s
    yield s
    app.dependency_overrides.pop(get_insforge_client, None)


def _login_pre_fix(client: httpx.AsyncClient) -> None:
    """Sign a cookie without the is_authorized key (pre-fix shape)."""
    from app.core.config import get_settings

    client.cookies.set(
        session_cookie_name(),
        write_session(
            {"email": "g@e.com", "rol": "key_user", "user_id": "u-g"},
            secret=get_settings().session_secret,
        ),
    )


async def test_middleware_default_false(
    client: httpx.AsyncClient, spy_insforge: _Spy
) -> None:
    """Pre-fix cookie → 302 /unauthorized on a protected route.

    The middleware's default-deny contract is exercised against a
    protected app route (``/animales``); the marketing landing at
    ``/`` is intentionally public so this test cannot use it.
    """
    _login_pre_fix(client)
    r = await client.get("/animales", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/unauthorized"


async def test_middleware_pasa_con_is_authorized_true(
    client: httpx.AsyncClient, spy_insforge: _Spy
) -> None:
    """Triangulation: with is_authorized=True the middleware lets through on a protected route."""
    from app.core.config import get_settings

    client.cookies.set(
        session_cookie_name(),
        write_session(
            {
                "email": "l@e.com",
                "rol": "key_user",
                "user_id": "u-l",
                "is_authorized": True,
            },
            secret=get_settings().session_secret,
        ),
    )
    r = await client.get("/animales", follow_redirects=False)
    assert r.headers.get("location") not in ("/unauthorized", "/login")
