"""Worker-local TTL cache for authorization revalidation (issues #143, #262, #287).

The session cookie signs the user's IDENTITY (email, user_id), which is
stable for the 7-day cookie lifetime. AUTHORIZATION (``is_authorized`` +
``rol``) can change at any moment, so
``app.core.auth_dependencies.require_authorized_user`` re-validates it
against ``usuarios_autorizados`` on every request.

Without a cache that is one extra ``SELECT`` per request. This module
memoizes each verdict for ``Settings.auth_cache_ttl_seconds`` (default
300s), reducing the steady-state cost to roughly one query per user per
five minutes. Explicit invalidation applies immediately inside the current
worker.

Deployment scope (issues #262 and #287)
---------------------------------------

The runtime backend is always :class:`InProcessAuthCache`: a per-worker
``dict`` guarded by a ``Lock``. Each process holds its own copy and a
restart starts empty. With multiple workers, an invalidation issued by
worker A does NOT propagate to worker B; the other worker can retain its
verdict until its TTL lapses or it restarts. The worst-case staleness
window is therefore ``Settings.auth_cache_ttl_seconds``.

The deployed Coolify application currently runs one Uvicorn worker. Before
increasing the Uvicorn worker count or application replica count, operators
must set ``APAP_AUTH_CACHE_TTL_SECONDS=0`` for immediate cross-worker
revocation. That disables cache hits and restores one authorization query
per authenticated request. See ``docs/runbooks/auth-cache-multi-worker.md``.

Issue #145 — write-after-invalidate race: every cached entry carries a
per-email ``generation`` and the cache key is ``(email, generation)``.
Each email has its own generation counter; ``invalidate_auth(email)``
bumps only that email's generation, so the prior verdict is unreachable
to subsequent readers while every other email keeps its cached verdict.
``invalidate_all`` bumps every email's generation so the whole cache is
unreachable at once (issue #280 fix — generations persist, they are NOT cleared).

Cache entries are invalidated:

- on ``add_authorized_user`` — the new/re-added email (``app.core.auth``);
- on ``deactivate_authorized_user`` — the deactivated email;
- on ``invalidate_all`` — admin reset tooling / tests;
- implicitly on process restart (deploy).

``AUTH_CACHE_KEY`` is a manual version marker an operator can bump to
signal a cache-schema change in code review; because the in-process store
is cleared on restart, bumping it documents intent rather than acting as a
runtime switch.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

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


class AuthCacheBackend(Protocol):
    """Internal contract for the runtime cache and injected test backends.

    Production uses :class:`InProcessAuthCache` exclusively. Keeping the
    Protocol decouples the module-level facades from the concrete class and
    lets tests inject deterministic fakes without exposing a runtime backend
    selector.

    ``None`` from :meth:`get` means a miss and the caller must consult the
    DB. An entry is fresh only while its age is strictly ``< ttl_seconds``;
    with ``ttl_seconds <= 0`` every entry reads as stale.

    Implementations must be safe to call from multiple threads in one
    process. :meth:`invalidate` is idempotent for missing emails.
    """

    def get(self, email: str, ttl_seconds: int) -> CachedAuth | None:
        """Return the cached verdict for ``email`` if still fresh, else ``None``."""
        ...

    def set(self, email: str, *, is_authorized: bool, rol: str | None) -> None:
        """Store (or overwrite) the authorization verdict for ``email``.

        Both positive and negative verdicts are cached: memoizing a deny
        avoids re-querying the DB for a just-deactivated user until the
        TTL lapses or :meth:`invalidate` is called.
        """
        ...

    def invalidate(self, email: str) -> None:
        """Drop the cached verdict for one email (idempotent if absent)."""
        ...

    def invalidate_all(self) -> None:
        """Clear every cached verdict (admin reset tooling / tests)."""


class InProcessAuthCache:
    """Worker-local in-memory cache (issue #143 / #145).

    The default backend. Lives in the worker's memory; ``invalidate``
    only affects THIS worker. With multiple workers, a revocation
    issued by worker A does NOT propagate to worker B until worker
    B's TTL lapses or the worker restarts. See module docstring +
    ``docs/runbooks/auth-cache-multi-worker.md`` for the multi-worker
    remediation playbook.
    """

    def __init__(self) -> None:
        # (email, generation) -> CachedAuth. Guarded by ``_lock`` for
        # every access. The generation component is the per-email
        # generation at write time (issue #145) — see module docstring
        # for the race semantics.
        self._cache: dict[tuple[str, int], CachedAuth] = {}
        # Per-email generation counters (issue #145). Bumped by
        # :meth:`invalidate` for the named email only;
        # :meth:`invalidate_all` bumps every email's counter. Default
        # for an email never seen is 0 — the first :meth:`set` writes
        # under generation 0.
        self._generation: dict[str, int] = {}
        self._lock = Lock()

    def _current_generation(self, email: str) -> int:
        """Return the current per-email cache generation (issue #145).

        The email is normalized to lowercase to match the case-insensitive
        cache key behaviour (issue #278).

        Exposed for tests and audit. Reading the generation does not
        acquire the lock because the int read from the dict is atomic
        in CPython and any value seen here is only used to compare
        against an entry's stamped generation — a torn read cannot
        violate the invariant.
        """
        return self._generation.get(email.lower(), 0)

    def get(self, email: str, ttl_seconds: int) -> CachedAuth | None:
        """Return the cached verdict for ``email`` if still fresh, else ``None``.

        Issue #145 — the lookup uses the email's current generation so
        an entry written under a previous generation is unreachable
        after an invalidation, regardless of whether the dict still
        contains its tuple.

        The email is normalized to lowercase before use as a cache key so
        that all case variants of the same address (e.g.
        ``Maria.Lopez@Example.COM`` and ``maria.lopez@example.com``) share
        the same cache entry and invalidation (issue #278).
        """
        email = email.lower()
        with self._lock:
            gen = self._generation.get(email, 0)
            entry = self._cache.get((email, gen))
            if entry is None:
                return None
            if time.monotonic() - entry.cached_at >= ttl_seconds:
                return None
            return entry

    def set(self, email: str, *, is_authorized: bool, rol: str | None) -> None:
        """Store (or overwrite) the authorization verdict for ``email``.

        Issue #145 — the entry is keyed under ``(email, email_gen)`` at
        the moment of writing. If an invalidation has bumped the
        email's generation since the caller observed the cache as
        empty, the new key is the post-invalidate generation and the
        entry is reachable from the next read; the pre-invalidate
        tuple remains in the dict as dead memory (and is replaced by
        the next ``set`` for that key).

        The email is normalized to lowercase so that all case variants
        share the same cache entry (issue #278).
        """
        email = email.lower()
        with self._lock:
            gen = self._generation.get(email, 0)
            self._cache[(email, gen)] = CachedAuth(
                is_authorized=is_authorized,
                rol=rol,
                cached_at=time.monotonic(),
                generation=gen,
            )
            # Track the generation so invalidate_all can bump this email.
            self._generation[email] = gen

    def invalidate(self, email: str) -> None:
        """Drop the cached verdict for one email (idempotent if absent).

        Issue #145 — the invalidate bumps ONLY the named email's
        generation. Other emails keep their cached verdict; the
        deactivated email's prior entry at ``(email, old_gen)`` is
        unreachable to subsequent reads because :meth:`get` now keys
        against ``(email, new_gen)`` which does not exist. The dict
        tuple is left in place as dead memory; the next ``set`` for
        the same email writes under the new generation and overwrites
        it.

        The email is normalized to lowercase so that all case variants
        of the same address share the same generation counter
        (issue #278).

        **Scope**: WORKER-LOCAL. The generation bump is visible only to
        the worker that called this method. Other workers keep serving
        their cached verdict until their TTL expires or the worker
        restarts. Multi-worker deployments that require immediate
        revocation must set ``APAP_AUTH_CACHE_TTL_SECONDS=0``.
        """
        email = email.lower()
        with self._lock:
            self._generation[email] = self._generation.get(email, 0) + 1

    def invalidate_all(self) -> None:
        """Atomically make every cached verdict unreachable.

        Bumps every per-email generation counter so any pre-existing cache
        entry's ``generation`` is now stale; then clears the entry dict. The
        counters stay in ``_generation`` (carry the bumped values forward)
        — they are NOT cleared, because a ``clear()`` would reset them to 0
        and reopen the write-after-invalidate race closed by issue #145
        (see issue #280).

        **Scope**: WORKER-LOCAL.
        """
        with self._lock:
            # Iterate over ALL emails that have a cache entry (via _cache
            # keys), not just emails in _generation. This ensures emails
            # only SET (never explicitly invalidated) are also bumped.
            emails_in_cache = {email for (email, _gen) in self._cache}
            for email in emails_in_cache:
                self._generation[email] = self._generation.get(email, 0) + 1
            self._cache.clear()


# ---------------------------------------------------------------------------
# Factory + module-level facade (backwards-compatible public API)
# ---------------------------------------------------------------------------


_DEFAULT_BACKEND: AuthCacheBackend | None = None


def _get_backend() -> AuthCacheBackend:
    """Return the memoized in-process backend, constructing it on first access."""
    global _DEFAULT_BACKEND
    if _DEFAULT_BACKEND is None:
        _DEFAULT_BACKEND = InProcessAuthCache()
    return _DEFAULT_BACKEND


def _reset_backend_for_testing() -> None:
    """Test helper: forget the memoized backend and its cached entries."""
    global _DEFAULT_BACKEND
    _DEFAULT_BACKEND = None


def _set_backend_for_testing(backend: AuthCacheBackend) -> None:
    """Test helper: force the module to use a specific backend instance.

    Used to assert that module-level facades dispatch to an injected test
    backend rather than touching module globals directly.
    """
    global _DEFAULT_BACKEND
    _DEFAULT_BACKEND = backend


# --- Module-level public API (issue #143, preserved by issue #262) -------


def get_cached_auth(email: str, ttl_seconds: int) -> CachedAuth | None:
    """Return the cached verdict for ``email`` if still fresh, else ``None``.

    A return of ``None`` means "miss" — the caller must consult the DB.
    An entry is fresh only while its age is strictly ``< ttl_seconds``;
    with ``ttl_seconds <= 0`` every entry reads as stale (cache
    effectively disabled), which is the knob for immediate revocation.

    **Scope (issues #262 and #287)**: the verdict is worker-local. With
    multiple workers, set ``APAP_AUTH_CACHE_TTL_SECONDS=0`` to prevent
    one worker from serving a cached verdict invalidated in another.

    Issue #145 — the lookup uses the email's current generation so an
    entry written under a previous generation is unreachable after an
    invalidation, regardless of whether the dict still contains its
    tuple.
    """
    return _get_backend().get(email, ttl_seconds)


def set_cached_auth(email: str, *, is_authorized: bool, rol: str | None) -> None:
    """Store (or overwrite) the authorization verdict for ``email``.

    Both positive and negative verdicts are cached: memoizing a deny
    avoids re-querying the DB for a just-deactivated user until the TTL
    lapses or :func:`invalidate_auth` is called.

    Issue #145 — the entry is keyed under ``(email, email_gen)`` at the
    moment of writing. If an invalidation has bumped the email's
    generation since the caller observed the cache as empty, the new
    key is the post-invalidate generation and the entry is reachable
    from the next read; the pre-invalidate tuple remains in the dict
    as dead memory (and is replaced by the next ``set`` for that key).
    """
    _get_backend().set(email, is_authorized=is_authorized, rol=rol)


def _case_variants(email: str) -> set[str]:
    """Generate all case variants of an email address for cache invalidation.

    Defense-in-depth for issue #278: legacy entries may have been cached at
    non-normalized casings (e.g. ``Maria.Lopez@Example.COM``).  Invalidation
    that only bumps the canonical key leaves stale entries at variant casings
    reachable if a future lookup uses those casings.  This function generates
    all variants reachable by swapping the case of each alphabetic character
    in turn, plus the full-swapcase variant.
    """
    # All-lowercase is the canonical form used at write time.
    variants = {email.lower(), email.upper()}
    chars = list(email)
    for i, ch in enumerate(chars):
        if ch.isalpha():
            chars[i] = ch.swapcase()
            variants.add("".join(chars))
            chars[i] = ch  # restore
    return variants


def invalidate_auth(email: str) -> None:
    """Drop the cached verdict for one email and all its case variants.

    Issue #145 — the invalidate bumps the named email's generation on the
    in-process backend. Issue #278 — because the cache keys on the exact
    string passed, and ``add_authorized_user`` / ``get_user_by_email`` now
    always normalize before reaching the cache, a legacy entry cached at a
    non-normalized casing would survive a single-key invalidation.  This
    function invalidates the canonical key AND every case-variant string
    so that no stale entry survives regardless of which casing the
    service layer stored it under.

    **Scope (issues #262 and #287)** — read this before deploying with
    multiple workers: invalidation is WORKER-LOCAL. It is visible only
    to the worker that called this function. Other workers can keep a
    stale verdict until their TTL expires or the worker restarts; the
    worst-case stale-verdict window is ``auth_cache_ttl_seconds``
    (default 300s).

    The deployed Coolify application currently runs one worker. Before
    increasing its worker or replica count, set
    ``APAP_AUTH_CACHE_TTL_SECONDS=0`` (one extra ``SELECT`` per request)
    for immediate revocation. See
    ``docs/runbooks/auth-cache-multi-worker.md``.
    """
    backend = _get_backend()
    for variant in _case_variants(email):
        backend.invalidate(variant)


def invalidate_all() -> None:
    """Clear every cached verdict (admin reset tooling / tests).

    Issue #145 — bumps every email's generation on the in-process
    backend so all pre-invalidate entries are unreachable to subsequent
    reads. The dict is also cleared as a memory hygiene step; the
    generation bump is what closes the read-side race for every email
    simultaneously.

    **Scope (issues #262 and #287)**: WORKER-LOCAL. Other workers retain
    their own entries until TTL expiry or restart.
    """
    _get_backend().invalidate_all()


def _current_generation(email: str) -> int:
    """Return the current per-email cache generation (issue #145).

    Module-level facade preserved for the issue #145 race-window tests
    (``tests/test_auth_cache.py``). Delegates to the in-process
    backend's per-email counter; returns ``0`` for injected test
    backends that do not expose that private counter.
    """
    backend = _get_backend()
    if isinstance(backend, InProcessAuthCache):
        return backend._current_generation(email)
    return 0
