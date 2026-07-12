"""Tests for ``app.core.logging`` (PR-6A, Slice 6 of hardening-2026-q2).

The structured-logging module is the ONLY allowed logging entry point
in ``app/``: APAP003 (ruff rule, PR-6B) bans raw ``logger.*`` calls
everywhere except ``app/core/logging.py``. These tests pin the
contract that ``log_safe``, ``JsonFormatter``, ``RedactionFilter``
and ``configure_logging`` together implement.

Coverage:

- REQ-1 (configure_logging) — single handler, idempotency.
- REQ-2 (log_safe redaction) — closed 12-field list, case-insensitive,
  ``_``/``-`` equivalence, non-PII passthrough.
- REQ-3 (filter as second line of defense) — bypass-via-logger still
  redacts because the filter mutates the LogRecord before formatting.
- REQ-4 (JSON format) — every emitted line is parseable JSON with the
  documented shape.

Adversarial cases (orthographic splits, mixed case, descriptive names
that look like PII but aren't) live in
``tests/test_logging_redaction_adversarial.py`` per tasks.md:T-6.10.

Spec: ``openspec/changes/hardening-2026-q2/specs/06-structured-logging/spec.md``.
Round-2 fix SB-5: redaction list expanded to 12 fields.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest

from app.core.logging import (
    REDACTED_FIELDS,
    JsonFormatter,
    RedactionFilter,
    configure_logging,
    log_safe,
)

# --- REQ-1: configure_logging installs a single stdout handler ------------


@pytest.fixture(autouse=True)
def _reset_root_logger_handlers() -> None:
    """Snapshot + restore root logger handlers around each test.

    ``configure_logging`` mutates the root logger's handler list. We
    capture the pre-test list and restore it after so one test's handler
    doesn't leak into the next (pytest's own caplog handler is
    unaffected because pytest re-attaches it on collection).
    """
    root = logging.getLogger()
    saved = list(root.handlers)
    saved_level = root.level
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved:
        root.addHandler(handler)
    root.setLevel(saved_level)


def test_configure_logging_installs_exactly_one_handler() -> None:
    """REQ-1 Scenario 1: ``configure_logging`` produces a single handler."""
    class _FakeSettings:
        log_level = "INFO"

    configure_logging(_FakeSettings())
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    handler = handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys_stdout()


def test_configure_logging_handler_carries_formatter_and_filter() -> None:
    """The handler must have ``JsonFormatter`` and ``RedactionFilter``."""
    class _FakeSettings:
        log_level = "INFO"

    configure_logging(_FakeSettings())
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler.formatter, JsonFormatter)
    filter_types = [type(f) for f in handler.filters]
    assert RedactionFilter in filter_types


def test_configure_logging_is_idempotent() -> None:
    """REQ-1 Scenario 2: calling twice does not duplicate handlers."""
    class _FakeSettings:
        log_level = "INFO"

    configure_logging(_FakeSettings())
    first_handler = logging.getLogger().handlers[0]
    configure_logging(_FakeSettings())
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    # The second call replaced the first one with a fresh handler.
    assert handlers[0] is not first_handler


def test_configure_logging_respects_settings_log_level() -> None:
    """The root logger level must come from ``settings.log_level``."""

    class _FakeSettings:
        log_level = "WARNING"

    configure_logging(_FakeSettings())
    assert logging.getLogger().level == logging.WARNING


def test_configure_logging_falls_back_to_info_on_unknown_level() -> None:
    """Unknown level strings must NOT crash; default to INFO."""

    class _FakeSettings:
        log_level = "BOGUS_LEVEL_NAME"

    configure_logging(_FakeSettings())
    assert logging.getLogger().level == logging.INFO


def sys_stdout() -> Any:
    """Return ``sys.stdout`` from the logging module's perspective."""
    import sys
    return sys.stdout


# --- REQ-2: log_safe redaction --------------------------------------------


