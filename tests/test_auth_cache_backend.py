"""Tests for the in-process auth-cache backend (issues #262 and #287).

Issue #143 introduced an in-process TTL cache backing
``require_authorized_user``. Issue #262 documented its per-worker scope and
added a Redis structural seam. Issue #287 removes that unusable seam because
the deployed Coolify application runs one Uvicorn worker and Redis was never
wired.

These tests pin the resolved contract:

- ``AuthCacheBackend`` remains the internal structural contract used for test
  injection.
- ``InProcessAuthCache`` is the only runtime backend.
- Unsupported configuration, including ``redis``, is rejected while settings
  load instead of failing on a live request.
- ``app.core.auth_cache`` keeps its public API (``get_cached_auth``,
  ``set_cached_auth``, ``invalidate_auth``, ``invalidate_all``,
  ``_current_generation``) so callers do not change.
- The worker-local scope and operator runbook remain explicit.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core import auth_cache
from app.core.auth_cache import AuthCacheBackend, InProcessAuthCache

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeBackend:
    def __init__(self) -> None:
        self.invalidated: list[str] = []

    def get(self, email: str, ttl_seconds: int) -> None:
        return None

    def set(self, email: str, *, is_authorized: bool, rol: str | None) -> None:
        return None

    def invalidate(self, email: str) -> None:
        self.invalidated.append(email)

    def invalidate_all(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    """Reset the process-global auth-cache backend between tests."""
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
# Removed Redis seam
# ---------------------------------------------------------------------------


def test_redis_backend_class_is_removed() -> None:
    """The unusable Redis backend is no longer part of the runtime module."""
    assert "RedisAuthCache" not in vars(auth_cache)


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


@pytest.mark.parametrize("backend_name", ["redis", "this-is-not-a-backend"])
def test_settings_reject_unsupported_auth_cache_backend(
    monkeypatch: pytest.MonkeyPatch,
    backend_name: str,
) -> None:
    """Unsupported backends fail settings validation instead of reaching a request."""
    from app.core.config import Settings

    monkeypatch.setenv("APAP_AUTH_CACHE_BACKEND", backend_name)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("auth_cache_backend",)
    assert error["input"] == backend_name


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


def test_module_level_facades_route_to_injected_backend() -> None:
    """The internal test seam still dispatches facades through the Protocol.

    Issue #278: invalidate_auth invalidates all case variants so that no
    stale entry survives regardless of which casing the service layer stored
    it under. The backend receives invalidation calls for every variant.
    """
    fake_backend = _FakeBackend()
    auth_cache._set_backend_for_testing(fake_backend)

    auth_cache.invalidate_auth("any@example.com")

    # All case variants (including the canonical form) must be invalidated.
    assert set(fake_backend.invalidated) == auth_cache._case_variants("any@example.com")


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


def test_current_generation_returns_zero_for_injected_test_backend() -> None:
    """Non-in-process test backends expose no Python generation counter."""
    auth_cache._set_backend_for_testing(_FakeBackend())

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

    The runbook is the operator-facing remediation for enforcing one
    worker or lowering TTL to zero; the module docstring must point at
    it so the reader does not have to grep the docs tree.
    """
    src = _read("app/core/auth_cache.py")
    assert "auth-cache-multi-worker" in src, (
        "app/core/auth_cache.py docstring must reference "
        "docs/runbooks/auth-cache-multi-worker.md so operators find "
        "the multi-worker remediation"
    )


def test_invalidate_auth_docstring_documents_scope() -> None:
    """``invalidate_auth`` documents that invalidation is worker-local."""
    doc = inspect.getdoc(auth_cache.invalidate_auth) or ""
    lowered = doc.lower()
    assert "worker-local" in lowered or "per-worker" in lowered, (
        "auth_cache.invalidate_auth docstring must document its worker-local scope; got: "
        + doc
    )


def test_module_docstring_does_not_offer_redis_backend() -> None:
    """Operator-facing module documentation must not advertise removed Redis support."""
    doc = inspect.getdoc(auth_cache) or ""

    assert "redis" not in doc.lower()


# ---------------------------------------------------------------------------
# Settings — config knob
# ---------------------------------------------------------------------------


def test_settings_expose_auth_cache_backend_field() -> None:
    """``Settings.auth_cache_backend`` defaults to the sole supported backend.

    The field remains as an explicit compatibility guard so stale
    ``APAP_AUTH_CACHE_BACKEND`` values fail validation instead of being
    ignored by ``extra=ignore``.
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
