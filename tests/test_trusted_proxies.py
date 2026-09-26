"""Trusted-proxy XFF resolution for rate limiting (issue #920, finding A-08).

Covers the ``Settings.trusted_proxies`` contract and the right-to-left
XFF walk in ``app.core.rate_limit``:

- ``trust_xff=True`` with an EMPTY ``trusted_proxies`` list never trusts
  the header (no client IP override) — a forged ``X-Forwarded-For``
  cannot change the rate-limit bucket.
- ``trust_xff=True`` with configured proxy CIDRs walks XFF right-to-left,
  skipping trusted proxy hops; the first untrusted value wins.
- ``trust_xff=False`` keeps the pre-#920 behavior (direct peer IP only).

See ``docs/runbooks/trusted-proxies.md`` for the operator contract.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

# ---------------------------------------------------------------------------
# Settings.trusted_proxies
# ---------------------------------------------------------------------------


class TestTrustedProxiesSettings:
    """``APAP_TRUSTED_PROXIES`` is a JSON list of CIDR strings, default empty."""

    def test_defaults_to_empty_list(self) -> None:
        settings = Settings(_env_file=None)

        assert settings.trusted_proxies == []

    def test_parses_json_list_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APAP_TRUSTED_PROXIES", '["10.0.0.0/8", "172.16.0.0/12"]')

        settings = Settings(_env_file=None)

        assert settings.trusted_proxies == ["10.0.0.0/8", "172.16.0.0/12"]

    def test_invalid_cidr_fails_settings_validation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-CIDR entry must fail fast at startup, not fail open at runtime."""
        monkeypatch.setenv("APAP_TRUSTED_PROXIES", '["not-a-cidr"]')

        with pytest.raises(ValidationError):
            Settings(_env_file=None)


# ---------------------------------------------------------------------------
# _extract_identity: right-to-left walk over X-Forwarded-For
# ---------------------------------------------------------------------------


def _request(xff: str | None, peer: str | None) -> MagicMock:
    """Build a request stand-in with one XFF header and one direct peer."""
    request = MagicMock()
    request.headers.get.return_value = xff
    if peer is None:
        request.client = None
    else:
        request.client.host = peer
    return request


class TestExtractIdentityTrustedProxies:
    """IP resolution semantics after #920.

    The header is only trusted when the direct connection peer and the
    proxy hops between it and the client are all configured in
    ``Settings.trusted_proxies``.
    """

    def test_trust_xff_true_empty_list_ignores_forged_xff(self) -> None:
        """trust_xff=True with NO trusted_proxies means no client IP override."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = []

        identity = _extract_identity(_request(xff="6.6.6.6", peer="10.0.0.1"), settings)

        assert identity.ip == "10.0.0.1"

    def test_trusted_proxy_hops_are_skipped_right_to_left(self) -> None:
        """Both proxy hops trusted → claimed client (leftmost) is used."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(
            _request(xff="203.0.113.50, 10.0.0.2, 10.0.0.1", peer="10.0.0.1"), settings
        )

        assert identity.ip == "203.0.113.50"

    def test_forged_xff_from_untrusted_peer_is_ignored(self) -> None:
        """The direct peer is not a trusted proxy → forged XFF is never reached."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(
            _request(xff="1.2.3.4", peer="8.8.8.8"), settings
        )

        assert identity.ip == "8.8.8.8"

    def test_unparseable_xff_entry_is_terminal(self) -> None:
        """Garbage in the chain stops the walk (never skips a real hop)."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(
            _request(xff="not-an-ip", peer="10.0.0.1"), settings
        )

        assert identity.ip == "not-an-ip"

    def test_all_hops_trusted_falls_back_to_peer(self) -> None:
        """Every candidate trusted → fail closed to the direct peer."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(
            _request(xff="10.0.0.5, 10.0.0.1", peer="10.0.0.1"), settings
        )

        assert identity.ip == "10.0.0.1"

    def test_trust_xff_false_keeps_peer(self) -> None:
        """trust_xff=False → pre-#920 behavior, header ignored."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = False
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(_request(xff="6.6.6.6", peer="10.0.0.1"), settings)

        assert identity.ip == "10.0.0.1"

    def test_no_peer_and_no_xff_yields_none(self) -> None:
        """No peer connection and no header → None (never crash)."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(_request(xff=None, peer=None), settings)

        assert identity.ip is None


# ---------------------------------------------------------------------------
# Middleware-level acceptance: forged XFF cannot evade the OAuth bucket
# ---------------------------------------------------------------------------


class TestForgedXffCannotEvadeLimit:
    """Acceptance #920: forged XFF must not change the rate-limit bucket."""

    @pytest.fixture(autouse=True)
    def _web_mode(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        """Activate the rate-limit middleware (see test_rate_limit_middleware.py)."""
        from app.core.config import get_settings

        monkeypatch.setenv("APAP_MODE", "web")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def test_forged_xff_does_not_evade_oauth_bucket(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """trust_xff=True + EMPTY trusted_proxies → distinct forged XFFs all
        land in the same bucket, so the OAuth limit trips. Before #920 each
        forged value created a fresh bucket and the limit was never hit."""
        from app.core import config as config_module

        base_settings = config_module.get_settings()
        monkeypatch.setattr(
            config_module,
            "get_settings",
            lambda: base_settings.__class__.model_copy(
                base_settings, update={"trust_xff": True}
            ),
        )

        statuses: list[int] = []
        for i in range(12):
            response = await client.get(
                "/auth/callback",
                headers={"X-Forwarded-For": f"9.9.9.{i}"},
                follow_redirects=False,
            )
            statuses.append(response.status_code)

        assert 429 in statuses, f"expected 429 from a single shared bucket, got {statuses}"
