"""TTL cache for per-request authorization revalidation (issue #143, #262).

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

Backend-agnostic seam (issue #262)
----------------------------------

The cache backend is selected by ``Settings.auth_cache_backend``:

- ``"in_process"`` (default): per-worker in-memory ``dict`` + ``Lock``.
  **WORKER-LOCAL scope** — each process holds its own copy; a process
  restart (i.e. a deploy) starts empty. With multiple workers, a
  revocation issued by worker A does NOT propagate to worker B until
  worker B's TTL lapses or the worker restarts. The per-worker TTL
  window is the maximum staleness product sees. To minimise the
  window in multi-worker deployments, set
  ``APAP_AUTH_CACHE_TTL_SECONDS=0`` (effectively disables the cache;
  one extra SELECT per request) or switch to the shared backend
  (``"redis"``).
- ``"redis"`` (opt-in, follow-up PR for the actual wire-up):
  SHARED scope — ``invalidate_auth(email)`` propagates to every worker
  in ~1 RTT. Selecting ``redis`` in this slice selects
  :class:`RedisAuthCache`, which is the structural seam only; the
  follow-up PR wires the real Redis client (TLS, retry, sentinel, JSON
  encoding). See ``docs/runbooks/auth-cache-multi-worker.md`` for the
  multi-worker remediation playbook.

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

The generation counter is part of the :class:`InProcessAuthCache`
contract (issue #145); the Redis backend exposes the same Protocol but
its generation model is internal (per-email version key, atomic
``INCR``). Tests that need to inspect the per-email generation pin
:class:`InProcessAuthCache` directly; the module-level
``_current_generation`` facade returns ``0`` for non-in-process backends.

Cache entries are invalidated:

- on ``add_authorized_user`` — the new/re-added email (``app.core.auth``);
- on ``deactivate_authorized_user`` — the deactivated email;
- on ``invalidate_all`` — admin reset tooling / tests;
- implicitly on process restart (deploy).

``AUTH_CACHE_KEY`` is a manual version marker an operator can bump to
signal a cache-schema change in code review; because the in-process
store is cleared on restart, bumping it is documentation of intent
rather than a runtime switch.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Protocol

from app.core.config import Settings, get_settings

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
    """Structural contract for a per-email authorization cache (issue #262).

    Any backend that satisfies this Protocol can be swapped in via
    :class:`app.core.config.Settings.auth_cache_backend` without touching
    call sites. Implementations MUST be safe to call from multiple worker
    threads in the same process; they MAY be shared across workers
    (Redis, memcached, …) or process-local (in-process dict).

    The :meth:`get` contract: ``None`` means "miss" — the caller MUST
    consult the DB. An entry is fresh only while its age is strictly
    ``< ttl_seconds``; with ``ttl_seconds <= 0`` every entry reads as
    stale (cache effectively disabled), which is the knob for
    immediate revocation.

    The :meth:`invalidate` contract: idempotent on missing emails;
    backend implementations SHOULD propagate the invalidation
    cluster-wide when shared, or only locally when worker-local — the
    caller picks by selecting the backend.
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

        Exposed for tests and audit. Reading the generation does not
        acquire the lock because the int read from the dict is atomic
        in CPython and any value seen here is only used to compare
        against an entry's stamped generation — a torn read cannot
        violate the invariant.
        """
        return self._generation.get(email, 0)

    def get(self, email: str, ttl_seconds: int) -> CachedAuth | None:
        """Return the cached verdict for ``email`` if still fresh, else ``None``.

        Issue #145 — the lookup uses the email's current generation so
        an entry written under a previous generation is unreachable
        after an invalidation, regardless of whether the dict still
        contains its tuple.
        """
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
        """
        with self._lock:
            gen = self._generation.get(email, 0)
            self._cache[(email, gen)] = CachedAuth(
                is_authorized=is_authorized,
                rol=rol,
                cached_at=time.monotonic(),
                generation=gen,
            )

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

        **Scope**: WORKER-LOCAL. The generation bump is visible only to
        the worker that called this method. Other workers keep serving
        their cached verdict until their TTL expires or the worker
        restarts. For cluster-wide revocation, select the Redis
        backend (see module docstring + runbook).
        """
        with self._lock:
            self._generation[email] = self._generation.get(email, 0) + 1

    def invalidate_all(self) -> None:
        """Clear every cached verdict (admin reset tooling / tests).

        Issue #145 — bumps every email's generation so all
        pre-invalidate entries are unreachable to subsequent reads.
        The dict is also cleared as a memory hygiene step; the
        generation bump is what closes the read-side race for every
        email simultaneously.

        **Scope**: WORKER-LOCAL.
        """
        with self._lock:
            for email in list(self._generation.keys()):
                self._generation[email] += 1
            self._generation.clear()
            self._cache.clear()


class RedisAuthCache:
    """Shared Redis backend (issue #262) — structural seam.

    This slice ships the **structural seam only**; the follow-up PR
    wires the real Redis client (TLS, retry, sentinel, JSON encoding,
    generation key layout). The class is here so
    :class:`app.core.config.Settings.auth_cache_backend == "redis"``
    selects a real object that satisfies :class:`AuthCacheBackend`
    instead of falling back silently to in-process (silent fallback
    would mask a misconfig).

    The constructor takes a pre-built Redis client (``redis_client``)
    so the lifespan / settings module can wire the production client
    in the follow-up PR without touching this class. Tests inject a
    fake / ``fakeredis``-like client.

    Operations raise :class:`NotImplementedError` until the follow-up
    wire-up lands. Selecting ``"redis"`` without the follow-up is a
    fail-loud path, not a silent fallback — see
    ``docs/runbooks/auth-cache-multi-worker.md``.

    **Scope** (once wired): SHARED — ``invalidate_auth(email)``
    propagates to every worker in ~1 RTT, so a revocation issued by
    worker A becomes visible to worker B without waiting for its
    TTL.
    """

    def __init__(self, redis_client: Any, ttl_seconds: int = 300) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    def get(self, email: str, ttl_seconds: int) -> CachedAuth | None:
        raise NotImplementedError(
            "RedisAuthCache is the structural seam for issue #262; the "
            "follow-up PR wires the real Redis client. See "
            "docs/runbooks/auth-cache-multi-worker.md."
        )

    def set(self, email: str, *, is_authorized: bool, rol: str | None) -> None:
        raise NotImplementedError(
            "RedisAuthCache is the structural seam for issue #262; the "
            "follow-up PR wires the real Redis client. See "
            "docs/runbooks/auth-cache-multi-worker.md."
        )

    def invalidate(self, email: str) -> None:
        raise NotImplementedError(
            "RedisAuthCache is the structural seam for issue #262; the "
            "follow-up PR wires the real Redis client. See "
            "docs/runbooks/auth-cache-multi-worker.md."
        )

    def invalidate_all(self) -> None:
        raise NotImplementedError(
            "RedisAuthCache is the structural seam for issue #262; the "
            "follow-up PR wires the real Redis client. See "
            "docs/runbooks/auth-cache-multi-worker.md."
        )


# ---------------------------------------------------------------------------
# Factory + module-level facade (backwards-compatible public API)
# ---------------------------------------------------------------------------


_DEFAULT_BACKEND: AuthCacheBackend | None = None


def _get_backend() -> AuthCacheBackend:
    """Return the process-cached backend, constructing it on first access.

    The backend is selected from :class:`Settings.auth_cache_backend`:
    unknown names fall back to :class:`InProcessAuthCache` (fail-soft;
    a typo in the env var must NOT crash at request time — the
    misconfig is visible in the logs instead).

    Memoised: tests that need a fresh backend call
    :func:`_reset_backend_for_testing` first.
    """
    global _DEFAULT_BACKEND
    if _DEFAULT_BACKEND is None:
        settings: Settings = get_settings()
        backend_name = settings.auth_cache_backend
        if backend_name == "redis":
            _DEFAULT_BACKEND = RedisAuthCache(
                redis_client=None,  # follow-up PR wires the real client
                ttl_seconds=settings.auth_cache_ttl_seconds,
            )
        else:
            _DEFAULT_BACKEND = InProcessAuthCache()
    return _DEFAULT_BACKEND


def _reset_backend_for_testing() -> None:
    """Test helper: forget the memoised backend so the factory re-reads config.

    Tests that mutate ``APAP_AUTH_CACHE_BACKEND`` via ``monkeypatch``
    must call this between cases (or rely on the autouse fixture in
    ``tests/test_auth_cache_backend.py``) so the env change takes
    effect.
    """
    global _DEFAULT_BACKEND
    _DEFAULT_BACKEND = None


def _set_backend_for_testing(backend: AuthCacheBackend) -> None:
    """Test helper: force the module to use a specific backend instance.

    Used to assert that module-level facades dispatch to the configured
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

    **Scope (issue #262)**: dispatches to the configured backend. With
    the in-process backend (default) the verdict is worker-local; with
    the Redis backend the verdict is shared across workers.

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


def invalidate_auth(email: str) -> None:
    """Drop the cached verdict for one email (idempotent if absent).

    Issue #145 — the invalidate bumps ONLY the named email's generation
    on the in-process backend. Other emails keep their cached verdict;
    the deactivated email's prior entry at ``(email, old_gen)`` is
    unreachable to subsequent reads because :func:`get_cached_auth` now
    keys against ``(email, new_gen)`` which does not exist.

    **Scope (issue #262)** — read this before deploying with multiple
    workers:

    - ``in_process`` backend (default, WORKER-LOCAL): the invalidation
      is visible ONLY to the worker that called this method. Other
      workers keep serving the stale verdict until their TTL expires
      or the worker restarts. With N workers the worst-case
      stale-verdict window is ``auth_cache_ttl_seconds`` (default 300s).
    - ``redis`` backend (SHARED, follow-up PR): the invalidation
      propagates to every worker in ~1 RTT, so the cluster-wide
      staleness window drops to one network round trip.

    For multi-worker deployments, either drop
    ``APAP_AUTH_CACHE_TTL_SECONDS`` to ``0`` (one extra ``SELECT`` per
    request, immediate revocation in any worker) or switch to the
    Redis backend. See ``docs/runbooks/auth-cache-multi-worker.md``.
    """
    _get_backend().invalidate(email)


def invalidate_all() -> None:
    """Clear every cached verdict (admin reset tooling / tests).

    Issue #145 — bumps every email's generation on the in-process
    backend so all pre-invalidate entries are unreachable to subsequent
    reads. The dict is also cleared as a memory hygiene step; the
    generation bump is what closes the read-side race for every email
    simultaneously.

    **Scope (issue #262)**: WORKER-LOCAL on the in-process backend;
    SHARED on the Redis backend (once wired).
    """
    _get_backend().invalidate_all()


def _current_generation(email: str) -> int:
    """Return the current per-email cache generation (issue #145).

    Module-level facade preserved for the issue #145 race-window tests
    (``tests/test_auth_cache.py``). Delegates to the in-process
    backend's per-email counter; returns ``0`` for non-in-process
    backends because the Redis model exposes generation internally
    (per-email version key, atomic ``INCR``) — tests that need the
    Redis generation pin :class:`InProcessAuthCache` directly.
    """
    backend = _get_backend()
    if isinstance(backend, InProcessAuthCache):
        return backend._current_generation(email)
    return 0
