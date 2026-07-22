"""Tests for the swappable auth-cache backend (issue #262).

Issue #143 introduced an in-process TTL cache backing
``require_authorized_user``. Issue #262 documents its per-worker scope and
adds a structural seam for an opt-in shared backend (Redis or equivalent)
so multi-worker deployments can revoke ``invalidate_auth(email)`` across
workers instead of waiting up to ``auth_cache_ttl_seconds`` per worker.

These tests pin the seam:

- ``AuthCacheBackend`` Protocol exists so any backend can satisfy it.
- ``InProcessAuthCache`` is the working default (current behavior, just
  refactored into a class).
- ``RedisAuthCache`` is the structural placeholder for the shared backend
  (wire-up is a follow-up PR; this slice ships the seam only).
- ``app.core.auth_cache`` keeps its public API (``get_cached_auth``,
  ``set_cached_auth``, ``invalidate_auth``, ``invalidate_all``,
  ``_current_generation``) so callers do not change.

The docstring / scope contract (``invalidate_auth`` mentions
worker-local vs shared) is pinned with an AST-level grep so a future
documentation drift is caught at test time.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.core import auth_cache
from app.core.auth_cache import (
    AuthCacheBackend,
    InProcessAuthCache,
    RedisAuthCache,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    """Reset the auth-cache backend between tests.

    The module keeps a process-global ``_DEFAULT_BACKEND`` that the
    factory memoises on first access. Without this reset, a test that
    monkeypatches ``APAP_AUTH_CACHE_BACKEND=redis`` would leak the
    Redis-backend selection into the next test that expects the default
    in-process backend.
    """
    auth_cache._reset_backend_for_testing()
    yield
    auth_cache._reset_backend_for_testing()


# ---------------------------------------------------------------------------
# Protocol contract
# ---------------------------------------------------------------------------


def test_auth_cache_module_exposes_backend_protocol() -> None:
    """``AuthCacheBackend`` is importable from ``app.core.auth_cache``.

    Without a Protocol there is no structural seam — backends would
    couple to a concrete class and swapping them later would require a
    refactor of every call site.
    """
    assert hasattr(auth_cache, "AuthCacheBackend"), (
        "app.core.auth_cache must expose AuthCacheBackend Protocol"
    )
    assert inspect.isclass(AuthCacheBackend), (
        f"AuthCacheBackend must be a class (Protocol), got {type(AuthCacheBackend)!r}"
    )


def test_in_process_backend_satisfies_protocol_shape() -> None:
    """``InProcessAuthCache`` exposes the four protocol methods.

    The Protocol contract is structural; this test pins the concrete
    implementation matches the expected shape so a refactor that renames
    or removes a method is caught here before it reaches production.
    """
    backend = InProcessAuthCache()
    for name in ("get", "set", "invalidate", "invalidate_all"):
        assert callable(getattr(backend, name, None)), (
            f"InProcessAuthCache must expose a callable '{name}' method "
            f"to satisfy AuthCacheBackend"
        )


# ---------------------------------------------------------------------------
# InProcessAuthCache class
# ---------------------------------------------------------------------------


def test_in_process_backend_set_then_get_returns_value() -> None:
    """Happy path: a set-then-get within TTL returns the stored verdict."""
    backend = InProcessAuthCache()
    backend.set("alice@example.com", is_authorized=True, rol="key_user")

    entry = backend.get("alice@example.com", ttl_seconds=300)

    assert entry is not None
    assert entry.is_authorized is True
    assert entry.rol == "key_user"


def test_in_process_backend_get_returns_none_when_empty() -> None:
    """Sad path: an empty cache returns ``None`` (caller hits the DB)."""
    backend = InProcessAuthCache()

    assert backend.get("nobody@example.com", ttl_seconds=300) is None


def test_in_process_backend_ttl_zero_disables_cache() -> None:
    """Edge path: ``ttl_seconds=0`` disables the cache (entry already stale).

    This is the knob operators use when immediate revocation is required:
    one extra ``SELECT`` per request, but no stale verdict beyond the
    in-flight request.
    """
    backend = InProcessAuthCache()
    backend.set("bob@example.com", is_authorized=True, rol="admin")

    assert backend.get("bob@example.com", ttl_seconds=0) is None


def test_in_process_backend_invalidate_scopes_per_email() -> None:
    """``invalidate(email)`` removes only that email; siblings keep their verdict."""
    backend = InProcessAuthCache()
    backend.set("keep@example.com", is_authorized=True, rol="admin")
    backend.set("drop@example.com", is_authorized=True, rol="key_user")

    backend.invalidate("drop@example.com")

    assert backend.get("drop@example.com", ttl_seconds=300) is None
    assert backend.get("keep@example.com", ttl_seconds=300) is not None


# ---------------------------------------------------------------------------
# RedisAuthCache structural seam
# ---------------------------------------------------------------------------


def test_redis_backend_class_is_importable_without_redis_library() -> None:
    """The Redis backend class is importable without the redis library.

    The default install (dev / CI) has no redis-py dep. The factory
    must be able to import :class:`RedisAuthCache` for the config-based
    selection to work; if the class required ``import redis`` at module
    load time, opting in via env var would crash with ``ImportError``
    even before any operation ran.
    """
    assert inspect.isclass(RedisAuthCache), (
        f"RedisAuthCache must be a class, got {type(RedisAuthCache)!r}"
    )


def test_redis_backend_raises_not_implemented_until_wired() -> None:
    """Operations on ``RedisAuthCache`` raise ``NotImplementedError``.

    This slice ships the STRUCTURAL SEAM only. Wiring the real Redis
    client (TLS, retry, sentinel, JSON encoding) is a follow-up PR
    tracked in ``docs/runbooks/auth-cache-multi-worker.md``. Until that
    lands, opting in via ``APAP_AUTH_CACHE_BACKEND=redis`` without a
    wired client must fail loud, not silently fall back to in-process
    (silent fallback would mask the misconfig).
    """
    sentinel = object()  # any client works — methods raise before use
    backend = RedisAuthCache(redis_client=sentinel, ttl_seconds=300)

    with pytest.raises(NotImplementedError):
        backend.get("anyone@example.com", ttl_seconds=300)
    with pytest.raises(NotImplementedError):
        backend.set("anyone@example.com", is_authorized=True, rol="key_user")
    with pytest.raises(NotImplementedError):
        backend.invalidate("anyone@example.com")
    with pytest.raises(NotImplementedError):
        backend.invalidate_all()


# ---------------------------------------------------------------------------
# Factory / configuration
# ---------------------------------------------------------------------------


def test_default_backend_is_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no env override the factory returns ``InProcessAuthCache``.

    This is the regression guard for "in-process remains the default,
    no new deps for dev" (acceptance criterion #2 of issue #262).
    """
    monkeypatch.delenv("APAP_AUTH_CACHE_BACKEND", raising=False)
    auth_cache._reset_backend_for_testing()

    backend = auth_cache._get_backend()

    assert isinstance(backend, InProcessAuthCache), (
        f"default backend must be InProcessAuthCache, got {type(backend).__name__}"
    )


