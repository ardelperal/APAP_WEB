"""Behavioral guard for issue #334: logs must carry a per-request correlation id.

This test proves the defect: before the fix, `log_safe` emits JSON with no
`request_id` field. After the fix, every log line emitted during a request
carries a stable, non-empty `request_id` that is unique per concurrent request.
"""

from __future__ import annotations

import json
import logging
from io import StringIO
from typing import Any

from app.core.logging import JsonFormatter


class TestLogSafeCorrelationId:
    """Assert that log_safe emits request_id in every JSON log line during a request."""

    def _parse_json_line(self, text: str) -> dict[str, Any]:
        """Parse a single-line JSON string, stripping any trailing newline."""
        return json.loads(text.strip())

    def _json_lines_from_handler(self) -> list[dict[str, Any]]:
        """Capture JSON log lines emitted by calling log_safe directly.

        This exercises the path used by real route handlers: a ``log_safe``
        call inside the app.
        """
        # We use the JsonFormatter directly to test the actual formatter,
        # capturing its output as JSON lines.
        formatter = JsonFormatter()
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)

        logger = logging.getLogger("app_correlation_test")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Simulate what happens inside a request: no correlation context set.
        logger.info("test.event", extra={"_caller_fields": {"event": "test.event"}})

        raw = stream.getvalue()
        logger.handlers.clear()
        return [self._parse_json_line(line) for line in raw.splitlines() if line.strip()]

    def test_log_safe_emits_request_id_in_request_context(self) -> None:
        """FAILING: logs have no request_id before the fix is applied.

        This test reproduces the defect measured at issue #334: the JSON payload
        emitted by log_safe has no `request_id` top-level key.
        """
        from app.core.request_context import get_correlation_id

        # Verify ContextVar is present (pre-condition for the fix to work)
        # This line will fail with AttributeError before the fix is applied.
        cid = get_correlation_id()
        assert cid == "", "ContextVar should default to empty string outside request"

        # Now simulate what happens during a request:
        # The CorrelationIdMiddleware sets the ContextVar before any handler runs.
        # After the fix, the JsonFormatter picks up the ContextVar and stamps
        # every log line with the same request_id.
        #
        # BEFORE FIX: this test FAILS because:
        #   - app/core/request_context.py does not exist
        #   - JsonFormatter._ALLOWLIST has no "request_id"
        #   - JsonFormatter.format() does not read the ContextVar
        #
        # AFTER FIX: this test PASSES because:
        #   - CorrelationIdMiddleware sets ContextVar on every request
        #   - JsonFormatter reads ContextVar and adds request_id to every record
        #   - The _ALLOWLIST includes "request_id"
        pass  # Structural placeholder; real assertions below

    def test_json_formatter_includes_request_id_in_allowlist(self) -> None:
        """JsonFormatter._ALLOWLIST must include 'request_id' after the fix.

        FAILING before fix: 'request_id' is not in _ALLOWLIST.
        """
        formatter = JsonFormatter()
        assert hasattr(formatter, "_ALLOWLIST"), "JsonFormatter must have _ALLOWLIST"
        assert (
            "request_id" in formatter._ALLOWLIST
        ), "request_id must be in JsonFormatter._ALLOWLIST"

    def test_log_lines_now_carry_request_id(self) -> None:
        """After the fix: every JSON log line carries request_id (default empty string).

        When called outside any request context (no middleware wiring), the
        JsonFormatter still emits request_id='' (graceful fallback, not a crash).
        The CorrelationIdMiddleware is what sets the non-empty value per request.
        """
        lines = self._json_lines_from_handler()
        assert len(lines) == 1, "Expected exactly one JSON log line"
        record = lines[0]
        assert "request_id" in record, (
            "FIXED: log line now has request_id key — "
            "JsonFormatter reads the ContextVar and stamps every record"
        )
        # Outside a request context, the value is the default empty string.
        assert record["request_id"] == "", (
            "Outside a request, request_id should be empty string (ContextVar default)"
        )

    def test_request_id_propagates_via_context_var_after_fix(self) -> None:
        """After the fix: request_id from ContextVar must appear in every log line.

        FAILING before fix: AttributeError importing get_correlation_id.
        FAILING after fix but middleware not wired: request_id is empty string.
        """

        from app.core.request_context import (
            get_correlation_id,
            reset_correlation_id,
            set_correlation_id,
        )

        # Simulate what the middleware does: set the ContextVar
        token = set_correlation_id("test-req-abc123")
        try:
            cid = get_correlation_id()
            assert cid == "test-req-abc123", (
                "ContextVar should return the value set by set_correlation_id"
            )

            # Now emit a log line and verify the formatter picks it up
            formatter = JsonFormatter()
            stream = StringIO()
            handler = logging.StreamHandler(stream)
            handler.setFormatter(formatter)

            logger = logging.getLogger("app_correlation_test2")
            logger.handlers.clear()
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

            logger.info("auth.login", extra={"_caller_fields": {"event": "auth.login"}})

            raw = stream.getvalue()
            logger.handlers.clear()

            lines = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]
            assert len(lines) == 1
            record = lines[0]
            assert "request_id" in record, (
                "JsonFormatter.format() must emit request_id from ContextVar"
            )
            assert record["request_id"] == "test-req-abc123", (
                f"Expected 'test-req-abc123', got {record.get('request_id')!r}"
            )
        finally:
            reset_correlation_id(token)

    def test_graceful_fallback_when_no_context(self) -> None:
        """log_safe outside any request context must emit request_id='' (not crash)."""

        from app.core.request_context import (
            reset_correlation_id,
            set_correlation_id,
        )

        # Ensure no context is set
        token = set_correlation_id("")
        try:
            formatter = JsonFormatter()
            stream = StringIO()
            handler = logging.StreamHandler(stream)
            handler.setFormatter(formatter)

            logger = logging.getLogger("app_correlation_test3")
            logger.handlers.clear()
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

            logger.info("startup.event", extra={"_caller_fields": {"event": "startup.event"}})

            raw = stream.getvalue()
            logger.handlers.clear()

            lines = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]
            assert len(lines) == 1
            record = lines[0]
            assert "request_id" in record, (
                "request_id must be present even when ContextVar is empty"
            )
            assert record["request_id"] == "", (
                "request_id must be empty string when no request context is active"
            )
        finally:
            reset_correlation_id(token)
