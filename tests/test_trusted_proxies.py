"""Trusted-proxy XFF resolution for rate limiting (issue #920, finding A-08).

Covers the ``Settings.trusted_proxies`` contract and the right-to-left
XFF walk in ``app.core.rate_limit``:

- ``trust_xff=True`` with an EMPTY ``trusted_proxies`` list never trusts
  the header (no client IP override) — a forged ``X-Forwarded-For``
  cannot change the rate-limit bucket.
- ``trust_xff=True`` with configured proxy CIDRs walks XFF right-to-left,
  skipping trusted proxy hops; the first untrusted value wins.
- ``trust_xff=False`` keeps the pre-#920 behavior (direct peer IP only).
- A request without a parseable direct peer (unix socket, no peer info)
  never trusts the header.
- Duplicate ``X-Forwarded-For`` header lines are joined before the walk,
  so a proxy appending a second line cannot be bypassed.
- Unparseable XFF entries are skipped during the walk; the direct peer
  wins when no usable untrusted IP is found.
- IPv4-mapped IPv6 peers (``::ffff:a.b.c.d``) match IPv4 CIDRs.

See ``docs/runbooks/trusted-proxies.md`` for the operator contract.
"""

from __future__ import annotations

import logging
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

    def test_trust_xff_without_proxies_emits_one_startup_advisory(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """trust_xff=True with empty trusted_proxies emits exactly ONE
        log_safe advisory, even across repeated constructions (JD-B-004)."""
        import app.core.config as config_module

        monkeypatch.setattr(config_module, "_xff_noop_advisory_emitted", False)
        monkeypatch.setenv("APAP_TRUST_XFF", "true")
        monkeypatch.delenv("APAP_TRUSTED_PROXIES", raising=False)

        with caplog.at_level(logging.INFO, logger="app"):
            Settings(_env_file=None)
            Settings(_env_file=None)

        advisory_events = [
            record
            for record in caplog.records
            if record.name == "app"
            and record._caller_fields.get("event") == "startup.xff_trust_noop"
        ]
        assert len(advisory_events) == 1


# ---------------------------------------------------------------------------
# _extract_identity: right-to-left walk over X-Forwarded-For
# ---------------------------------------------------------------------------


def _request(xff: str | list[str] | None, peer: str | None) -> MagicMock:
    """Build a request stand-in with XFF header line(s) and one direct peer.

    ``xff`` accepts a single header value or a list of duplicate header
    lines (starlette ``headers.getlist`` semantics).
    """
    request = MagicMock()
    if xff is None:
        request.headers.getlist.return_value = []
    elif isinstance(xff, str):
        request.headers.getlist.return_value = [xff]
    else:
        request.headers.getlist.return_value = xff
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

    def test_unparseable_xff_entry_is_skipped_falls_back_to_peer(self) -> None:
        """Garbage entries are skipped, never adopted as the identity; with
        no usable untrusted IP the walk falls back to the direct peer."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(
            _request(xff="not-an-ip", peer="10.0.0.1"), settings
        )

        assert identity.ip == "10.0.0.1"

    def test_unparseable_xff_entry_does_not_shadow_real_hops(self) -> None:
        """A garbage entry mid-chain is skipped; the next untrusted hop to
        its left is still adopted (JD-B-005)."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(
            _request(xff="203.0.113.50, not-an-ip, 10.0.0.1", peer="10.0.0.1"),
            settings,
        )

        assert identity.ip == "203.0.113.50"

    def test_duplicate_xff_header_lines_are_all_considered(self) -> None:
        """A proxy appending a second XFF header line is not bypassed: all
        lines are joined before the walk and the proxy-appended hop wins."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(
            _request(xff=["9.9.9.9", "203.0.113.50"], peer="10.0.0.1"), settings
        )

        assert identity.ip == "203.0.113.50"

    def test_peer_none_with_forged_xff_never_trusts_header(self) -> None:
        """No direct peer (unix socket / no peer info) + trusted_proxies
        configured + forged XFF → peer-based identity (None); the header is
        never consulted without a parseable peer anchor."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(_request(xff="6.6.6.6", peer=None), settings)

        assert identity.ip is None

    def test_unparseable_peer_disables_xff_trust(self) -> None:
        """An unparseable peer (e.g. TestClient's ``testclient``) never
        anchors the XFF walk; identity falls back to the peer itself."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(
            _request(xff="6.6.6.6", peer="testclient"), settings
        )

        assert identity.ip == "testclient"

    def test_ipv4_mapped_ipv6_peer_matches_ipv4_cidr(self) -> None:
        """A peer reported as ::ffff:10.0.0.1 is normalized to 10.0.0.1
        before CIDR matching, so IPv4-mapped sockets do not collapse every
        client into one global bucket."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        settings.trust_xff = True
        settings.trusted_proxies = ["10.0.0.0/8"]

        identity = _extract_identity(
            _request(xff="203.0.113.50", peer="::ffff:10.0.0.1"), settings
        )

        assert identity.ip == "203.0.113.50"

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

    async def test_duplicate_xff_lines_proxy_appended_hop_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A proxy appending the real client as a SECOND X-Forwarded-For
        header line is not bypassed (JD-B-002): all lines are joined before
        the walk, so the proxy-appended hop (203.0.113.50) is the identity
        and the per-request forged first line cannot create fresh buckets."""
        from app.core import config as config_module
        from app.main import app as _app

        base_settings = config_module.get_settings()
        monkeypatch.setattr(
            config_module,
            "get_settings",
            lambda: base_settings.__class__.model_copy(
                base_settings,
                update={"trust_xff": True, "trusted_proxies": ["10.0.0.0/8"]},
            ),
        )
        # Trusted direct peer so the XFF walk is anchored (ASGITransport
        # default peer is the unparseable "testclient").
        transport = httpx.ASGITransport(app=_app, client=("10.0.0.1", 45678))

        statuses: list[int] = []
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as scoped_client:
            for i in range(12):
                response = await scoped_client.get(
                    "/auth/callback",
                    headers=[
                        ("X-Forwarded-For", f"9.9.9.{i}"),
                        ("X-Forwarded-For", "203.0.113.50"),
                    ],
                    follow_redirects=False,
                )
                statuses.append(response.status_code)

        assert 429 in statuses, (
            f"expected 429 from the single proxy-appended bucket, got {statuses}"
        )


# ---------------------------------------------------------------------------
# Trusted-proxy CIDR parse cache
# ---------------------------------------------------------------------------


class TestParseTrustedProxiesCache:
    """CIDR parsing is cached keyed on the tuple of strings (JD-B-007)."""

    def test_same_tuple_returns_cached_networks(self) -> None:
        from app.core.rate_limit import _parse_trusted_proxies

        first = _parse_trusted_proxies(("10.0.0.0/8", "172.16.0.0/12"))
        second = _parse_trusted_proxies(("10.0.0.0/8", "172.16.0.0/12"))

        assert first is second
