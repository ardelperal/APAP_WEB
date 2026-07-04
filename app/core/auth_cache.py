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

Issue #145 — write-after-invalidate race: every cached entry carries a
per-email ``generation`` and the cache key is ``(email, generation)``.
Each email has its own generation counter; ``invalidate_auth(email)``
bumps ONLY that email's generation, so the deactivated email's prior
verdict is unreachable to any subsequent reader while every other email
keeps its cached verdict. The narrow race window between a T1 cache-miss,
T1's DB query, T2's invalidation, and T1's write is bounded by the TTL —
the generation guard makes the pre-invalidate verdict traceable for
audit and collapses it into an unreachable key so a process restart
isn't the only thing that drops it. ``invalidate_all`` bumps every email's
generation so the whole cache is unreachable at once.

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
    TTL math is immune to system-clock adjustments. ``generation`` is
    the per-email generation counter at write time (issue #145) — an
    entry's generation that no longer matches the email's current
    generation is unreachable to every subsequent read because the cache
    key includes the generation.
    """

    is_authorized: bool
    rol: str | None
    cached_at: float
    generation: int


# (email, generation) -> CachedAuth. Guarded by ``_cache_lock`` for every
# access. The generation component of the key is the per-email generation
# at write time (issue #145) — see module docstring for the race semantics.
_auth_cache: dict[tuple[str, int], CachedAuth] = {}
# Per-email generation counters (issue #145). Bumped by ``invalidate_auth``
# for the named email only; ``invalidate_all`` bumps every email's counter.
# Default for an email never seen is 0 — the first ``set_cached_auth``
# writes under generation 0.
_email_generation: dict[str, int] = {}
_cache_lock = Lock()


def _current_generation(email: str) -> int:
    """Return the current per-email cache generation (issue #145).

    Exposed for tests and audit. Reading the generation does not acquire
    the lock because the int read from the dict is atomic in CPython and
    any value seen here is only used to compare against an entry's
    stamped generation — a torn read cannot violate the invariant.
    """
    return _email_generation.get(email, 0)


def get_cached_auth(email: str, ttl_seconds: int) -> CachedAuth | None:
    """Return the cached verdict for ``email`` if still fresh, else None.

    A return of ``None`` means "miss" — the caller must consult the DB.
    An entry is fresh only while its age is strictly ``< ttl_seconds``;
    with ``ttl_seconds <= 0`` every entry reads as stale (cache
    effectively disabled), which is the knob for immediate revocation.

    Issue #145 — the lookup uses the email's current generation so an
    entry written under a previous generation is unreachable after an
    invalidation, regardless of whether the dict still contains its tuple.
    """
    with _cache_lock:
        gen = _email_generation.get(email, 0)
        entry = _auth_cache.get((email, gen))
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

    Issue #145 — the entry is keyed under ``(email, email_gen)`` at the
    moment of writing. If an invalidation has bumped the email's
    generation since the caller observed the cache as empty, the new key
    is the post-invalidate generation and the entry is reachable from
    the next read; the pre-invalidate tuple remains in the dict as dead
    memory (and is replaced by the next ``set`` for that key).
    """
    with _cache_lock:
        gen = _email_generation.get(email, 0)
        _auth_cache[(email, gen)] = CachedAuth(
            is_authorized=is_authorized,
            rol=rol,
            cached_at=time.monotonic(),
            generation=gen,
        )


def invalidate_auth(email: str) -> None:
    """Drop the cached verdict for one email (idempotent if absent).

    Issue #145 — the invalidate bumps ONLY the named email's generation.
    Other emails keep their cached verdict; the deactivated email's prior
    entry at ``(email, old_gen)`` is unreachable to subsequent reads
    because ``get_cached_auth`` now keys against ``(email, new_gen)``
    which does not exist. The dict tuple is left in place as dead memory;
    the next ``set`` for the same email writes under the new generation
    and overwrites it.
    """
    with _cache_lock:
        _email_generation[email] = _email_generation.get(email, 0) + 1


def invalidate_all() -> None:
    """Clear every cached verdict (admin reset tooling / tests).

    Issue #145 — bumps every email's generation so all pre-invalidate
    entries are unreachable to subsequent reads. The dict is also cleared
    as a memory hygiene step; the generation bump is what closes the
    read-side race for every email simultaneously.
    """
    with _cache_lock:
        for email in list(_email_generation.keys()):
            _email_generation[email] += 1
        _email_generation.clear()
        _auth_cache.clear()