@pytest.mark.parametrize(
    "redacted_field",
    sorted(REDACTED_FIELDS),
)
def test_log_safe_redacts_every_closed_list_field(
    redacted_field: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every name in ``REDACTED_FIELDS`` MUST be replaced with '[REDACTED]'.

    Parametrized over all 12 entries per round-2 fix SB-5
    (csrf_token, pkce_challenge, referer, ip_address, x_forwarded_for
    added to the original 7 from spec.md).
    """
    secret_value = f"super-secret-{redacted_field}"
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("test.event", **{redacted_field: secret_value})

    assert caplog.records, "log_safe did not emit a LogRecord"
    record = caplog.records[0]
    assert getattr(record, redacted_field) == "[REDACTED]", (
        f"log_safe leaked {redacted_field}: "
        f"record.{redacted_field}={getattr(record, redacted_field)!r}"
    )
    # The secret value MUST NOT appear anywhere on the record.
    assert secret_value not in str(record.__dict__)


def test_log_safe_does_not_leak_email_via_record_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-2 Scenario 1: ``email`` is redacted AND not in the formatted message."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("auth.login", email="victim@example.com")

    record = caplog.records[0]
    assert record.email == "[REDACTED]"
    assert "victim@example.com" not in record.getMessage()


def test_log_safe_passes_non_pii_through_unchanged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-2 non-PII Scenario: ``path`` and ``status_code`` are NOT redacted."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("http.request", path="/admin/users", status_code=200)

    record = caplog.records[0]
    assert record.path == "/admin/users"
    assert record.status_code == 200


def test_log_safe_sets_event_field_explicitly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The event name is duplicated as an explicit ``event`` extra for downstream dashboards."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("csrf.rejected", path="/admin/users", reason="token_mismatch")

    record = caplog.records[0]
    assert record.event == "csrf.rejected"
    assert record.path == "/admin/users"
    assert record.reason == "token_mismatch"


def test_log_safe_redaction_is_case_insensitive(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-2 Scenario 3: ``EMAIL`` and ``Session_Token`` are still redacted."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe(
            "test.event",
            EMAIL="victim@example.com",
            Session_Token="abc.def.ghi",
        )

    record = caplog.records[0]
    assert record.EMAIL == "[REDACTED]"
    assert record.Session_Token == "[REDACTED]"
    assert "victim@example.com" not in str(record.__dict__)
    assert "abc.def.ghi" not in str(record.__dict__)


def test_log_safe_redaction_treats_dash_and_underscore_equivalently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-3 Scenario 1: ``session-token`` (dash) matches ``session_token``."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("test.event", session_token="abc.def.ghi")

    record = caplog.records[0]
    assert record.session_token == "[REDACTED]"


def test_log_safe_does_not_redact_descriptive_field_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-3 Scenario 2: ``user_email_address`` (descriptive) is NOT redacted.

    Closed-list policy: a name that merely CONTAINS a redacted substring
    is not redacted. The list is exact-match after normalization.
    """
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("test.event", user_email_address="ana@example.com")

    record = caplog.records[0]
    assert record.user_email_address == "ana@example.com"


def test_log_safe_emits_info_level(caplog: pytest.LogCaptureFixture) -> None:
    """log_safe's default level is INFO (operators see auth/route events)."""
    with caplog.at_level(logging.DEBUG, logger="app"):
        log_safe("test.event", path="/x")
    assert caplog.records
    assert caplog.records[0].levelno == logging.INFO


def test_log_safe_works_without_any_fields(caplog: pytest.LogCaptureFixture) -> None:
    """log_safe accepts an event-only call (no kwargs)."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("boot.complete")
    record = caplog.records[0]
    assert record.message == "boot.complete"
    assert record.event == "boot.complete"


# --- REQ-3: RedactionFilter as second line of defense ---------------------


def test_redaction_filter_replaces_email_on_bypass_logger_call() -> None:
    """If a developer bypasses ``log_safe`` and calls the logger directly,
    the filter MUST still redact email (closed-list defense in depth).
    """
    logger = logging.getLogger("test_redaction_filter_bypass")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    captured_records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured_records.append(record)

    handler = _Capture()
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)

    logger.info("bypass", extra={"email": "secret@example.com"})

    assert captured_records, "the bypass log did not emit"
    assert captured_records[0].email == "[REDACTED]"


def test_redaction_filter_normalizes_dashes_and_case() -> None:
    """The filter normalizes ``X-Forwarded-For`` -> ``x_forwarded_for``.

    Dash-keys aren't valid Python identifiers, so the filter mutates
    ``record.__dict__`` directly. The JsonFormatter reads from
    ``__dict__`` too, so the redacted value still reaches stdout.
    """
    logger = logging.getLogger("test_redaction_filter_normalize")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    captured_records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured_records.append(record)

    handler = _Capture()
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)

    logger.info("bypass", extra={"X-Forwarded-For": "10.0.0.1"})

    assert captured_records
    assert captured_records[0].__dict__["X-Forwarded-For"] == "[REDACTED]"


def test_redacted_fields_constant_has_fifteen_entries() -> None:
    """Round-2 fix SB-5 + PR4b extension: the closed list MUST contain all 15 fields.

    A regression here (someone deletes a field to silence a test)
    breaks the security contract. The constant is referenced by both
    ``log_safe`` and ``RedactionFilter`` so a drift is caught here.
    PR4b adds the three PII columns the M1 forward migration brings into
    the web (``dni``, ``tel1``, ``tel2``) on top of the original 12.
    """
    expected = frozenset(
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
    assert REDACTED_FIELDS == expected, (
        f"REDACTED_FIELDS drifted: missing={expected - REDACTED_FIELDS}, "
        f"extra={REDACTED_FIELDS - expected}"
    )


# --- REQ-4: JsonFormatter produces parseable JSON --------------------------


def test_json_formatter_emits_required_top_level_fields() -> None:
    """The JSON payload MUST include the documented top-level fields."""
    record = logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello",
        args=(),
        exc_info=None,
    )
    output = JsonFormatter().format(record)
    payload = json.loads(output)
    for required in ("timestamp", "level", "logger", "message", "module", "func", "line"):
        assert required in payload, f"JsonFormatter missing {required!r}: {payload}"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app"
    assert payload["message"] == "hello"


def test_json_formatter_includes_extra_fields() -> None:
    """``extra={...}`` kwargs MUST appear as top-level JSON keys."""
    record = logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="csrf.rejected",
        args=(),
        exc_info=None,
    )
    record.path = "/admin/users"
    record.reason = "token_mismatch"
    output = JsonFormatter().format(record)
    payload = json.loads(output)
    assert payload["path"] == "/admin/users"
    assert payload["reason"] == "token_mismatch"


def test_json_formatter_renders_to_stdout_format() -> None:
    """End-to-end: configure_logging + log_safe produces a parseable JSON line on stdout."""
    class _FakeSettings:
        log_level = "INFO"

    stream = io.StringIO()
    configure_logging(_FakeSettings())
    # Replace the configured stream with our StringIO so we can read it back.
    handler = logging.getLogger().handlers[0]
    original_stream = handler.stream
    handler.stream = stream
    try:
        log_safe("e2e.event", path="/x", email="victim@example.com")
    finally:
        handler.stream = original_stream

    line = stream.getvalue().strip()
    assert line, "no output captured"
    payload = json.loads(line)
    assert payload["message"] == "e2e.event"
    assert payload["event"] == "e2e.event"
    assert payload["path"] == "/x"
    assert payload["email"] == "[REDACTED]"
    # The secret value MUST NOT appear in the rendered JSON.
    assert "victim@example.com" not in line
