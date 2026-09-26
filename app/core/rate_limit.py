"""Rate-limit backend: sliding-window in-process store and identity resolution.

Issue #286. Provides:
- ``RetryInfo`` — result of a rate-limit check.
- ``RateLimitBackend`` — Protocol defining the ``hit`` interface.
- ``InProcessRateLimitBackend`` — worker-local sliding-window implementation.
- ``Identity`` — named tuple of ``(ip, user_id)`` resolved from a request.
- ``_extract_identity`` — helper that resolves IP and user_id per bucket rules.
"""

from __future__ import annotations

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


def _parse_trusted_proxies(cidrs: list[str]) -> list[_TrustedNetwork]:
    """Parse ``Settings.trusted_proxies`` CIDR strings into networks."""
    return [ipaddress.ip_network(cidr, strict=False) for cidr in cidrs]


def _is_trusted(ip_str: str, networks: Sequence[_TrustedNetwork]) -> bool:
    """Return True only when ``ip_str`` parses and falls in a trusted network.

    An unparseable entry (e.g. garbage injected into X-Forwarded-For) is
    treated as untrusted, so it terminates the right-to-left walk instead
    of letting a forged hop past it.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in network for network in networks)


def _xff_entries(xff: str) -> list[str]:
    """Split ``X-Forwarded-For`` into stripped, non-empty entries."""
    return [entry.strip() for entry in xff.split(",") if entry.strip()]


def _client_ip_from_xff(
    xff: str, peer: str | None, trusted_networks: Sequence[_TrustedNetwork]
) -> str | None:
    """Walk X-Forwarded-For right-to-left; the first untrusted value wins.

    Candidates are the XFF entries (leftmost = claimed original client)
    followed by the direct peer. Only trusted-proxy hops are skipped, so a
    forged entry appended by a client behind an untrusted peer can never be
    reached. When every candidate is trusted, the direct peer wins
    (fail-closed). See docs/runbooks/trusted-proxies.md.
    """
    candidates = _xff_entries(xff) + ([peer] if peer else [])
    for candidate in reversed(candidates):
        if not _is_trusted(candidate, trusted_networks):
            return candidate
    return peer


def _resolve_client_ip(request: Request, settings: Settings) -> str | None:
    """Resolve the client IP for rate-limit bucketing (issue #920).

    ``trust_xff=True`` overrides the client IP ONLY when
    ``settings.trusted_proxies`` is non-empty; with the default empty list
    the header is NEVER trusted (no client IP override) and the direct
    peer is used. See docs/runbooks/trusted-proxies.md.
    """
    peer = request.client.host if request.client else None
    if not settings.trust_xff or not settings.trusted_proxies:
        return peer
    return _client_ip_from_xff(
        request.headers.get("x-forwarded-for") or "",
        peer,
        _parse_trusted_proxies(settings.trusted_proxies),
    )


def _extract_identity(request: Request, settings: Settings) -> Identity:
    """Resolve per-request IP and user_id for rate-limit bucket keying (D4, REQ-6).

    IP resolution order:
    1. When ``settings.trust_xff`` is True AND ``settings.trusted_proxies``
       is configured, ``X-Forwarded-For`` is walked right-to-left and the
       first value outside the trusted proxy networks is the client IP.
    2. ``request.client.host`` otherwise — including when ``trust_xff`` is
       True but ``trusted_proxies`` is empty (no header trust; issue #920,
       see docs/runbooks/trusted-proxies.md).

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
