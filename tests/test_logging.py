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
    _stamp_caller_fields,
    configure_logging,
    log_safe,
)

# --- T1 RED: _stamp_caller_fields helper (issues #283, #284) ------------


def test_stamp_caller_fields_redacts_email() -> None:
    """T1.1 RED: _stamp_caller_fields redacts email → result['email'] == '[REDACTED]'."""
    result = _stamp_caller_fields("test.event", email="a@b.c")
    assert result["email"] == "[REDACTED]", (
        f"email was not redacted: {result.get('email')!r}"
    )


def test_stamp_caller_fields_carries_event() -> None:
    """T1.2 RED: _stamp_caller_fields carries event → result['event'] == event_value."""
    result = _stamp_caller_fields("auth.login", path="/admin")
    assert result["event"] == "auth.login", (
        f"event was not carried: {result.get('event')!r}"
    )


def test_stamp_caller_fields_empty_kwargs() -> None:
    """T1.3 RED: _stamp_caller_fields handles empty kwargs → result == {'event': event_value}."""
    result = _stamp_caller_fields("boot.complete")
    assert result == {"event": "boot.complete"}, (
        f"empty kwargs produced wrong result: {result!r}"
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

    After the #283/#284 refactor, caller fields live in record._caller_fields.
    """
    secret_value = f"super-secret-{redacted_field}"
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("test.event", **{redacted_field: secret_value})

    assert caplog.records, "log_safe did not emit a LogRecord"
    record = caplog.records[0]
    assert record._caller_fields[redacted_field] == "[REDACTED]", (
        f"log_safe leaked {redacted_field}: "
        f"record._caller_fields[{redacted_field}]={record._caller_fields.get(redacted_field)!r}"
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
    assert record._caller_fields["email"] == "[REDACTED]"
    assert "victim@example.com" not in record.getMessage()


def test_log_safe_passes_non_pii_through_unchanged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-2 non-PII Scenario: ``path`` and ``status_code`` are NOT redacted."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("http.request", path="/admin/users", status_code=200)

    record = caplog.records[0]
    assert record._caller_fields["path"] == "/admin/users"
    assert record._caller_fields["status_code"] == 200


def test_log_safe_sets_event_field_explicitly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The event name is stored in _caller_fields and emitted as top-level 'event'."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("csrf.rejected", path="/admin/users", reason="token_mismatch")

    record = caplog.records[0]
    assert record._caller_fields["event"] == "csrf.rejected"
    assert record._caller_fields["path"] == "/admin/users"
    assert record._caller_fields["reason"] == "token_mismatch"


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
    assert record._caller_fields["EMAIL"] == "[REDACTED]"
    assert record._caller_fields["Session_Token"] == "[REDACTED]"
    assert "victim@example.com" not in str(record.__dict__)
    assert "abc.def.ghi" not in str(record.__dict__)


def test_log_safe_redaction_treats_dash_and_underscore_equivalently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-3 Scenario 1: ``session-token`` (dash) matches ``session_token``."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("test.event", session_token="abc.def.ghi")

    record = caplog.records[0]
    assert record._caller_fields["session_token"] == "[REDACTED]"


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
    assert record._caller_fields["user_email_address"] == "ana@example.com"


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
    assert record._caller_fields["event"] == "boot.complete"


# --- T2 RED: log_safe reserved LogRecord attr collision (issues #283, #284) --


# All 25 reserved LogRecord attribute names in Python 3.11/3.12.
_RESERVED_LOGRECORD_ATTRS = [
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
    "taskName",
]


@pytest.mark.parametrize("attr_name", _RESERVED_LOGRECORD_ATTRS)
def test_log_safe_does_not_raise_on_reserved_logrecord_attr(
    attr_name: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T2.1 RED: log_safe does NOT raise KeyError for all 25 reserved LogRecord attr names.

    After the nested-envelope refactor, caller kwargs live inside record._caller_fields,
    not as top-level extra keys. So a kwarg named 'module' cannot collide with
    LogRecord.module (which is set by the logging machinery itself).
    """
    with caplog.at_level(logging.INFO, logger="app"):
        # This must not raise KeyError: "Attempt to overwrite 'X' in LogRecord"
        log_safe("test.collision", **{attr_name: f"caller-value-{attr_name}"})

    assert caplog.records, "log_safe did not emit a LogRecord"
    record = caplog.records[0]
    # The caller's value is stored inside _caller_fields, not at the top level.
    assert attr_name in record._caller_fields, (
        f"caller kwarg {attr_name!r} not stored in _caller_fields"
    )
    assert record._caller_fields[attr_name] == f"caller-value-{attr_name}"


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
    """After #283/#284 refactor, caller kwargs are in record._caller_fields.

    The JsonFormatter reads _caller_fields and emits it as a nested dict.
    """
    record = logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="csrf.rejected",
        args=(),
        exc_info=None,
    )
    # Simulate what log_safe does: stamp _caller_fields and pass via extra.
    record.__dict__["_caller_fields"] = {
        "event": "csrf.rejected",
        "path": "/admin/users",
        "reason": "token_mismatch",
    }
    output = JsonFormatter().format(record)
    payload = json.loads(output)
    assert payload["_caller_fields"]["path"] == "/admin/users"
    assert payload["_caller_fields"]["reason"] == "token_mismatch"


