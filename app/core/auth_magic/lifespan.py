"""Wire magic-link state into the FastAPI app for production deploys (M3, R2).

Called from :func:`app.main.lifespan` AFTER the InsForge client is
attached to ``app.state.insforge_client`` and BEFORE the bootstrap
``try`` block. When ``APAP_AUTH_ENABLE_MAGIC_LINK=true`` and
``APAP_SMTP_HOST`` is set, the lifespan attaches the three ports
(``magic_link_port``, ``mail_transport``, ``auth_port``) needed by the
magic router mounted via :func:`app.core.auth_flow.register_auth_flow_routes`.

The wiring is opt-in: when the flag is unset OR SMTP is unset, the
lifespan skips the wiring and the magic router's no-op branches
(from F2) handle the request. This keeps the OAuth path as the active
channel when the operator has not configured magic-link.

Failures are logged but never raised — the OAuth path must keep
working even if the magic-link wiring fails (e.g. local Postgres
unreachable).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.core.auth_magic.get_mail_transport import get_mail_transport
from app.core.auth_magic.postgres_adapter import PostgresMagicLinkAdapter
from app.core.config import Settings

_logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _magic_link_enabled() -> bool:
    """Return True iff ``APAP_AUTH_ENABLE_MAGIC_LINK`` is truthy."""
    return os.environ.get("APAP_AUTH_ENABLE_MAGIC_LINK", "").strip().lower() in _TRUTHY


def _smtp_configured() -> bool:
    """Return True iff ``APAP_SMTP_HOST`` is set and non-empty."""
    return bool(os.environ.get("APAP_SMTP_HOST"))


async def wire_magic_link_to_app_state(
    application: Any, settings: Settings
) -> None:
    """Attach the three magic-link ports to ``app.state``.

    When ``APAP_AUTH_ENABLE_MAGIC_LINK`` is unset, log an informational
    line and return. When ``APAP_AUTH_ENABLE_MAGIC_LINK=true`` but
    ``APAP_SMTP_HOST`` is unset, log a warning and return — the OAuth
    path remains active and the magic-link channel is disabled.

    On the happy path, attach ``magic_link_port``, ``mail_transport``,
    and ``auth_port`` to ``application.state``. ``auth_port`` reuses the
    existing InsForge-backed adapter when ``insforge_client`` is on
    ``app.state``; otherwise it falls back to the local-backend stub so
    a degraded boot does not abort the lifespan.

    All exceptions are caught and logged at ERROR — a wiring failure
    must never abort the lifespan, because the OAuth path should still
    serve the operator.

    The ``settings`` argument is accepted for symmetry with the
    :func:`app.main.lifespan` signature (operators can inject a custom
    Settings via tests), even though the wiring itself uses
    ``os.environ`` for the DSN/schema/SMTP values (the pydantic
    Settings does not declare these fields today and adding them is a
    separate work unit).
    """
    del settings  # consumed for signature parity; the helper reads env directly
    if not _magic_link_enabled():
        _logger.info(
            "magic_link.disabled",
            extra={"reason": "APAP_AUTH_ENABLE_MAGIC_LINK unset"},
        )
        return

    if not _smtp_configured():
        _logger.warning(
            "magic_link.degraded",
            extra={
                "reason": (
                    "APAP_AUTH_ENABLE_MAGIC_LINK=true but APAP_SMTP_HOST "
                    "unset; magic-link flow disabled, OAuth path still active"
                )
            },
        )
        return

    dsn = os.environ.get("APAP_LOCAL_DB_URL", "").strip()
    if not dsn:
        _logger.warning(
            "magic_link.degraded",
            extra={
                "reason": (
                    "APAP_LOCAL_DB_URL unset; cannot construct "
                    "PostgresMagicLinkAdapter; magic-link flow disabled"
                )
            },
        )
        return

    try:
        application.state.magic_link_port = PostgresMagicLinkAdapter(
            dsn=dsn,
            search_path=os.environ.get("APAP_LOCAL_DB_SCHEMA", "").strip() or None,
        )
        application.state.mail_transport = get_mail_transport()
        factory = getattr(
            application.state, "_magic_link_auth_port_factory", None
        )
        if factory is None:
            _logger.error(
                "magic_link.wiring_failed",
                extra={"error": "_magic_link_auth_port_factory not on app.state"},
            )
            return
        application.state.auth_port = factory()
        _logger.info(
            "magic_link.enabled",
            extra={"smtp_host": os.environ.get("APAP_SMTP_HOST")},
        )
    except Exception as exc:
        _logger.error(
            "magic_link.wiring_failed",
            extra={"error": str(exc)},
        )


__all__ = ["wire_magic_link_to_app_state"]
