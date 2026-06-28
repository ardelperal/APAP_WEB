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
from migration.cli import main as cli_main

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


# --- T5.7: --interactive (a/b/c/q) ---------------------------------------


class TestReconcileInteractive:
    """``apap-migrate reconcile --interactive`` walks each case with
    prompts ``(a) keep web / (b) accept derived / (c) defer / (q) quit``.

    Each test pre-loads the prompt queue with the operator's choices
    and asserts the resulting write path. The test fake
    ``web_client`` records every SQL call so the assertions can
    distinguish shadow-state writes (``update_reconciliation_status``)
    from web-table writes (``UPDATE {table}``).
    """

    def test_interactive_keep_web_writes_matched(self) -> None:
        """Operator picks ``(a) keep web`` → shadow row is flipped to
        ``matched`` and the web value is NOT modified.

        One pending row for ``voluntarios.DNI`` (preserve strategy).
        The prompt queue is ``["a"]`` — the operator picks keep.
        Assertions:
        - exit 0.
        - the CLI issues ``UPDATE web_only_feature_shadow`` with
          ``reconciliation_status = 'matched'`` (the
          ``ShadowStateRepository.update_reconciliation_status``
          SQL).
        - NO ``UPDATE voluntarios`` is issued (the web value is
          preserved verbatim; keep does not write to the web table).
        """
        row = _needs_review_row(
            table_name="voluntarios",
            legacy_pk="v-1",
            web_pk="00000000-0000-0000-0000-000000000001",
            web_column="DNI",
            preserved_value="12345678A",
            strategy="preserve",
        )
        prompt = _capture_prompt(["a"])

        rc, captured, _stdout = _run_reconcile(
            argv=["reconcile", "--interactive"],
            shadow_rows=[row],
            prompt=prompt,
        )

        assert rc == 0
        # Find the shadow-state UPDATE that flips status to matched.
        shadow_updates = [
            c
            for c in captured
            if "UPDATE web_only_feature_shadow" in c.get("query", "")
            and "reconciliation_status = %s" in c.get("query", "")
        ]
        assert len(shadow_updates) == 1, (
            f"keep web must issue exactly one shadow-state UPDATE; "
            f"got {len(shadow_updates)}: {shadow_updates!r}"
        )
        params = shadow_updates[0].get("params", [])
        assert params[0] == "matched", f"status must be 'matched'; got {params[0]!r}"
        assert params[3] == "voluntarios"
        assert params[4] == "v-1"
        assert params[5] == "DNI"
        # No UPDATE issued against the voluntarios web table.
        web_updates = [
            c
            for c in captured
            if "UPDATE voluntarios" in c.get("query", "").upper()
            and "web_only_feature_shadow" not in c.get("query", "")
        ]
        assert web_updates == [], f"keep web must NOT issue a web-table UPDATE; got {web_updates!r}"

    def test_interactive_accept_derived_writes_web_value(self) -> None:
        """Operator picks ``(b) accept derived`` → CLI prompts for the
        value, issues ``UPDATE {web_table} SET {web_column} = ...``,
        and flips the shadow row to ``matched``.

        One pending row for ``animales.current_state`` (derived
        strategy). The prompt queue is ``["b", "Adoptado"]`` — the
        operator picks accept and types ``"Adoptado"`` as the new
        value. Assertions:
        - exit 0.
        - the CLI issues an ``UPDATE animales SET current_state = ...``
          with the typed value, scoped by ``id = {web_pk}``.
        - the shadow row is flipped to ``matched`` with
          ``last_reconciled_at`` populated.
        """
        row = _needs_review_row(
            table_name="animales",
            legacy_pk="a-1",
            web_pk="00000000-0000-0000-0000-0000000000aa",
            web_column="current_state",
            preserved_value=None,  # derived → NULL in shadow row
            strategy="derived",
        )
        prompt = _capture_prompt(["b", "Adoptado"])

        rc, captured, _stdout = _run_reconcile(
            argv=["reconcile", "--interactive"],
            shadow_rows=[row],
            prompt=prompt,
        )

        assert rc == 0
        # Web-table UPDATE for animales.current_state. The
        # query text is case-sensitive (the production emitter
        # uppercases ``UPDATE``); we use ``.upper()`` on both
        # sides so the substring check is robust to the
        # actual casing of the SQL.
        web_updates = [
            c
            for c in captured
            if "UPDATE ANIMALES" in c.get("query", "").upper()
            and "current_state" in c.get("query", "").lower()
        ]
        assert len(web_updates) == 1, (
            f"accept derived must issue exactly one UPDATE animales; "
            f"got {len(web_updates)}: {web_updates!r}"
        )
        params = web_updates[0].get("params", [])
        # Param order: new value, then web_pk.
        assert params[0] == "Adoptado", f"new value must be 'Adoptado'; got {params[0]!r}"
        assert params[1] == "00000000-0000-0000-0000-0000000000aa"
        # Shadow-state UPDATE flips status to matched.
        shadow_updates = [
            c
            for c in captured
            if "UPDATE web_only_feature_shadow" in c.get("query", "")
            and "reconciliation_status = %s" in c.get("query", "")
        ]
        assert len(shadow_updates) == 1, (
            f"accept derived must flip shadow row to matched; "
            f"got {len(shadow_updates)}: {shadow_updates!r}"
        )
        assert shadow_updates[0].get("params", [])[0] == "matched"

    def test_interactive_defer_leaves_status(self) -> None:
        """Operator picks ``(c) defer`` → the case stays
        ``needs_review``; no UPDATE is issued.

        One pending row. The prompt queue is ``["c"]``. Assertions:
        - exit 0.
        - no ``UPDATE web_only_feature_shadow`` is issued (the
          shadow row keeps its ``needs_review`` status).
        - no ``UPDATE {web_table}`` is issued (defer writes nothing).
        """
        row = _needs_review_row(
            table_name="voluntarios",
            legacy_pk="v-1",
            web_pk="00000000-0000-0000-0000-000000000001",
            web_column="DNI",
        )
        prompt = _capture_prompt(["c"])

        rc, captured, _stdout = _run_reconcile(
            argv=["reconcile", "--interactive"],
            shadow_rows=[row],
            prompt=prompt,
        )

        assert rc == 0
        # No UPDATE statements of any kind.
        for call in captured:
            query = call.get("query", "").upper()
            assert "UPDATE" not in query, f"defer must not issue any UPDATE; got: {call!r}"
            assert "INSERT" not in query, f"defer must not issue any INSERT; got: {call!r}"

    def test_interactive_quit_exits_early(self) -> None:
        """Operator picks ``(q) quit`` on the first case → the CLI
        returns 0 and does NOT process the remaining rows.

        Two pending rows. The prompt queue is ``["q"]``. The first
        case is shown, the operator quits, the second case is
        never displayed and the shadow state is untouched.
        """
        rows = [
            _needs_review_row(legacy_pk="v-1", web_column="DNI", table_name="voluntarios"),
            _needs_review_row(legacy_pk="v-2", web_column="DNI", table_name="voluntarios"),
        ]
        prompt = _capture_prompt(["q"])

        stream = io.StringIO()
        rc, captured, stdout = _run_reconcile(
            argv=["reconcile", "--interactive"],
            shadow_rows=rows,
            prompt=prompt,
            stream=stream,
        )

        assert rc == 0
        # The first case header IS shown; the second never is.
        assert stdout.count("legacy_pk:               v-1") == 1
        assert "legacy_pk:               v-2" not in stdout
        # No UPDATE / INSERT issued for either row.
        for call in captured:
            query = call.get("query", "").upper()
            assert "UPDATE" not in query, f"quit must not write; got: {call!r}"
            assert "INSERT" not in query, f"quit must not write; got: {call!r}"

    def test_interactive_unknown_choice_is_skipped(self) -> None:
        """Operator types an unrecognised choice (not a/b/c/q) → the
        case is skipped with a warning; no writes are issued.

        One pending row. The prompt queue is ``["x", "q"]``: the
        first call returns ``"x"`` (unknown), the second returns
        ``"q"`` so the loop exits cleanly. The test asserts the
        shadow state was never touched and the warning went to
        stderr.
        """
        row = _needs_review_row(
            table_name="voluntarios",
            legacy_pk="v-1",
            web_column="DNI",
        )
        prompt = _capture_prompt(["x", "q"])

        rc, captured, _stdout = _run_reconcile(
            argv=["reconcile", "--interactive"],
            shadow_rows=[row],
            prompt=prompt,
        )

        assert rc == 0
        for call in captured:
            query = call.get("query", "").upper()
            assert "UPDATE" not in query, f"unknown choice must not write; got: {call!r}"
            assert "INSERT" not in query, f"unknown choice must not write; got: {call!r}"