def test_json_formatter_renders_to_stdout_format() -> None:
    """End-to-end: configure_logging + log_safe produces a parseable JSON line on stdout.

    After #283/#284 refactor: caller kwargs are inside payload["_caller_fields"].
    The JsonFormatter emits event as a top-level key (from _caller_fields.event)
    and _caller_fields itself as a nested dict.
    """
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
    assert payload["_caller_fields"]["path"] == "/x"
    assert payload["_caller_fields"]["email"] == "[REDACTED]"
    assert payload["_caller_fields"]["event"] == "e2e.event"
    # The secret value MUST NOT appear in the rendered JSON.
    assert "victim@example.com" not in line


# --- T3 RED: JsonFormatter strict allow-list (issues #283, #284) -----------


_EXPECTED_KEYS_PLAIN = frozenset(
    {"timestamp", "level", "logger", "message", "module", "func", "line", "event", "_caller_fields"}
)
_INTERNAL_KEYS_THAT_MUST_NOT_LEAK = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "pathname",
        "filename",
        "thread",
        "process",
        "taskName",
        "processName",
        "threadName",
        "asctime",
        "resourceUK",
        "msecs",
        "relativeCreated",
        "exc_info",
        "exc_text",
        "stack_info",
        "created",
    }
)


def test_json_formatter_emits_exact_key_set_for_plain_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T3.1 RED: JsonFormatter.format plain call emits exactly the documented key set.

    The allow-list emits only timestamp, level, logger, message, module, func,
    line, event, and _caller_fields. No LogRecord internal keys (name, msg, args,
    levelname, pathname, thread, process, taskName, etc.) may appear.
    """
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("auth.login", path="/admin")

    assert caplog.records, "log_safe did not emit"
    record = caplog.records[0]
    output = JsonFormatter().format(record)
    payload = json.loads(output)

    assert frozenset(payload.keys()) == _EXPECTED_KEYS_PLAIN, (
        f"JsonFormatter emitted unexpected keys: {set(payload.keys()) - _EXPECTED_KEYS_PLAIN}"
    )
    # No LogRecord internals may leak.
    for bad in _INTERNAL_KEYS_THAT_MUST_NOT_LEAK:
        assert bad not in payload, (
            f"LogRecord internal key {bad!r} leaked into JSON payload: {payload}"
        )
    # _caller_fields is a dict that carries the caller's kwargs.
    assert isinstance(payload["_caller_fields"], dict), (
        f"_caller_fields should be a dict, got {type(payload['_caller_fields'])}"
    )
    assert payload["_caller_fields"]["path"] == "/admin"
    assert payload["_caller_fields"]["event"] == "auth.login"


def test_json_formatter_emits_exact_key_set_for_redacted_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T3.2 RED: JsonFormatter.format with redacted fields emits same exact key set.

    Even when email is redacted, the top-level key set is unchanged — no extra
    keys from LogRecord internals may appear.
    """
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("auth.login", email="a@b.c", path="/admin")

    assert caplog.records, "log_safe did not emit"
    record = caplog.records[0]
    output = JsonFormatter().format(record)
    payload = json.loads(output)

    assert frozenset(payload.keys()) == _EXPECTED_KEYS_PLAIN, (
        f"JsonFormatter emitted unexpected keys with redaction: {set(payload.keys()) - _EXPECTED_KEYS_PLAIN}"
    )
    assert payload["_caller_fields"]["email"] == "[REDACTED]"
    assert payload["_caller_fields"]["path"] == "/admin"
    for bad in _INTERNAL_KEYS_THAT_MUST_NOT_LEAK:
        assert bad not in payload, f"LogRecord internal {bad!r} leaked with redaction"


def test_json_formatter_emits_exc_info_when_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T3.3 RED: JsonFormatter.format with exc_info present emits exc_info or exc_text key.

    Tracebacks must be preserved in JSON output (spec REQ-3). The allow-list
    explicitly includes exc_info, exc_text, and stack_info.
    """
    with caplog.at_level(logging.INFO, logger="app"):
        try:
            raise ValueError("test traceback")
        except ValueError:
            log_safe("error", exc_info=True)

    assert caplog.records, "log_safe did not emit"
    record = caplog.records[0]
    output = JsonFormatter().format(record)
    payload = json.loads(output)

    # exc_info or exc_text or stack_info must be present with non-empty value.
    exc_keys = {"exc_info", "exc_text", "stack_info"}
    found = exc_keys & frozenset(payload.keys())
    assert found, f"No exception info key in payload; expected one of {exc_keys}: {payload}"
    for k in found:
        assert payload[k], f"Exception key {k!r} is empty: {payload[k]!r}"


# --- T4 RED: nested _caller_fields redaction (issues #283, #284) ---------


def test_nested_redaction_replaces_email_inside_caller_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T4.1 RED: log_safe('x', email='a@b.c') → _caller_fields['email'] == '[REDACTED]'.

    After the nested-envelope refactor, RedactionFilter walks inside _caller_fields
    and replaces email with '[REDACTED]'. The raw value must not appear in the
    formatted JSON string.
    """
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("x", email="a@b.c")

    assert caplog.records, "log_safe did not emit"
    record = caplog.records[0]
    output = JsonFormatter().format(record)
    assert record._caller_fields["email"] == "[REDACTED]", (
        f"email not redacted inside _caller_fields: {record._caller_fields.get('email')!r}"
    )
    assert "a@b.c" not in output, (
        f"raw email 'a@b.c' leaked into JSON output: {output}"
    )