def test_setting_auth_cache_backend_redis_returns_redis_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``APAP_AUTH_CACHE_BACKEND=redis`` selects ``RedisAuthCache``.

    The opt-in wiring path. The factory reads the env-driven
    ``Settings.auth_cache_backend`` and constructs the matching backend.
    """
    monkeypatch.setenv("APAP_AUTH_CACHE_BACKEND", "redis")
    auth_cache._reset_backend_for_testing()

    backend = auth_cache._get_backend()

    assert isinstance(backend, RedisAuthCache), (
        f"with APAP_AUTH_CACHE_BACKEND=redis the factory must return "
        f"RedisAuthCache, got {type(backend).__name__}"
    )


def test_setting_unknown_backend_falls_back_to_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sad path: an unknown backend name falls back to in-process.

    Fail-soft (default-deny from the opposite direction): a typo in the
    env var (``APAP_AUTH_CACHE_BACKEND=reddis``) must NOT silently raise
    at request time. Falling back to the known-good in-process backend
    is the conservative choice; the misconfig is visible in the logs.
    """
    monkeypatch.setenv("APAP_AUTH_CACHE_BACKEND", "this-is-not-a-backend")
    auth_cache._reset_backend_for_testing()

    backend = auth_cache._get_backend()

    assert isinstance(backend, InProcessAuthCache), (
        f"unknown backend name must fall back to InProcessAuthCache, "
        f"got {type(backend).__name__}"
    )


