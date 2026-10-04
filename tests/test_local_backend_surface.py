"""Structural pins for the local backend's SQL surface (issue #1078).

The M0 module ``app/core/local_backend/api.py`` exposed
``POST /database/advance/rawsql`` — arbitrary SQL with NO authentication
— as a self-contained FastAPI app. Nothing imported or started it, but
anyone running ``uvicorn app.core.local_backend.api:app`` (as its own
comment suggested) would have exposed unauthenticated SQL. The real
rawsql surface is ``app/core/local_backend/rawsql.py`` (token-protected
since #680, mounted by ``app/core/local_backend/app.py``).

These pins keep the surface single: the M0 module stays deleted, and no
other module under ``app/`` may declare a rawsql route outside the
guarded router.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "app"
GUARDED_ROUTER = Path("app/core/local_backend/rawsql.py")
#: The deleted M0 module must stay deleted (issue #1078).
RETIRED_MODULE = Path("app/core/local_backend/api.py")

_ROUTE_WITH_RAWSQL = re.compile(
    r"@(?:\w+)\.(?:post|get|put|delete|api_route)\(\s*[\"'][^\"']*rawsql",
    re.IGNORECASE,
)


def test_the_unauthenticated_m0_api_module_stays_deleted() -> None:
    """``api.py`` executed arbitrary SQL with no authentication; its only
    protection was that nobody imported it. It must never come back."""
    assert not (REPO_ROOT / RETIRED_MODULE).exists(), (
        f"{RETIRED_MODULE} must not be reintroduced: it exposed "
        f"POST /database/advance/rawsql with no authentication "
        f"(issue #1078). The guarded surface is {GUARDED_ROUTER}."
    )


def test_no_rawsql_routes_outside_the_guarded_router() -> None:
    """Every rawsql route lives in the token-protected router and nowhere
    else under ``app/``."""
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        if rel.as_posix() == GUARDED_ROUTER.as_posix():
            continue
        if _ROUTE_WITH_RAWSQL.search(path.read_text(encoding="utf-8")):
            offenders.append(rel.as_posix())

    assert offenders == [], (
        f"rawsql routes found outside {GUARDED_ROUTER}: {offenders}. "
        f"Raw SQL execution must stay behind the token-protected router "
        f"(issue #1078)."
    )
