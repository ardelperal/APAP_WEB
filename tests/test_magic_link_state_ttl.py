"""Unit tests pinning the magic-link state TTL to the token TTL.

Issue #1004 (JD-B-005/JD-A-005): the state-binding TTL must not be an
independent constant that can drift from the magic-link token TTL — a
state outliving its token (or vice versa) breaks the pairing and
either wastes legitimately received links or extends the attack
window. :func:`app.core.local_backend.magic_link._state_ttl_for`
derives the effective TTL from the wired port at binding creation;
these tests pin the COUPLING itself:

- The module fallback constant equals the ``MagicLinkPortImpl``
  default TTL (the value the lifespan wiring uses —
  ``app/core/local_backend/app.py`` constructs ``MagicLinkPortImpl``),
  so the fallback is never wrong for the production adapter.
- The derivation function reads the adapter's ``_ttl`` and falls back
  sanely for ports that do not expose one.

No DB, no lifespan: pure unit coverage of the TTL seam.
"""
from __future__ import annotations

from app.core.adapters.auth_local.magic_link_port import MagicLinkPortImpl
from app.core.local_backend.magic_link import _STATE_TTL_SECONDS, _state_ttl_for

# Coupling under test (issue #1004, JD-B-005): the production adapter's
# default token TTL — the value the lifespan wiring uses, since
# ``MagicLinkPortImpl(executor)`` is constructed without overrides —
# must equal the state-binding fallback constant. If either side
# changes, this test fails and both must be re-aligned deliberately.
_COUPLED_TOKEN_TTL_SECONDS = 1800


class TestStateTtlCoupling:
    """Pin the state TTL to the port's token TTL."""

    def test_fallback_constant_equals_adapter_default_ttl(self) -> None:
        adapter = MagicLinkPortImpl(db=None)  # type: ignore[arg-type]
        assert adapter._ttl == _COUPLED_TOKEN_TTL_SECONDS  # noqa: SLF001
        assert _STATE_TTL_SECONDS == _COUPLED_TOKEN_TTL_SECONDS

    def test_state_ttl_for_reads_the_wired_adapter_ttl(self) -> None:
        adapter = MagicLinkPortImpl(db=None, ttl_seconds=900)  # type: ignore[arg-type]
        assert _state_ttl_for(adapter) == 900

    def test_state_ttl_for_falls_back_when_port_has_no_ttl(self) -> None:
        class _BarePort:
            """Port-shaped object without a ``_ttl`` attribute."""

        assert _state_ttl_for(_BarePort()) == _STATE_TTL_SECONDS

    def test_state_ttl_for_ignores_non_positive_ttl(self) -> None:
        adapter = MagicLinkPortImpl(db=None, ttl_seconds=0)  # type: ignore[arg-type]
        assert _state_ttl_for(adapter) == _STATE_TTL_SECONDS