def test_get_backend_is_memoised() -> None:
    """The factory memoises the backend across calls (process-global).

    The cache is a process-global singleton by design (the existing
    in-process state lives in module globals; swapping it on every call
    would defeat the per-email invalidation). Tests that need a fresh
    backend call ``_reset_backend_for_testing()``.
    """
    first = auth_cache._get_backend()
    second = auth_cache._get_backend()

    assert first is second


# ---------------------------------------------------------------------------
# Public API regression guards (issue #262 DoD: "Don't change the public
# API of auth_cache.py or provide a backwards-compatible shim")
# ---------------------------------------------------------------------------


def test_module_level_facades_still_work() -> None:
    """The public module-level functions are unchanged.

    Callers (``app.core.auth_dependencies``,
    ``app.core.auth.add_authorized_user``,
    ``app.core.auth.deactivate_authorized_user``) import
    ``auth_cache.get_cached_auth`` / ``set_cached_auth`` /
    ``invalidate_auth`` / ``invalidate_all`` directly. The refactor
    must not break that contract.
    """
    auth_cache.set_cached_auth("api@example.com", is_authorized=True, rol="reader")
    entry = auth_cache.get_cached_auth("api@example.com", ttl_seconds=300)
    assert entry is not None
    assert entry.is_authorized is True

    auth_cache.invalidate_auth("api@example.com")
    assert auth_cache.get_cached_auth("api@example.com", ttl_seconds=300) is None


def test_module_level_facades_route_to_configured_backend() -> None:
    """Module-level facades dispatch to the configured backend.

    When ``APAP_AUTH_CACHE_BACKEND=redis``, calling
    ``auth_cache.invalidate_auth`` reaches the Redis backend, not the
    in-process one — proving the refactor actually wires the swap.
    """
    from app.core.auth_cache import RedisAuthCache as _Redis

    sentinel = object()
    fake_redis = _Redis(redis_client=sentinel, ttl_seconds=300)
    auth_cache._set_backend_for_testing(fake_redis)

    with pytest.raises(NotImplementedError):
        auth_cache.invalidate_auth("any@example.com")


def test_current_generation_helper_delegates_to_in_process() -> None:
    """``_current_generation`` keeps working for the in-process backend.

    The issue #145 race-window test
    (``test_cached_auth_entry_carries_current_generation``) calls
    ``auth_cache._current_generation`` directly. The refactor preserves
    that module-level helper as a thin facade over the in-process
    backend's per-email counter.
    """
    starting = auth_cache._current_generation("gen@example.com")

    auth_cache.set_cached_auth("gen@example.com", is_authorized=True, rol="key_user")
    auth_cache.invalidate_auth("gen@example.com")

    # After invalidate, the generation MUST have moved (issue #145).
    assert auth_cache._current_generation("gen@example.com") > starting


def test_current_generation_returns_zero_for_non_in_process_backend() -> None:
    """``_current_generation`` returns ``0`` when the backend is not in-process.

    The Redis backend exposes the per-email generation internally (via an
    atomic ``INCR`` on a version key), not as a Python-side counter. The
    module-level facade falls back to ``0`` in that case; tests that need
    the Redis generation pin :class:`InProcessAuthCache` directly.
    """
    sentinel = object()
    fake_redis = RedisAuthCache(redis_client=sentinel, ttl_seconds=300)
    auth_cache._set_backend_for_testing(fake_redis)

    assert auth_cache._current_generation("any@example.com") == 0


