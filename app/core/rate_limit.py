"""Rate-limit backend: sliding-window in-process store and identity resolution.

Issue #286. Provides:
- ``RetryInfo`` — result of a rate-limit check.
- ``RateLimitBackend`` — Protocol defining the ``hit`` interface.
- ``InProcessRateLimitBackend`` — worker-local sliding-window implementation.
- ``Identity`` — named tuple of ``(ip, user_id)`` resolved from a request.
- ``_extract_identity`` — helper that resolves IP and user_id per bucket rules.
"""

from __future__ import annotations

import functools
import ipaddress
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

from app.core.config import Settings
from app.core.session import read_session_payload

# --- Public data shapes ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetryInfo:
    """Information returned on every rate-limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: float  # epoch seconds at which the oldest ts exits window
    retry_after: int | None  # seconds; only set when ``allowed`` is False


class Identity:
    """Resolved identity for rate-limit bucket keying."""

    __slots__ = ("ip", "user_id")

    def __init__(self, ip: str | None, user_id: str | None) -> None:
        self.ip = ip
        self.user_id = user_id

    def __repr__(self) -> str:
        return f"Identity(ip={self.ip!r}, user_id={self.user_id!r})"


# --- Protocol ----------------------------------------------------------------


class RateLimitBackend(Protocol):
    """Minimal rate-limit backend contract (REQ-3, D2)."""

    def hit(
        self,
        scope: str,
        identity: str,
        *,
        limit: int,
        now: float,
        window_seconds: int = 60,
    ) -> tuple[bool, RetryInfo]:
        """Atomically check-and-record one request.

        Returns ``(True, RetryInfo)`` when the request is allowed and the
        bucket state after recording. Returns ``(False, RetryInfo)`` when
        the bucket is exhausted.
        """
        ...

    def reset(self) -> None:
        """Clear all bucket state (for test isolation)."""
        ...


# --- In-process implementation -----------------------------------------------


class InProcessRateLimitBackend:
    """Worker-local sliding-window rate-limit store (REQ-3, D2-D3).

    Keyed by ``(scope, identity)`` → ``deque[monotonic_ts]``. Thread-safe
    via a single ``threading.Lock``. State is per-worker (same scope as the
    auth cache per §29 / #262).
    """

    # Maximum number of distinct keys before oldest are evicted.
    MAX_KEYS = 10_000

    __slots__ = ("_lock", "_timestamps", "_key_order")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Map (scope, identity) → deque of timestamps
        self._timestamps: dict[tuple[str, str], list[float]] = {}
        # LRU eviction order — oldest seen keys evicted first
        self._key_order: list[tuple[str, str]] = []

    def reset(self) -> None:
        """Clear all bucket state (for test isolation)."""
        with self._lock:
            self._timestamps.clear()
            self._key_order.clear()

    def hit(
        self,
        scope: str,
        identity: str,
        *,
        limit: int,
        now: float,
        window_seconds: int = 60,
    ) -> tuple[bool, RetryInfo]:
        key = (scope, identity)
        cutoff = now - window_seconds

        with self._lock:
            if key in self._timestamps:
                times = self._timestamps[key]
            else:
                # New key — enforce MAX_KEYS by evicting oldest if needed
                if len(self._timestamps) >= self.MAX_KEYS:
                    oldest_key = self._key_order.pop(0)
                    self._timestamps.pop(oldest_key, None)
                times = []
                self._timestamps[key] = times
                self._key_order.append(key)

            # Evict timestamps that have left the sliding window
            while times and times[0] <= cutoff:
                times.pop(0)

            if len(times) < limit:
                # Allowed
                times.append(now)
                remaining = limit - len(times)
                reset_at = (times[0] + window_seconds) if times else now + window_seconds
                return (
                    True,
                    RetryInfo(
                        allowed=True,
                        limit=limit,
                        remaining=remaining,
                        reset_at=reset_at,
                        retry_after=None,
                    ),
                )
            # Rejected — window is full
            reset_at = times[0] + window_seconds
            retry_after = max(int(reset_at - now), 1)
            return (
                False,
                RetryInfo(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    reset_at=reset_at,
                    retry_after=retry_after,
                ),
            )


# --- Identity resolution -----------------------------------------------------

#: A trusted proxy network parsed from ``Settings.trusted_proxies``.
_TrustedNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

#: A parsed IP address (peer or X-Forwarded-For candidate).
_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


@functools.lru_cache(maxsize=8)
def _parse_trusted_proxies(cidrs: tuple[str, ...]) -> tuple[_TrustedNetwork, ...]:
    """Parse ``Settings.trusted_proxies`` CIDR strings into networks.

    Cached on the tuple of strings (JD-B-007): the same configured list is
    re-parsed on every request otherwise. ``maxsize=8`` bounds memory for
    test configurations that mutate settings.
    """
    return tuple(ipaddress.ip_network(cidr, strict=False) for cidr in cidrs)


def _parse_ip(value: str) -> _IPAddress | None:
    """Parse an IP address string; return None when unparseable."""
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _matchable_address(addr: _IPAddress) -> _IPAddress:
    """Normalize an IPv4-mapped IPv6 address (``::ffff:a.b.c.d``) to IPv4.

    Without normalization such peers never match IPv4 CIDRs, so every
    client would collapse into one global rate-limit bucket (JD-B-003).
    """
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _is_trusted_address(
    addr: _IPAddress, networks: Sequence[_TrustedNetwork]
) -> bool:
    """Return True when the (normalized) address falls in a trusted network."""
    addr = _matchable_address(addr)
    return any(addr in network for network in networks)


def _xff_entries(xff: str) -> list[str]:
    """Split ``X-Forwarded-For`` into stripped, non-empty entries."""
    return [entry.strip() for entry in xff.split(",") if entry.strip()]


def _client_ip_from_xff(
    xff: str, peer: str | None, trusted_networks: Sequence[_TrustedNetwork]
) -> str | None:
    """Walk X-Forwarded-For right-to-left; the first untrusted IP wins.

    Candidates are the XFF entries (leftmost = claimed original client)
    followed by the direct peer. Trusted-proxy hops are skipped and
    unparseable entries (garbage injected into the header) are skipped
    too — garbage is never adopted as the identity (JD-B-005). When no
    usable untrusted IP is found, the direct peer wins (fail-closed).
    See docs/runbooks/trusted-proxies.md.
    """
    candidates = _xff_entries(xff) + ([peer] if peer else [])
    for candidate in reversed(candidates):
        addr = _parse_ip(candidate)
        if addr is None:
            continue
        if _is_trusted_address(addr, trusted_networks):
            continue
        return candidate
    return peer


def _peer_host(request: Request) -> str | None:
    """Return the direct connection peer host, or None without peer info."""
    return request.client.host if request.client else None


def _is_xff_trust_active(settings: Settings) -> bool:
    """XFF is trusted only with trust_xff=True AND a non-empty CIDR list."""
    return settings.trust_xff and bool(settings.trusted_proxies)


def _join_xff_lines(request: Request) -> str:
    """Join every ``X-Forwarded-For`` header line into one walkable value.

    ``headers.get`` would return only the first line, letting a proxy that
    appends a second line be bypassed (JD-B-002).
    """
    return ",".join(filter(None, request.headers.getlist("x-forwarded-for")))


def _resolve_client_ip(request: Request, settings: Settings) -> str | None:
    """Resolve the client IP for rate-limit bucketing (issue #920).

    ``trust_xff=True`` overrides the client IP ONLY when
    ``settings.trusted_proxies`` is non-empty AND the direct peer is a
    parseable IP address; without a parseable peer anchor (unix socket,
    no peer info, or an unparseable peer) the header is NEVER trusted and
    the direct peer is used. Duplicate ``X-Forwarded-For`` header lines
    are joined before the walk so a proxy appending a second line cannot
    be bypassed (JD-B-002). See docs/runbooks/trusted-proxies.md.
    """
    peer = _peer_host(request)
    if (
        peer is None
        or not _is_xff_trust_active(settings)
        or _parse_ip(peer) is None
    ):
        # No parseable peer → no trusted anchor for the walk; the header
        # is never honoured (JD fix W1).
        return peer
    return _client_ip_from_xff(
        _join_xff_lines(request),
        peer,
        _parse_trusted_proxies(tuple(settings.trusted_proxies)),
    )


def _extract_identity(request: Request, settings: Settings) -> Identity:
    """Resolve per-request IP and user_id for rate-limit bucket keying (D4, REQ-6).

    IP resolution order:
    1. When ``settings.trust_xff`` is True AND ``settings.trusted_proxies``
       is configured AND the direct peer is a parseable IP address,
       ``X-Forwarded-For`` is walked right-to-left and the first value
       outside the trusted proxy networks is the client IP. Unparseable
       entries are skipped; the direct peer wins when no usable untrusted
       IP is found.
    2. ``request.client.host`` otherwise — including when ``trust_xff`` is
       True but ``trusted_proxies`` is empty (no header trust; issue #920,
       see docs/runbooks/trusted-proxies.md), and when the request has no
       parseable peer (the header is never trusted without an anchor).

    user_id: extracted from the signed session cookie when present and valid.
    Returns an empty user_id (None) when no session or invalid.

    IP is NEVER logged on rejection (REQ-5, D6). Callers must use
    ``log_safe("ratelimit.rejected", path=..., reason=..., scope=...,
    user_id=...)`` without passing IP.
    """
    # IP resolution (trusted-proxy aware; issue #920)
    ip: str | None = _resolve_client_ip(request, settings)

    # User ID from session
    user_id: str | None = None
    session = read_session_payload(request, secret=settings.session_secret)
    if session:
        user_id = session.get("user_id")

    return Identity(ip=ip, user_id=user_id)
