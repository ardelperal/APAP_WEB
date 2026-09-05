"""Typed accessor for the classic-password port on ``app.state``.

The Phase 2 lifespan mounts :class:`ClassicPasswordAuthPort` on
``app.state.password_auth``. Routes read it via this thin seam so the
seam can be monkeypatched in tests without coupling to attribute-name
string literals in production code. The accessor fails LOUDLY when the
attribute is missing — a misconfigured lifespan (or a request hitting
the route before the lifespan finishes) surfaces as a clear
:class:`RuntimeError` naming the missing attribute, instead of a generic
:class:`AttributeError` deep inside the request handler.

The :class:`ClassicPasswordAuthPort` is the M2 port
(``app.core.adapters.auth.classic_password_auth_port``). We import it
through the :class:`AuthUsersPort` Protocol interface — the route depends
on the Protocol, not on the concrete InsForge adapter (AGENTS.md §31).
"""
from __future__ import annotations

from fastapi import Request

from app.core.adapters.auth.classic_password_auth_port import (
    ClassicPasswordAuthPort,
)


def get_password_auth_port(request: Request) -> ClassicPasswordAuthPort:
    """Return the request-scoped :class:`ClassicPasswordAuthPort` from ``app.state``.

    Raises :class:`RuntimeError` if ``app.state.password_auth`` is not
    set — the F2.1.5 lifespan is responsible for attaching the port
    before the first request reaches the password routes (gated on
    ``APAP_AUTH_ENABLE_PASSWORD=true``).
    """
    port = getattr(request.app.state, "password_auth", None)
    if port is None:
        raise RuntimeError(
            "app.state.password_auth is not configured — the F2.1.5 lifespan "
            "must attach the ClassicPasswordAuthPort before the first "
            "password request. Set APAP_AUTH_ENABLE_PASSWORD=true to enable "
            "this slice. See openspec/changes/phase2-classic-password/tasks.md::T2.1.5."
        )
    return port  # type: ignore[no-any-return]


__all__ = ["get_password_auth_port"]