# ---------------------------------------------------------------------------
# Scope / docstring documentation
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_module_docstring_documents_worker_local_scope() -> None:
    """The module docstring mentions the per-worker scope.

    Future contributors MUST see the per-worker scope in the docstring
    (not buried in the issue tracker). This is the primary surface an
    operator reads when debugging a stale-verdict incident.
    """
    src = _read("app/core/auth_cache.py")
    # The phrase MUST appear in the module docstring (top of file) so it
    # is the first thing ``help(auth_cache)`` shows.
    assert "per-worker" in src or "worker-local" in src or "per worker" in src, (
        "app/core/auth_cache.py docstring must document the per-worker "
        "scope so operators debugging a stale-verdict incident find it "
        "at the top of the module"
    )


def test_module_docstring_links_runbook() -> None:
    """The module docstring references the multi-worker runbook.

    The runbook is the operator-facing remediation (lowering TTL,
    switching to Redis, etc.); the seam docstring must point at it so
    the reader does not have to grep the docs tree.
    """
    src = _read("app/core/auth_cache.py")
    assert "auth-cache-multi-worker" in src, (
        "app/core/auth_cache.py docstring must reference "
        "docs/runbooks/auth-cache-multi-worker.md so operators find "
        "the multi-worker remediation"
    )


def test_invalidate_auth_docstring_documents_scope() -> None:
    """``invalidate_auth``'s docstring mentions worker-local vs shared.

    The function is the one operators call from
    ``add_authorized_user`` / ``deactivate_authorized_user``; its
    docstring MUST mention the scope so a reader does not assume it is
    cluster-wide when it is not.
    """
    doc = inspect.getdoc(auth_cache.invalidate_auth) or ""
    lowered = doc.lower()
    assert "worker-local" in lowered or "per-worker" in lowered or "shared" in lowered, (
        "auth_cache.invalidate_auth docstring must document its scope "
        "(worker-local vs shared); got: " + doc
    )


def test_redis_backend_docstring_explains_followup() -> None:
    """``RedisAuthCache`` docstring explains it is the structural seam.

    A future reader MUST know that the class is intentionally a stub
    for the follow-up Redis wire-up, not a working Redis client.
    """
    doc = inspect.getdoc(RedisAuthCache) or ""
    lowered = doc.lower()
    assert "follow-up" in lowered or "followup" in lowered or "seam" in lowered, (
        "RedisAuthCache docstring must explain it is the structural "
        "seam for the follow-up Redis wire-up"
    )


# ---------------------------------------------------------------------------
# Settings — config knob
# ---------------------------------------------------------------------------


def test_settings_expose_auth_cache_backend_field() -> None:
    """``Settings.auth_cache_backend`` exists and defaults to ``"in_process"``.

    This is the opt-in knob for the Redis backend; without it the
    factory has no signal to swap.
    """
    from app.core.config import Settings

    settings = Settings()
    assert hasattr(settings, "auth_cache_backend"), (
        "Settings must expose an auth_cache_backend field"
    )
    assert settings.auth_cache_backend == "in_process", (
        f"default auth_cache_backend must be 'in_process', "
        f"got {settings.auth_cache_backend!r}"
    )


# ---------------------------------------------------------------------------
# Sanity: the existing per-email generation semantics survive the refactor.
# This is a single regression test — the comprehensive race-window /
# invalidate-per-email coverage lives in ``test_auth_cache.py``.
# ---------------------------------------------------------------------------


def test_refactor_preserves_set_invalidate_get_contract() -> None:
    """End-to-end: set → invalidate → next get is a miss.

    Pinning the whole contract in one place so a future refactor that
    accidentally drops the generation counter (issue #145) or the
    per-email scoping (existing test) fails loudly here.
    """
    auth_cache.set_cached_auth("e2e@example.com", is_authorized=True, rol="key_user")
    assert auth_cache.get_cached_auth("e2e@example.com", ttl_seconds=300) is not None

    auth_cache.invalidate_auth("e2e@example.com")

    assert auth_cache.get_cached_auth("e2e@example.com", ttl_seconds=300) is None


# Helper: any sentinel value works — the methods raise before touching it.
