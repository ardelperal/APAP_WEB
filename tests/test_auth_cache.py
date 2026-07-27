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


# ---------------------------------------------------------------------------
# Issue #145: race condition write-after-invalidate (CAS-style generation
# counter). The window is bounded by HTTP round-trip + TTL; the generation
# guard makes the post-invalidate generation unreachable to any reader that
# captured the pre-invalidate generation, and stamps every entry with the
# generation it was written under so an audit can see stale data.
# ---------------------------------------------------------------------------


def test_cached_auth_entry_carries_current_generation() -> None:
    """``CachedEntry.generation`` records the generation the entry was written under.

    Issue #145 — every entry MUST carry its generation so an audit can detect
    a verdict that pre-dates an invalidation. Without this field, the cache
    is opaque about freshness; with it, the cache becomes a documented seam.
    """
    starting_gen = auth_cache._current_generation("u@e.com")

    auth_cache.set_cached_auth("u@e.com", is_authorized=True, rol="key_user")

    entry = auth_cache.get_cached_auth("u@e.com", ttl_seconds=300)

    assert entry is not None
    # The entry's stored generation must equal the email's current generation
    # at write time — not zero (after invalidation), not a fresh generation,
    # but the one that was live when the caller called ``set_cached_auth``.
    assert entry.generation == starting_gen == auth_cache._current_generation("u@e.com")


def test_get_cached_auth_returns_none_after_invalidate_due_to_generation_bump() -> None:
    """``invalidate_auth`` bumps the email's generation, so the next read sees a miss.

    Issue #145 — the write-after-invalidate race window. After T2's
    invalidation, the email's generation moves forward and the
    pre-invalidate entry is unreachable to any subsequent read. A later
    ``set_cached_auth`` writes under the NEW generation (visible in the
    entry's ``generation`` field); reads that follow the invalidation see
    only entries written AFTER it.

    Per-email scoping: invalidating ``u@e.com`` MUST NOT touch a sibling
    email's cached verdict — that's the regression guard for the existing
    ``test_invalidate_auth_removes_entry`` contract, pinned here so the
    CAS-style fix doesn't accidentally make every deactivate a global
    cache bust.
    """
    auth_cache.set_cached_auth("u@e.com", is_authorized=True, rol="key_user")
    auth_cache.set_cached_auth("sibling@e.com", is_authorized=True, rol="admin")
    pre_invalidate_gen = auth_cache._current_generation("u@e.com")
    assert auth_cache.get_cached_auth("u@e.com", ttl_seconds=300) is not None

    auth_cache.invalidate_auth("u@e.com")

    # The deactivated email's generation MUST have moved; otherwise the
    # bump is a silent no-op and the race stays open.
    assert auth_cache._current_generation("u@e.com") > pre_invalidate_gen

    # Direct check: get returns None for the invalidated email.
    assert auth_cache.get_cached_auth("u@e.com", ttl_seconds=300) is None

    # Regression guard: the sibling email's verdict is unaffected.
    sibling = auth_cache.get_cached_auth("sibling@e.com", ttl_seconds=300)
    assert sibling is not None
    assert sibling.rol == "admin"
    assert auth_cache._current_generation("sibling@e.com") == 0

    # And: a subsequent set for the invalidated email writes under the
    # post-invalidate generation, becoming visible to the next read.
    auth_cache.set_cached_auth("u@e.com", is_authorized=True, rol="key_user")
    entry = auth_cache.get_cached_auth("u@e.com", ttl_seconds=300)
    assert entry is not None
    assert entry.generation == auth_cache._current_generation("u@e.com") > pre_invalidate_gen


def test_invalidate_all_bumps_generation_and_obsoletes_every_entry() -> None:
    """``invalidate_all`` invalidates every email; all reads are misses.

    Issue #145 — admin reset tooling relies on this: after
    ``invalidate_all()``, every cached email must miss the cache, forcing
    the next request through the DB rather than serving a verdict written
    under a previous generation. After the clear, every email is back at
    generation 0 (the per-email tracking dict is wiped), so a subsequent
    ``set_cached_auth`` writes under the fresh generation and is visible
    to the next ``get``.
    """
    auth_cache.set_cached_auth("a@e.com", is_authorized=True, rol="key_user")
    auth_cache.set_cached_auth("b@e.com", is_authorized=False, rol=None)
    assert auth_cache._current_generation("a@e.com") == 0
    assert auth_cache._current_generation("b@e.com") == 0

    auth_cache.invalidate_all()

    assert auth_cache.get_cached_auth("a@e.com", ttl_seconds=300) is None
    assert auth_cache.get_cached_auth("b@e.com", ttl_seconds=300) is None

    # Subsequent sets start fresh at generation 0 and are immediately
    # visible — the cache is a clean slate, not a tombstone.
    auth_cache.set_cached_auth("a@e.com", is_authorized=True, rol="key_user")
    entry = auth_cache.get_cached_auth("a@e.com", ttl_seconds=300)
    assert entry is not None
    assert entry.generation == 0


# --- Issue #278: case-folding ghost users -----------------------------------


def test_invalidate_auth_cascades_to_case_variants() -> None:
    """Invalidating one case form invalidates all case variants.

    When the admin deactivates a user whose email was stored in mixed case,
    the cache must be invalidated for the canonical form AND all other
    casings of the same local-part + domain, otherwise a cache lookup using
    a different casing (e.g. after OAuth normalizes to lowercase) would hit a
    stale cached verdict and skip re-validation (issue #278).
    """
    # Prime cache entries at several case variants of the same email
    auth_cache.set_cached_auth("Maria.Lopez@Example.COM", is_authorized=True, rol="key_user")
    auth_cache.set_cached_auth("maria.lopez@example.com", is_authorized=True, rol="key_user")
    auth_cache.set_cached_auth("MARIA.LOPEZ@EXAMPLE.COM", is_authorized=True, rol="key_user")
    auth_cache.set_cached_auth("maria.lopez@Example.COM", is_authorized=True, rol="key_user")

    # Invalidate using one variant
    auth_cache.invalidate_auth("maria.lopez@example.com")

    # All variants — including the one NOT invalidated directly — must miss
    assert auth_cache.get_cached_auth("Maria.Lopez@Example.COM", ttl_seconds=300) is None
    assert auth_cache.get_cached_auth("maria.lopez@example.com", ttl_seconds=300) is None
    assert auth_cache.get_cached_auth("MARIA.LOPEZ@EXAMPLE.COM", ttl_seconds=300) is None
    assert auth_cache.get_cached_auth("maria.lopez@Example.COM", ttl_seconds=300) is None