# --- T5.8: --table + --since ---------------------------------------------


class TestReconcileFilters:
    """``--table`` and ``--since`` flow into the
    ``ShadowStateRepository.list_needs_review`` kwargs.
    """

    def test_table_and_since_passed_to_repository(self) -> None:
        """``--table voluntarios --since 2026-06-20T00:00:00+00:00``
        are forwarded to ``ShadowStateRepository.list_needs_review``.

        The mock returns a single matching row. The assertion
        inspects the SQL emitted by ``list_needs_review`` to confirm
        both filters are present (the WHERE clause carries the
        ``table_name = %s`` and ``last_legacy_snapshot_at >= %s``
        predicates) and the params carry the values in the right
        order.
        """
        row = _needs_review_row(
            table_name="voluntarios",
            legacy_pk="v-1",
            web_column="DNI",
        )

        rc, captured, _stdout = _run_reconcile(
            argv=[
                "reconcile",
                "--check-only",
                "--table",
                "voluntarios",
                "--since",
                "2026-06-20T00:00:00+00:00",
            ],
            shadow_rows=[row],
        )

        assert rc == 0
        # Find the list_needs_review SELECT.
        list_queries = [
            c
            for c in captured
            if "web_only_feature_shadow" in c.get("query", "")
            and "WHERE" in c.get("query", "").upper()
            and "needs_review" in c.get("query", "")
        ]
        assert len(list_queries) == 1, (
            f"expected exactly one list_needs_review SELECT; "
            f"got {len(list_queries)}: {list_queries!r}"
        )
        sql = list_queries[0]["query"]
        # WHERE carries both filter predicates.
        assert "table_name = %s" in sql, f"--table filter missing in SQL: {sql!r}"
        assert "last_legacy_snapshot_at >= %s" in sql, f"--since filter missing in SQL: {sql!r}"
        # Params carry the values in the right order.
        params = list_queries[0].get("params", [])
        assert "voluntarios" in params, f"--table value not in params: {params!r}"
        assert "2026-06-20T00:00:00+00:00" in params, f"--since value not in params: {params!r}"

    def test_invalid_since_returns_exit_2(self) -> None:
        """``--since not-a-date`` is rejected with exit code 2 BEFORE
        any SQL is issued.

        The CLI validates the ISO-8601 format client-side so a typo
        surfaces as a clean exit-2 error (design.md §7) instead of
        silently returning an empty list. The mock client is wired
        so any captured SQL would fail the assertion below.
        """
        rc, captured, _stdout = _run_reconcile(
            argv=["reconcile", "--check-only", "--since", "not-a-date"],
            shadow_rows=[],
        )

        assert rc == 2, f"invalid --since must exit 2; got {rc}"
        # Validation rejects before any SQL is issued.
        assert captured == [], f"invalid --since must not issue SQL; got {captured!r}"
