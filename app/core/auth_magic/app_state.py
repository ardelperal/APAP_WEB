"""Typed accessors for the magic-link ports on ``app.state``.

The magic-link slice owns three ``app.state`` attributes, all set by the
F3 lifespan startup (the verify-fallback-ready local backend owns its
own lifespan — F2 ships the routes and DI seam only; see
``openspec/changes/m1-magic-link-self-host/tasks.md::T2.3``):

* ``app.state.magic_link_port`` — :class:`PostgresMagicLinkAdapter`
  implementing :class:`~app.core.ports.magic_link_port.MagicLinkPort`.
* ``app.state.mail_transport`` — :class:`ConsoleMailTransport` (or the
  M1.1 :class:`SMTPMailTransport`) implementing
  :class:`~app.core.ports.mail_transport_port.MailTransport`.
* ``app.state.auth_port`` — :class:`AuthUsersPort` implementation the
  routes use to authorise the email before persisting a magic-link
  request. F3 reuses the same InsForge-backed adapter the OAuth
  callback uses.

The accessors fail LOUDLY when an attribute is missing. A misconfigured
lifespan (or a request hitting the route before the lifespan finishes)
surfaces as a clear :class:`RuntimeError` naming the missing attribute
and pointing the operator at ``tasks.md::T2.3`` instead of a generic
``AttributeError`` deep inside a request handler.

The accessors are tiny on purpose — a thin seam over
``request.app.state`` so tests can ``monkeypatch.setattr`` the port at
the request layer without coupling to attribute-name string literals in
production code.
"""
from __future__ import annotations

import os

from fastapi import Request

from app.core.ports.auth_port import AuthUsersPort
from app.core.ports.magic_link_port import MagicLinkPort
from app.core.ports.mail_transport_port import MailTransport

_ATTR_NAMES: tuple[str, ...] = ("magic_link_port", "mail_transport", "auth_port")
"""``app.state`` attribute names owned by the magic-link slice (F3 lifespan)."""


def get_magic_link_port(request: Request) -> MagicLinkPort:
    """Return the request-scoped :class:`MagicLinkPort` from ``app.state``.

    Raises :class:`RuntimeError` if ``app.state.magic_link_port`` is not
    set — the F3 lifespan is responsible for attaching the adapter
    before the first request reaches the magic-link routes.
    """
    port = getattr(request.app.state, "magic_link_port", None)
    if port is None:
        raise RuntimeError(
            "app.state.magic_link_port is not configured — the F3 lifespan "
            "must attach the MagicLinkPort before the first request. "
            "See openspec/changes/m1-magic-link-self-host/tasks.md::T2.3."
        )
    return port  # type: ignore[no-any-return]


def get_mail_transport(request: Request) -> MailTransport:
    """Return the request-scoped :class:`MailTransport` from ``app.state``.

    Raises :class:`RuntimeError` if ``app.state.mail_transport`` is not
    set. F2's routes do not currently call the transport directly
    (the :class:`PostgresMagicLinkAdapter` owns the send), but the
    accessor is exposed for F3's lifespan validation and any future
    route that needs to send ad-hoc emails.
    """
    transport = getattr(request.app.state, "mail_transport", None)
    if transport is None:
        raise RuntimeError(
            "app.state.mail_transport is not configured — the F3 lifespan "
            "must attach the MailTransport before the first request. "
            "See openspec/changes/m1-magic-link-self-host/tasks.md::T2.3."
        )
    return transport  # type: ignore[no-any-return]


def get_auth_port(request: Request) -> AuthUsersPort:
    """Return the request-scoped :class:`AuthUsersPort` from ``app.state``.

    When the env var ``APAP_E2E_STUB_AUTH=true`` is set, returns the
    F3-round-trip :class:`StubAuthPort` (in-memory) seeded with the
    configured ``e2e_auth_default_email``. Used by
    ``tests/e2e/test_magic_link_e2e.py`` to exercise the full magic-link
    round-trip without an InsForge backend.

    Raises :class:`RuntimeError` if ``app.state.auth_port`` is not set.
    The F3 lifespan attaches the same :class:`AuthUsersPort` adapter the
    OAuth callback uses (currently
    :class:`app.core.adapters.insforge.auth_insforge_adapter.InsForgeAuthUsersAdapter`).
    """
    if os.environ.get("APAP_E2E_STUB_AUTH") == "true":
        # M3.1 E2E fix: re-use the F3-round-trip StubAuthPort in
        # app/core/local_backend/stub_auth_port.py. Pre-seeds the
        # configured test email so the magic-link form can complete a
        # round-trip without an InsForge backend.
        from app.core.config import get_settings  # noqa: PLC0415
        from app.core.local_backend.stub_auth_port import StubAuthPort
        from app.core.roles import Rol
        stub = StubAuthPort()
        settings = get_settings()
        seed_email = settings.initial_admin_email or "ardelperal@gmail.com"
        stub.add(seed_email, rol=Rol.DEVELOPER)
        return stub
    port = getattr(request.app.state, "auth_port", None)
    if port is None:
        raise RuntimeError(
            "app.state.auth_port is not configured — the F3 lifespan must "
            "attach the AuthUsersPort before the first magic-link request. "
            "See openspec/changes/m1-magic-link-self-host/tasks.md::T2.3."
        )
    return port  # type: ignore[no-any-return]


__all__ = [
    "get_auth_port",
    "get_mail_transport",
    "get_magic_link_port",
]
