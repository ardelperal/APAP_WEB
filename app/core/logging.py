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

Issues #283/#284 refactor:
- log_safe no longer passes caller kwargs as top-level extra keys (which
  collided with reserved LogRecord attr names like ``module``, ``name``,
  ``process``). Instead, all caller kwargs are collected into a single
  ``_caller_fields`` dict which is the value of ONE reserved extra key.
- JsonFormatter uses a strict allow-list instead of a deny-list,
  preventing ~15 LogRecord internal attributes from leaking into JSON.
- RedactionFilter walks inside ``record._caller_fields`` so redaction
  continues to protect PII after the nesting restructure.
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
(see :func:`normalize_key`). The list is intentionally CLOSED:
adding a name is a deliberate code-review change.
"""


def normalize_key(key: str) -> str:
    """Normalize a field name for redaction list matching.

    Lower-cases and replaces ``-`` with ``_`` so a kwarg named
    ``Session-Token`` matches ``session_token`` in the closed list.

    Public API (no leading underscore) since PR5 — ``migration.cli``
    imports this helper to apply the same closed-list comparison
    against ``web_column`` for the operator-facing CLI masking. The
    semantics are stable (case-insensitive, ``-``/``_`` equivalent);
    a future change to the normalisation rule is a contract change
    that requires updating every cross-module caller.
    """
    return key.replace("-", "_").lower()


def _stamp_caller_fields(event: str, **fields: Any) -> dict[str, Any]:
    """Collect caller kwargs into a redacted dict for nested logging.

    All ``**fields`` (including the event name) are placed inside a single
    dict. This dict is the sole value of the reserved extra key
    ``"_caller_fields"`` on the LogRecord, so caller-supplied kwarg names
    can never collide with the 25 reserved LogRecord attribute names
    (``name``, ``module``, ``process``, ``args``, etc.).

    Field names matching :data:`REDACTED_FIELDS` (case-insensitive,
    ``_``/``-`` normalized) have their values replaced with
    ``"[REDACTED]"`` before the dict is returned.

    Parameters
    ----------
    event:
        Short event name (e.g. ``"auth.login"``, ``"csrf.rejected"``).
    **fields:
        Caller-supplied structured key=value pairs.

    Returns
    -------
    dict[str, Any]
        A dict containing ``event`` and all ``fields``, with PII values
        redacted. This dict becomes the value of the reserved extra key
        ``"_caller_fields"`` on the LogRecord.
    """
    out: dict[str, Any] = {"event": event}
    for key, value in fields.items():
        if normalize_key(key) in REDACTED_FIELDS:
            out[key] = "[REDACTED]"
        else:
            out[key] = value
    return out


class JsonFormatter(logging.Formatter):
    """Render a :class:`logging.LogRecord` as a single-line JSON object.

    Strict allow-list: only the documented canonical fields, plus
    ``event`` (extracted from ``_caller_fields``), ``_caller_fields``
    itself, and optionally ``exc_info``/``exc_text``/``stack_info``
    when present on the record.

    No LogRecord internal attributes (``name``, ``msg``, ``args``,
    ``levelname``, ``pathname``, ``thread``, ``process``, etc.) are
    emitted. This replaces the v1 deny-list approach which could leak
    ~15 internal attributes per line (issue #284).
    """

    # Canonical fields from LogRecord, plus event (from _caller_fields),
    # the _caller_fields dict itself, and exception-info keys.
    _ALLOWLIST = frozenset(
        {
            "timestamp",
            "level",
            "logger",
            "message",
            "module",
            "func",
            "line",
            "event",
            "_caller_fields",
            "exc_info",
            "exc_text",
            "stack_info",
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
        # Extract 'event' from _caller_fields and emit it as a top-level key.
        caller_fields = record.__dict__.get("_caller_fields")
        if isinstance(caller_fields, dict):
            payload["_caller_fields"] = caller_fields
            if "event" in caller_fields:
                payload["event"] = caller_fields["event"]
        # Emit exception info when present.
        if record.exc_info:
            payload["exc_text"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
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
    equivalent (see :func:`normalize_key`).

    After the #283/#284 refactor, this filter also walks inside
    ``record._caller_fields`` so that renaming a caller key does not
    bypass the closed redaction list.
    """

    REDACTED_FIELDS = REDACTED_FIELDS

    @staticmethod
    def _normalize(key: str) -> str:
        return normalize_key(key)

    def filter(self, record: logging.LogRecord) -> bool:
        # Top-level defense: redact any REDACTED_FIELD key at top level.
        for key in list(record.__dict__.keys()):
            if key.startswith("_"):
                continue
            if self._normalize(key) in self.REDACTED_FIELDS:
                # Mutate ``__dict__`` directly so keys that are not valid
                # Python identifiers (e.g. ``X-Forwarded-For`` with a
                # dash) still get redacted. ``setattr`` would raise
                # ``AttributeError`` on those names.
                record.__dict__[key] = "[REDACTED]"
        # Nested defense: walk inside _caller_fields (post #283/#284).
        caller_fields = record.__dict__.get("_caller_fields")
        if isinstance(caller_fields, dict):
            for key in list(caller_fields.keys()):
                if self._normalize(key) in self.REDACTED_FIELDS:
                    caller_fields[key] = "[REDACTED]"
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
    logger unless the developer bypasses this helper.

    All caller kwargs (excluding ``exc_info``) are collected into a single
    ``_caller_fields`` dict which is stored as ONE reserved extra key on
    the LogRecord. This prevents ``KeyError: "Attempt to overwrite 'X' in
    LogRecord"`` when a caller-supplied kwarg name collides with a
    reserved LogRecord attribute name (``module``, ``name``, ``process``,
    etc.) — issue #283.

    ``exc_info`` is extracted and forwarded to ``logger.info()`` so the
    logging machinery sets ``record.exc_info`` and ``record.exc_text``
    correctly, enabling ``JsonFormatter`` to emit them.

    The JsonFormatter emits ``event`` as a top-level key (extracted from
    ``_caller_fields``) and ``_caller_fields`` itself as a nested dict.
    No LogRecord internal attributes leak into the JSON output — issue
    #284.

    Parameters
    ----------
    event:
        Short event name (e.g. ``"auth.login"``, ``"csrf.rejected"``).
    **fields:
        Structured key=value pairs. PII/secret values will be redacted
        if their key matches the closed redaction list. ``exc_info`` is
        NOT placed in ``_caller_fields`` — it is forwarded to the logger.

    Notes
    -----
    The ``event`` name is placed inside ``_caller_fields`` and also
    emitted as a top-level ``event`` key by the JsonFormatter
    allow-list. Downstream dashboards that read ``payload["event"]``
    continue to work. Dashboards that read
    ``payload["_caller_fields"]["event"]`` are also supported.
    """
    # Extract exc_info before building _caller_fields so it reaches the
    # logging machinery (record.exc_info), not the caller-fields dict.
    exc_info = fields.pop("exc_info", None)
    caller_fields = _stamp_caller_fields(event, **fields)
    logger = logging.getLogger("app")
    if exc_info is not None:
        logger.info(event, extra={"_caller_fields": caller_fields}, exc_info=exc_info)
    else:
        logger.info(event, extra={"_caller_fields": caller_fields})
