"""Structured logging with redaction (Slice 6 of hardening-2026-q2).

The ONLY allowed logging entry point in ``app/`` is :func:`log_safe`.
Direct calls to
``logging.getLogger(...).{info,warning,error,debug,critical,exception}``
are banned by the APAP003 ruff rule (PR-6B, T-6.3) and must NOT appear
anywhere in ``app/`` except this module.

Two layers of PII protection:

1. :func:`log_safe` redacts fields whose names match
   :data:`REDACTED_FIELDS` BEFORE passing them to the underlying
   logger. A sensitive value never reaches the LogRecord unless the
   developer bypassed ``log_safe`` entirely.
2. :class:`RedactionFilter` (installed on the root handler by
   :func:`configure_logging`) provides a second line of defense: if
   anything ever reaches a handler with a sensitive field name, the
   value is replaced with ``"[REDACTED]"`` before formatting.

The redaction list is intentionally CLOSED. Adding a name is a
deliberate code-review change — see ``design.md`` Slice 6 §"Closed-list
policy".

Spec: ``openspec/changes/hardening-2026-q2/specs/06-structured-logging/spec.md``.
Design: ``openspec/changes/hardening-2026-q2/design.md`` §Slice 6
(``app/core/logging.py`` module contract).
Round-2 fix SB-5: redaction list expanded to 12 fields.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

# 12 fields per round-2 fix SB-5: csrf_token, pkce_challenge, referer,
# ip_address, x_forwarded_for added on top of the original 7 from
# spec.md (email, session_token, jwt, oauth_code, pkce_verifier,
# authorization, cookie). dni, tel1, tel2 added by PR4b to cover the
# PII columns the M1 forward migration brings into the web (DNI is
# web-only shadow; Tel1/Tel2 migrate from legacy `TbVoluntariosParaAutorrellenables`).
# Total: 15 closed-list entries. Adding a new PII column means adding
# one line here AND pinning it in ``tests/test_log_safe_redaction.py``.
REDACTED_FIELDS: frozenset[str] = frozenset(
    {
        "email",
        "session_token",
        "jwt",
        "oauth_code",
        "pkce_verifier",
        "csrf_token",
        "pkce_challenge",
        "authorization",
        "cookie",
        "referer",
        "ip_address",
        "x_forwarded_for",
        "dni",
        "tel1",
        "tel2",
    }
)
"""Closed list of field names whose values MUST be replaced with ``"[REDACTED]"``.

Comparison is case-insensitive and treats ``-`` and ``_`` as equivalent
(see :func:`_normalize_key`). The list is intentionally CLOSED:
adding a name is a deliberate code-review change.
"""


def _normalize_key(key: str) -> str:
    """Normalize a field name for redaction list matching.

    Lower-cases and replaces ``-`` with ``_`` so a kwarg named
    ``Session-Token`` matches ``session_token`` in the closed list.
    """
    return key.replace("-", "_").lower()


class JsonFormatter(logging.Formatter):
    """Render a :class:`logging.LogRecord` as a single-line JSON object.

    The payload always includes ``timestamp``, ``level``, ``logger``,
    ``message``, ``module``, ``func``, ``line``. Any ``extra={...}``
    kwarg from the call site is added as top-level keys (after
    redaction, if a :class:`RedactionFilter` is installed upstream).
    """

    _RESERVED_KEYS = frozenset(
        {
            "timestamp",
            "level",
            "logger",
            "message",
            "module",
            "func",
            "line",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        for key, value in record.__dict__.items():
            if key in self._RESERVED_KEYS or key.startswith("_"):
                continue
            payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


class RedactionFilter(logging.Filter):
    """Replace values of fields whose key is in :data:`REDACTED_FIELDS`.

    Applied to a :class:`logging.Handler` so the filter runs BEFORE
    the formatter. This is a second line of defense: ``log_safe``
    already redacts before passing to the logger, but if a developer
    bypasses ``log_safe`` and writes
    ``logger.info("...", extra={"email": ...})`` directly, the filter
    still protects stdout.

    Comparison is case-insensitive and treats ``-`` and ``_`` as
    equivalent (see :func:`_normalize_key`).
    """

    REDACTED_FIELDS = REDACTED_FIELDS

    @staticmethod
    def _normalize(key: str) -> str:
        return _normalize_key(key)

    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__.keys()):
            if self._normalize(key) in self.REDACTED_FIELDS:
                # Mutate ``__dict__`` directly so keys that are not valid
                # Python identifiers (e.g. ``X-Forwarded-For`` with a
                # dash) still get redacted. ``setattr`` would raise
                # ``AttributeError`` on those names.
                record.__dict__[key] = "[REDACTED]"
        return True


def configure_logging(settings: Any) -> None:
    """Install a single ``StreamHandler(sys.stdout)`` with JSON + redaction.

    Idempotent: removes existing handlers from the root logger before
    installing, so calling twice produces the same end state. The
    log level is read from ``settings.log_level`` (project default:
    ``"INFO"``); unknown level strings fall back to ``INFO``.

    The first line of the ``app.main`` lifespan is the canonical call
    site — see ``app/main.py`` and ``design.md`` Slice 6 §"REQ-4".
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    root.addHandler(handler)
    root.setLevel(
        getattr(logging, str(settings.log_level).upper(), logging.INFO)
    )


def log_safe(event: str, **fields: Any) -> None:
    """Emit a structured INFO log. The ONLY allowed logging call in ``app/``.

    Field names matching :data:`REDACTED_FIELDS` (case-insensitive,
    ``_``/``-`` normalized) are replaced with ``"[REDACTED]"`` BEFORE
    the record is constructed — a sensitive value never reaches the
    logger unless the developer bypassed this helper.

    Parameters
    ----------
    event:
        Short event name (e.g. ``"auth.login"``, ``"csrf.rejected"``).
    **fields:
        Structured key=value pairs. PII/secret values will be redacted
        if their key matches the closed redaction list.

    Notes
    -----
    The event name is duplicated as an explicit ``event`` extra field
    on the LogRecord. Downstream dashboards rely on ``event`` being a
    dedicated field (rather than reading the message), so renaming the
    message does not break dashboards.
    """
    record_fields: dict[str, Any] = {"event": event}
    for key, value in fields.items():
        if _normalize_key(key) in REDACTED_FIELDS:
            record_fields[key] = "[REDACTED]"
        else:
            record_fields[key] = value
    logging.getLogger("app").info(event, extra=record_fields)
