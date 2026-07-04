"""Tests for the per-request authorization TTL cache.

The cache (``app.core.auth_cache``) backs the per-request authorization
revalidation added for issue #143. The cookie signs the IDENTITY (stable,
7 days); the DB is the source of truth for AUTHORIZATION and is
re-validated per request, with a short TTL cache to bound query load.

These are pure unit tests: no Access, no InsForge, no FastAPI. They pin
the cache contract (store / hit-within-ttl / miss-when-expired /
invalidate-one / invalidate-all / thread-safety) independently of the
dependency that consumes it (``require_authorized_user``), whose
integration is pinned in ``test_auth_dependencies.py``.
"""

from __future__ import annotations

import threading

import pytest

from app.core import auth_cache


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Each test starts from an empty process-global cache."""
    auth_cache.invalidate_all()
    yield
    auth_cache.invalidate_all()


def test_get_cached_auth_returns_none_when_empty() -> None:
    """A miss on an empty cache returns None (caller must hit the DB)."""
    assert auth_cache.get_cached_auth("nobody@example.com", ttl_seconds=300) is None


def test_set_cached_auth_stores_entry() -> None:
    """After ``set``, a ``get`` within the TTL returns the stored values."""
    auth_cache.set_cached_auth("a@e.com", is_authorized=True, rol="key_user")

    entry = auth_cache.get_cached_auth("a@e.com", ttl_seconds=300)

    assert entry is not None
    assert entry.is_authorized is True
    assert entry.rol == "key_user"


def test_get_cached_auth_returns_entry_when_within_ttl() -> None:
    """A generous TTL keeps a freshly stored entry visible."""
    auth_cache.set_cached_auth("b@e.com", is_authorized=True, rol="admin")

    entry = auth_cache.get_cached_auth("b@e.com", ttl_seconds=3600)

    assert entry is not None
    assert entry.rol == "admin"


def test_get_cached_auth_returns_none_when_expired() -> None:
    """With ``ttl_seconds=0`` any stored entry is already stale on read.

    ``ttl_seconds=0`` means the freshness window is closed: the entry's
    age (``> 0`` because ``monotonic`` advances) exceeds the TTL, so the
    caller is forced back to the DB. This is the knob product can set to
    disable the cache entirely for immediate (<1s) revocation.
    """
    auth_cache.set_cached_auth("c@e.com", is_authorized=True, rol="reader")

    assert auth_cache.get_cached_auth("c@e.com", ttl_seconds=0) is None


def test_get_cached_auth_returns_none_after_negative_window() -> None:
    """A negative TTL is treated as expired, never as 'infinite fresh'."""
    auth_cache.set_cached_auth("c2@e.com", is_authorized=True, rol="reader")

    assert auth_cache.get_cached_auth("c2@e.com", ttl_seconds=-1) is None


def test_cached_auth_can_store_deauthorized_state() -> None:
    """The cache can memoize a negative verdict too (is_authorized=False).

    Memoizing the deny avoids hammering the DB for a user who was just
    deactivated; the TTL still bounds how long the deny is served, and
    ``invalidate_auth`` clears it immediately on re-activation.
    """
    auth_cache.set_cached_auth("gone@e.com", is_authorized=False, rol=None)

    entry = auth_cache.get_cached_auth("gone@e.com", ttl_seconds=300)

    assert entry is not None
    assert entry.is_authorized is False
    assert entry.rol is None


def test_invalidate_auth_removes_entry() -> None:
    """``invalidate_auth`` drops exactly the named email; next read is a miss."""
    auth_cache.set_cached_auth("keep@e.com", is_authorized=True, rol="key_user")
    auth_cache.set_cached_auth("drop@e.com", is_authorized=True, rol="key_user")

    auth_cache.invalidate_auth("drop@e.com")

    assert auth_cache.get_cached_auth("drop@e.com", ttl_seconds=300) is None
    assert auth_cache.get_cached_auth("keep@e.com", ttl_seconds=300) is not None


def test_invalidate_auth_missing_email_is_noop() -> None:
    """Invalidating an absent email does not raise (idempotent)."""
    auth_cache.invalidate_auth("never-cached@e.com")  # must not raise


def test_invalidate_all_clears_cache() -> None:
    """``invalidate_all`` empties every entry (used on admin reset / deploy)."""
    auth_cache.set_cached_auth("x@e.com", is_authorized=True, rol="key_user")
    auth_cache.set_cached_auth("y@e.com", is_authorized=True, rol="admin")

    auth_cache.invalidate_all()

    assert auth_cache.get_cached_auth("x@e.com", ttl_seconds=300) is None
    assert auth_cache.get_cached_auth("y@e.com", ttl_seconds=300) is None


def test_cache_is_thread_safe_under_concurrent_writes() -> None:
    """Concurrent set/get/invalidate must not corrupt the dict or raise.

    Exercises the ``Lock``: 20 threads each hammer set/get/invalidate on
    distinct keys. Without the lock, ``dict`` mutation during iteration
    could raise ``RuntimeError``; with it, every final read is coherent.
    """
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            email = f"user-{n}@e.com"
            for _ in range(50):
                auth_cache.set_cached_auth(email, is_authorized=True, rol="key_user")
                auth_cache.get_cached_auth(email, ttl_seconds=300)
                auth_cache.invalidate_auth(email)
        except BaseException as exc:  # noqa: BLE001 — surface any thread error
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"thread-safety violation: {errors!r}"
