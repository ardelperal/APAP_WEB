"""TTL cache for per-request authorization revalidation (issue #143).

The session cookie signs the user's IDENTITY (email, user_id), which is
stable for the 7-day cookie lifetime. AUTHORIZATION (``is_authorized`` +
``rol``), by contrast, can change at any moment — a developer may
deactivate a user via ``/admin/users/{id}/deactivate`` — so it is
re-validated against ``usuarios_autorizados`` on every request in
``app.core.auth_dependencies.require_authorized_user``.

Without a cache that is one extra ``SELECT`` per request. This module
memoizes the verdict per email for a short TTL
(``Settings.auth_cache_ttl_seconds``, default 300s) so the steady-state
cost is ~one query per user per 5 minutes, while a revocation still takes
effect within the TTL (or immediately, via explicit invalidation below).

The cache is a process-global in-memory dict guarded by a ``Lock``. It is
NOT shared across worker processes: each process holds its own copy and a
process restart (i.e. a deploy) starts empty — that is the deploy-time
invalidation. ``AUTH_CACHE_KEY`` is a manual version marker an operator
can bump to signal a cache-schema change in code review; because the
store is per-process and cleared on restart, bumping it is documentation
of intent rather than a runtime switch.

Cache entries are invalidated:

- on ``add_authorized_user`` — the new/re-added email (``app.core.auth``);
- on ``deactivate_authorized_user`` — the deactivated email;
- on ``invalidate_all`` — admin reset tooling / tests;
- implicitly on process restart (deploy).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock

# Manual cache-schema version marker (see module docstring). Bump in a
# hotfix commit to document that cached verdicts from an older code
# version must not be trusted; the per-process store is cleared on the
# restart the deploy performs, so this is intent, not a runtime toggle.
AUTH_CACHE_KEY = "v1"


@dataclass(frozen=True, slots=True)
class CachedAuth:
    """A memoized authorization verdict for one email.

    ``cached_at`` is a ``time.monotonic()`` reading (not wall-clock) so
    TTL math is immune to system-clock adjustments.
    """

    is_authorized: bool
    rol: str | None
    cached_at: float


# email -> CachedAuth. Guarded by ``_cache_lock`` for every access.
_auth_cache: dict[str, CachedAuth] = {}
_cache_lock = Lock()


def get_cached_auth(email: str, ttl_seconds: int) -> CachedAuth | None:
    """Return the cached verdict for ``email`` if still fresh, else None.

    A return of ``None`` means "miss" — the caller must consult the DB.
    An entry is fresh only while its age is strictly ``< ttl_seconds``;
    with ``ttl_seconds <= 0`` every entry reads as stale (cache
    effectively disabled), which is the knob for immediate revocation.
    """
    with _cache_lock:
        entry = _auth_cache.get(email)
        if entry is None:
            return None
        if time.monotonic() - entry.cached_at >= ttl_seconds:
            return None
        return entry


def set_cached_auth(email: str, *, is_authorized: bool, rol: str | None) -> None:
    """Store (or overwrite) the authorization verdict for ``email``.

    Both positive and negative verdicts are cached: memoizing a deny
    avoids re-querying the DB for a just-deactivated user until the TTL
    lapses or ``invalidate_auth`` is called.
    """
    with _cache_lock:
        _auth_cache[email] = CachedAuth(
            is_authorized=is_authorized,
            rol=rol,
            cached_at=time.monotonic(),
        )


def invalidate_auth(email: str) -> None:
    """Drop the cached verdict for one email (idempotent if absent)."""
    with _cache_lock:
        _auth_cache.pop(email, None)


def invalidate_all() -> None:
    """Clear every cached verdict (admin reset tooling / tests)."""
    with _cache_lock:
        _auth_cache.clear()
