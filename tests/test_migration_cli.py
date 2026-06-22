"""Tests for the ``apap-migrate reconcile`` CLI (PR 5/6 of
``web-only-feature-preservation``).

The CLI is the operator-facing surface that resolves
``reconciliation_status = 'needs_review'`` shadow rows after a
``post_apply_diff`` run flagged a manual web override (Q2 path).
The skeleton (PR 1) only guaranteed that ``--help`` and
``--check-only`` exit cleanly against an empty repo; PR 5 fills
in the read paths, the interactive prompt loop, the keep/accept/
defer write paths, and the ``--table`` / ``--since`` filters.

This file is split into three test classes matching the work-unit
PR split (tasks.md §PR 5):

- T5.6 ``TestReconcileCheckOnly`` — list rows, do not write, exit 0.
- T5.7 ``TestReconcileInteractive`` — the three documented operator
  choices ``(a) keep web / (b) accept derived / (c) defer`` plus
  ``(q) quit`` and unknown-choice edge cases.
- T5.8 ``TestReconcileFilters`` — ``--table`` / ``--since`` flow
  into ``ShadowStateRepository.list_needs_review``.

All tests use mocks for ``web_client`` (``httpx.MockTransport``,
the same pattern as the existing ``test_shadow_state.py`` and
``test_migration.py::TestCliReconcile``) and a list-driven
``_PromptReader`` for the interactive flow, so the suite is fully
deterministic and never touches stdin/stdout or the network.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from typing import Any

import httpx

from app.core.insforge import InsForgeClient
from app.core.migration.cli import main as cli_main


# --- helpers --------------------------------------------------------------


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _make_web_client(handler: Callable[[httpx.Request], httpx.Response]) -> InsForgeClient:
    return InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )


def _needs_review_row(
    *,
    table_name: str = "voluntarios",
    legacy_pk: str = "v-1",
    web_pk: str = "00000000-0000-0000-0000-000000000001",
    web_column: str = "DNI",
    preserved_value: Any = "12345678A",
    strategy: str = "preserve",
    last_legacy_snapshot_at: str | None = "2026-06-20T12:00:00+00:00",
    last_reconciled_at: str | None = None,
    review_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """One row in the shape ``ShadowStateRepository.list_needs_review`` returns.

    Mirrors the column order in the SELECT in
    ``shadow_state.py::list_needs_review`` so the fake response is
    byte-for-byte compatible with what production would return.
    """
    return {
        "id": "00000000-0000-0000-0000-000000000aaa",
        "table_name": table_name,
        "legacy_pk": legacy_pk,
        "web_pk": web_pk,
        "web_column": web_column,
        "preserved_value": json.dumps(preserved_value),
        "strategy": strategy,
        "last_legacy_snapshot_at": last_legacy_snapshot_at,
        "last_web_edit_at": None,
        "last_reconciled_at": last_reconciled_at,
        "reconciliation_status": "needs_review",
        "review_reasons": json.dumps(review_reasons or ["web_manual_override_detected"]),
    }


def _capture_prompt(responses: list[str]) -> Callable[[str], str]:
    """Build a list-driven ``_PromptReader`` for the interactive flow.

    Tests pre-load the canned responses in the order the CLI is
    expected to ask. ``StopIteration`` surfaces as a test failure
    (caller runs out of pre-canned answers) which is the right
    safety net: a missing entry in the list means the test's
    expected flow drifted from the production flow.
    """

    def _read(_prompt: str) -> str:
        if not responses:
            raise AssertionError("prompt called more times than test expected")
        return responses.pop(0)

    return _read


def _run_reconcile(
    *,
    argv: list[str],
    shadow_rows: list[dict[str, Any]],
    extra_sql: dict[str, list[dict[str, Any]]] | None = None,
    prompt: Callable[[str], str] | None = None,
    stream: Any = None,
) -> tuple[int, list[dict[str, Any]], str]:
    """Drive ``cli_main`` end-to-end and return ``(rc, captured_calls, stdout)``.

    ``shadow_rows`` is the body the SELECT in
    ``ShadowStateRepository.list_needs_review`` returns.
    ``extra_sql`` is an optional ``{contains: [{...}]}`` map of
    additional bodies to return when a specific SQL substring
    appears in the request (e.g. ``{"UPDATE voluntarios": [{"ok": 1}]}``).
    The mock response defaults to an empty list so any extra SQL
    (UPDATE, INSERT) just no-ops if not configured.
    """
    extra_sql = extra_sql or {}
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        query = body.get("query", "") if isinstance(body, dict) else ""
        for marker, rows in extra_sql.items():
            if marker in query:
                return _json_response(200, rows)
        # Default: return the shadow rows only when the query looks
        # like the ``list_needs_review`` SELECT. Anything else
        # (UPDATE, INSERT) returns an empty list — the
        # InsForgeClient protocol doesn't choke on that, and the
        # tests assert the call was issued (not the result).
        if "web_only_feature_shadow" in query and "WHERE" in query:
            return _json_response(200, shadow_rows)
        return _json_response(200, [])

    client = _make_web_client(handler)
    try:
        rc = cli_main(
            argv,
            web_client=client,
            prompt=prompt,
            stream=stream,
        )
    finally:
        client.close()

    stdout = ""
    if stream is not None:
        stdout = stream.getvalue()

    return rc, captured, stdout


# --- T5.6: --check-only --------------------------------------------------


class TestReconcileCheckOnly:
    """``apap-migrate reconcile --check-only`` lists pending cases
    without writing, exit 0 even with pending rows (design.md §7).
    """

    def test_check_only_lists_pending_no_writes(self) -> None:
        """``--check-only`` prints one ``key=value`` line per pending row
        and never issues a write SQL (``UPDATE`` / ``INSERT``).

        Three rows are pre-seeded in the shadow state; the CLI is
        invoked with ``--check-only``. Assertions:
        - exit code 0 (pending cases do NOT abort — design.md §7).
        - ``stdout`` contains the three pending rows in the
          ``key=value`` format.
        - the captured SQL list contains no ``UPDATE`` / ``INSERT``
          statements (the SELECT in ``list_needs_review`` is the
          only statement issued).
        """
        rows = [
            _needs_review_row(legacy_pk="v-1", web_column="DNI", table_name="voluntarios"),
            _needs_review_row(
                legacy_pk="a-1",
                web_column="current_state",
                table_name="animales",
                preserved_value=None,
                strategy="derived",
            ),
            _needs_review_row(
                legacy_pk="a-2",
                web_column="current_state",
                table_name="animales",
                preserved_value=None,
                strategy="derived",
            ),
        ]
        stream = io.StringIO()
        rc, captured, stdout = _run_reconcile(
            argv=["reconcile", "--check-only"],
            shadow_rows=rows,
            stream=stream,
        )

        assert rc == 0, f"reconcile --check-only must exit 0; got rc={rc}, stdout={stdout!r}"
        # Three rows → three lines of key=value pairs.
        out_lines = [line for line in stdout.splitlines() if line.strip()]
        assert len(out_lines) == 3, (
            f"--check-only must emit one line per row; got {len(out_lines)}: {out_lines!r}"
        )
        # All three legacy_pks appear in the output (sanity check on
        # the rendered content, not just the count).
        assert "legacy_pk=v-1" in stdout
        assert "legacy_pk=a-1" in stdout
        assert "legacy_pk=a-2" in stdout
        # Status flag is surfaced so the operator can grep.
        assert "status=needs_review" in stdout
        # No write SQL was issued: every captured query is a SELECT
        # against ``web_only_feature_shadow``.
        for call in captured:
            query = call.get("query", "")
            assert "INSERT" not in query.upper(), f"unexpected INSERT: {query!r}"
            assert "UPDATE" not in query.upper(), f"unexpected UPDATE: {query!r}"
            assert "DELETE" not in query.upper(), f"unexpected DELETE: {query!r}"
