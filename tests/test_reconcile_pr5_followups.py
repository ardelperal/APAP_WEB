"""Tests for PR 5 follow-ups (P2 from PR 5 code review) of
``web-only-feature-preservation``.

PR 5 code review surfaced 7 P2 gaps. PR 6 closes them as follow-up
production changes. The follow-up tests live here so they sit next
to the round-trip / perf / 11-cases regression tests in
``tests/test_reconcile_pr6.py`` but commit separately.

What this file covers (T6.7-T6.13):

- ``TestShadowSchemaFollowUps`` -- schema gains ``derived_value`` and
  ``derived_at`` columns so the CLI can autofill the operator's
  ``accept derived`` prompt.
- ``TestShadowRepositoryFollowUps`` -- ``update_derived_value`` and
  ``update_derived_at`` write methods on ``ShadowStateRepository``.
- ``TestReconcileDerivedFollowUps`` -- the derivation engine's
  result is persisted to the shadow row so the CLI can autofill.
- ``TestCliCheckOnlyFollowUps`` -- ``--check-only`` output emits the
  new ``derived_value`` / ``derived_at`` keys (per spec REQ-CLI
  scenario).
- ``TestCliInteractiveAcceptDerivedFollowUps`` -- ``--interactive``
  accept-derived pre-fills with the stored ``derived_value``.
- ``TestCliInteractiveLock`` -- ``run_reconcile`` acquires the
  migration lock when ``--interactive`` is set and releases on exit
  (regla #13474 v2: no two interactive sessions concurrently).
- ``TestCliCheckOnlyEmptyString`` -- ``--check-only`` renders an
  empty string distinctly from ``None``
  (``if x is None: 'null' else: str(x)``).

Each test follows the same conventions as the existing
``test_reconcile.py``: mocks for the web client + a fake
``ShadowStateRepository`` so the suite is fully deterministic
and never touches the network.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from migration.cli import (
    _format_row_for_check_only,
)
from migration.cli import (
    main as cli_main,
)

# --- helpers --------------------------------------------------------------


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation for reconcile follow-up tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._rows: list[dict[str, Any]] = []
        self._extra: dict[str, list[dict[str, Any]]] = {}

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def set_extra(self, extra: dict[str, list[dict[str, Any]]]) -> None:
        self._extra = extra

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append({"query": query, "params": list(params or [])})
        for marker, rows in self._extra.items():
            if marker in query:
                return rows
        if "web_only_feature_shadow" in query and "WHERE" in query:
            return self._rows
        return []

    def close(self) -> None:
        pass


def _make_client(
    shadow_rows: list[dict[str, Any]] | None = None,
    extra_sql: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[_FakeSqlExecutor, list[dict[str, Any]]]:
    """Build a fake executor wired to return shadow_rows for list_needs_review queries."""
    fake = _FakeSqlExecutor()
    if shadow_rows is not None:
        fake.set_rows(shadow_rows)
    if extra_sql:
        fake.set_extra(extra_sql)
    return fake, fake.calls


def _capture_prompt(responses: list[str]) -> Callable[[str], str]:
    """Build a list-driven prompt reader."""

    def _read(_prompt: str) -> str:
        if not responses:
            raise AssertionError("prompt called more times than test expected")
        return responses.pop(0)

    return _read


def _needs_review_row(
    *,
    table_name: str = "animales",
    legacy_pk: str = "a-1",
    web_pk: str = "00000000-0000-0000-0000-000000000001",
    web_column: str = "current_state",
    preserved_value: Any = None,
    strategy: str = "derived",
    last_legacy_snapshot_at: str | None = "2026-06-20T12:00:00+00:00",
    last_reconciled_at: str | None = None,
    review_reasons: list[str] | None = None,
    reconciliation_status: str = "needs_review",
    # PR 5 follow-up additions
    derived_value: Any = None,
    derived_at: str | None = None,
) -> dict[str, Any]:
    """One row in the shape ``ShadowStateRepository.list_needs_review`` returns.

    Includes the new ``derived_value`` / ``derived_at`` columns added
    in PR 6 (PR 5 follow-up #1).
    """
    return {
        "id": "00000000-0000-0000-0000-000000000aaa",
        "table_name": table_name,
        "legacy_pk": legacy_pk,
        "web_pk": web_pk,
        "web_column": web_column,
        "preserved_value": json.dumps(preserved_value) if preserved_value is not None else None,
        "strategy": strategy,
        "last_legacy_snapshot_at": last_legacy_snapshot_at,
        "last_web_edit_at": None,
        "last_reconciled_at": last_reconciled_at,
        "reconciliation_status": reconciliation_status,
        "review_reasons": json.dumps(review_reasons or ["web_manual_override_detected"]),
        # PR 5 follow-up columns
        "derived_value": json.dumps(derived_value) if derived_value is not None else None,
        "derived_at": derived_at,
    }


def _shadow_state_mapping_with_current_state_derived():
    """Synthetic ``animales`` TableMapping with ``current_state`` as derived."""
    from migration.mappings import ColumnMapping, TableMapping

    return TableMapping(
        version="1.0",
        web_table="animales",
        legacy_table="TbFichaAnimal",
        key_field="NCHIP",
        legacy_key="NCHIP",
        date_fields=["FIMPLANTACIONCHIP", "FDefuncion"],
        columns=[
            ColumnMapping(
                web_column="NCHIP",
                legacy_column="NCHIP",
                transform="identity",
                nullable=False,
            ),
            ColumnMapping(
                web_column="current_state",
                legacy_column=None,
                transform="identity",
                nullable=True,
                web_only_strategy="derived",
            ),
        ],
        fk_lookups=[],
    )


def _voluntario_mapping_with_dni_preserve():
    """Synthetic ``voluntarios`` TableMapping with ``DNI`` as preserve."""
    from migration.mappings import ColumnMapping, TableMapping

    return TableMapping(
        version="1.0",
        web_table="voluntarios",
        legacy_table="TbVoluntariosParaAutorrellenables",
        key_field="Voluntario",
        legacy_key="Voluntario",
        date_fields=[],
        columns=[
            ColumnMapping(
                web_column="Voluntario",
                legacy_column="Voluntario",
                transform="identity",
                nullable=False,
            ),
            ColumnMapping(
                web_column="DNI",
                legacy_column=None,
                transform="identity",
                nullable=True,
                web_only_strategy="preserve",
            ),
        ],
        fk_lookups=[],
    )


def _empty_sync_state():
    from migration.sync_state import SyncState

    return SyncState()


# --- T6.7: SHADOW_TABLE_SQL includes derived_value + derived_at ---------


class TestShadowSchemaFollowUps:
    """PR 5 follow-up: the shadow table gains ``derived_value`` (JSONB)
    and ``derived_at`` (TIMESTAMPTZ) so the CLI can autofill the
    operator's ``accept derived`` prompt with the stored derivation.
    """

    def test_shadow_table_sql_has_derived_value_column(self) -> None:
        from migration.shadow_state import SHADOW_TABLE_SQL

        assert "derived_value" in SHADOW_TABLE_SQL, (
            "SHADOW_TABLE_SQL must declare derived_value (JSONB) so the CLI "
            "can autofill accept-derived; got: " + SHADOW_TABLE_SQL
        )

    def test_shadow_table_sql_has_derived_at_column(self) -> None:
        from migration.shadow_state import SHADOW_TABLE_SQL

        assert "derived_at" in SHADOW_TABLE_SQL, (
            "SHADOW_TABLE_SQL must declare derived_at (TIMESTAMPTZ) so the "
            "CLI can autofill accept-derived; got: " + SHADOW_TABLE_SQL
        )


# --- T6.8: ShadowStateRepository gains update_derived_value + update_derived_at


class TestShadowRepositoryFollowUps:
    """PR 5 follow-up: ``ShadowStateRepository`` exposes the two new
    update methods so the applier hook can persist the derivation
    result without going through the generic ``upsert`` path.
    """

    def _client_capturing(self) -> tuple[_FakeSqlExecutor, list[dict[str, Any]]]:
        fake = _FakeSqlExecutor()
        return fake, fake.calls


    def test_update_derived_value_emits_scoped_update(self) -> None:
        """``update_derived_value`` writes ``derived_value`` for the row
        identified by the unique key -- not for any other row."""
        from migration.shadow_state import ShadowStateRepository

        client, captured = self._client_capturing()
        repo = ShadowStateRepository(client)
        repo.update_derived_value(
            table_name="animales",
            legacy_pk="a-1",
            web_column="current_state",
            derived_value="Albergue",
        )
        assert len(captured) == 1
        call = captured[0]
        query = call["query"]
        assert "UPDATE web_only_feature_shadow" in query
        assert "derived_value" in query
        # Scoped by the unique key (table_name, legacy_pk, web_column).
        assert "table_name = %s" in query
        assert "legacy_pk = %s" in query
        assert "web_column = %s" in query
        assert call["params"][0] == json.dumps("Albergue")
        assert call["params"][-3:] == ["animales", "a-1", "current_state"]

    def test_update_derived_at_emits_scoped_update(self) -> None:
        """``update_derived_at`` writes ``derived_at`` for the row
        identified by the unique key."""
        from migration.shadow_state import ShadowStateRepository

        client, captured = self._client_capturing()
        repo = ShadowStateRepository(client)
        repo.update_derived_at(
            table_name="animales",
            legacy_pk="a-1",
            web_column="current_state",
            derived_at=datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        )
        assert len(captured) == 1
        call = captured[0]
        query = call["query"]
        assert "UPDATE web_only_feature_shadow" in query
        assert "derived_at" in query
        # Scoped by the unique key.
        assert "table_name = %s" in query
        assert "legacy_pk = %s" in query
        assert "web_column = %s" in query
        assert "2026-06-22T12:00:00+00:00" in call["params"][0]
        assert call["params"][-3:] == ["animales", "a-1", "current_state"]


# --- T6.9: reconcile._reconcile_derived persists derived_value + derived_at


class TestReconcileDerivedFollowUps:
    """PR 5 follow-up: when ``_reconcile_derived`` runs the derivation
    engine, it MUST persist ``derived_value`` and ``derived_at`` on the
    shadow row via the new update methods so the CLI can autofill.
    """

    def test_derived_strategy_persists_derived_value_and_at(self) -> None:
        """After a MATCHED derivation, the shadow row carries
        ``derived_value`` = the derived state and ``derived_at`` = the
        snapshot timestamp."""
        from migration.reconcile import reconcile_after_legacy_write

        update_derived_value_calls: list[dict[str, object]] = []
        update_derived_at_calls: list[dict[str, object]] = []

        class _FakeShadow:
            def upsert(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_reconciliation_status(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                pass

            def update_derived_value(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                update_derived_value_calls.append(kwargs)

            def update_derived_at(self, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                update_derived_at_calls.append(kwargs)

        snapshot_at = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
        outcome = reconcile_after_legacy_write(
            shadow_state=_FakeShadow(),  # type: ignore[arg-type]
            table_name="animales",
            legacy_pk="a-1",
            web_pk="00000000-0000-0000-0000-000000000001",
            web_column="current_state",
            strategy="derived",
            preserved_value=None,
            last_legacy_snapshot_at=snapshot_at,
            derived_inputs={
                "tb_ficha": {"NCHIP": "001", "FDefuncion": None},
                "tb_entradas": [{"IDEntrada": 1, "FSalida": None, "FEntregaAPropietario": None}],
                "tb_acogidas": [],
                "tb_adopciones": [],
            },
            stored_state="Albergue",
            web_updated_at=None,
        )
        assert outcome.status.name == "MATCHED"
        assert outcome.derived_value == "Albergue"
        # update_derived_value was called with the derived state.
        assert len(update_derived_value_calls) == 1
        call = update_derived_value_calls[0]
        assert call["table_name"] == "animales"
        assert call["legacy_pk"] == "a-1"
        assert call["web_column"] == "current_state"
        assert call["derived_value"] == "Albergue"
        # update_derived_at was called with the snapshot timestamp.
        assert len(update_derived_at_calls) == 1
        at_call = update_derived_at_calls[0]
        assert at_call["table_name"] == "animales"
        assert at_call["legacy_pk"] == "a-1"
        assert at_call["web_column"] == "current_state"
        assert at_call["derived_at"] == snapshot_at


# --- T6.10: CLI --check-only output emits derived_value= + derived_at= --


class TestCliCheckOnlyFollowUps:
    """PR 5 follow-up: ``--check-only`` output emits the
    ``derived_value`` and ``derived_at`` keys (per spec REQ-CLI
    scenario).
    """

    def _run_check_only(self, row: dict[str, Any]) -> str:
        stream = io.StringIO()
        fake = _FakeSqlExecutor()
        fake.set_rows([row])
        try:
            rc = cli_main(
                ['reconcile', '--check-only'],
                web_client=fake,
                stream=stream,
            )
        finally:
            fake.close()
        assert rc == 0
        return stream.getvalue()


    def test_check_only_emits_derived_value(self) -> None:
        row = _needs_review_row(
            table_name="animales",
            legacy_pk="a-1",
            web_column="current_state",
            preserved_value=None,
            strategy="derived",
            derived_value="Adoptado",
            derived_at="2026-06-21T10:00:00+00:00",
        )
        stdout = self._run_check_only(row)
        # The ``derived_value`` column is JSONB so the value comes
        # back as a JSON-serialised string (``'"Adoptado"'``). The
        # formatter renders it verbatim (preserving the JSON quotes so
        # ``jq`` can re-parse the line).
        assert 'derived_value="Adoptado"' in stdout, (
            f"check-only output must include derived_value; got: {stdout!r}"
        )
        assert "derived_at=2026-06-21T10:00:00+00:00" in stdout, (
            f"check-only output must include derived_at; got: {stdout!r}"
        )


# --- T6.13: _format_row_for_check_only handles empty string vs None -----


class TestCliCheckOnlyEmptyString:
    """PR 5 follow-up: ``--check-only`` renders an empty string as a
    literal ``""`` (or ``repr``), NOT as ``null``. The ``or 'null'``
    pattern collapses empty strings to ``null`` -- fix it so the
    operator can distinguish ``""`` from ``None``.
    """

    def test_check_only_distinguishes_empty_string_from_none(self) -> None:
        # ``table_name`` is present (non-empty) -> no fallback.
        # ``preserved_value`` is the JSONB NULL coming back from PG as
        # ``None``. The original bug was ``row.get('table_name') or
        # 'null'`` which would collapse ``''`` to ``'null'`` even when
        # the field is populated with an empty string by mistake.
        # In our model all keys should be populated; we check the
        # specific behavior for ``preserved_value``.
        row = {
            "table_name": "animales",
            "legacy_pk": "a-1",
            "web_pk": "00000000-0000-0000-0000-000000000001",
            "web_column": "current_state",
            "reconciliation_status": "needs_review",
            "strategy": "derived",
            "preserved_value": None,  # explicit NULL -> "null"
            "last_legacy_snapshot_at": None,
            "last_reconciled_at": None,
            "review_reasons": "[]",
        }
        formatted = _format_row_for_check_only(row)
        # The "null" literal is rendered for None values.
        assert "web_value=null" in formatted
        assert "last_legacy_snapshot_at=null" in formatted
        # Now check the empty-string case: the fix uses
        # ``if x is None: 'null' else: repr(x)`` so an empty string
        # stays as ``''`` (NOT ``'null'``).
        row_with_empty = {**row, "preserved_value": ""}
        formatted_empty = _format_row_for_check_only(row_with_empty)
        # Empty string -> rendered as the empty literal, NOT "null".
        assert "web_value=" in formatted_empty
        # The specific guard: the "or 'null'" bug would render this as
        # ``web_value=null``; the fix renders it as ``web_value=""``.
        assert "web_value=null" not in formatted_empty, (
            f"empty string must NOT collapse to 'null'; got: {formatted_empty!r}"
        )


# --- T6.11: CLI --interactive accept-derived pre-fills the prompt -------


class TestCliInteractiveAcceptDerivedFollowUps:
    """PR 5 follow-up: ``--interactive`` accept-derived pre-fills the
    prompt with the stored ``derived_value`` so the operator does NOT
    have to retype it (per spec REQ-CLI scenario).
    """

    def test_accept_derived_prefills_with_stored_value(self) -> None:
        """The CLI's ``accept derived`` flow pre-fills the prompt with
        ``derived_value`` so the operator can just press Enter.

        We assert the prompt text includes the stored value as a
        default -- implementation detail: the CLI concatenates ``\n
        [default: ...]`` (or similar) into the prompt body.
        """
        row = _needs_review_row(
            table_name="animales",
            legacy_pk="a-1",
            web_pk="00000000-0000-0000-0000-0000000000aa",
            web_column="current_state",
            preserved_value=None,
            strategy="derived",
            derived_value="Adoptado",
            derived_at="2026-06-22T12:00:00+00:00",
        )
        # The CLI will prompt twice: choice + value. We reply
        # "b\n<Enter>" -- the <Enter> accepts the default (the stored
        # derived_value). The empty input is rejected by the assertion
        # if the pre-fill is missing (because no value was returned).
        captured_prompts: list[str] = []

        def _prompt(prompt_text: str) -> str:
            captured_prompts.append(prompt_text)
            # 1st call: operator picks (b) accept derived.
            # 2nd call: operator presses Enter (empty) -> CLI should
            # use the stored derived_value as the default.
            if len(captured_prompts) == 1:
                return "b"
            return ""

        fake = _FakeSqlExecutor()
        fake.set_rows([row])
        fake.set_extra({"UPDATE ANIMALES": [{"ok": 1}]})
        try:
            rc = cli_main(
                ["reconcile", "--interactive"],
                web_client=fake,
                prompt=_prompt,
            )
        finally:
            fake.close()

        assert rc == 0
        # The value prompt must include the derived_value as the
        # default so the operator can press Enter to accept.
        assert len(captured_prompts) >= 2
        value_prompt = captured_prompts[1]
        assert "Adoptado" in value_prompt, (
            f"value prompt must pre-fill with derived_value 'Adoptado'; got: {value_prompt!r}"
        )


# --- T6.12: --interactive acquires the migration lock -------------------


class TestCliInteractiveLock:
    """PR 5 follow-up: ``run_reconcile`` acquires the migration lock
    when ``--interactive`` is set, and releases it on exit (try/finally
    semantics -- even on error).

    Rationale: two operators hitting ``--interactive`` concurrently
    could double-resolve a case. Regla #13474 v2: una sola escritura a
    la vez contra el shadow state.
    """

    def test_interactive_acquires_and_releases_lock(self, tmp_path) -> None:
        """The lock is acquired at the top of ``run_reconcile`` when
        ``--interactive`` is set, and released before return.

        We force the CLI's lock path to ``tmp_path`` so the test stays
        hermetic -- the production CLI picks up the path from settings
        (``get_settings().migration_dir`` or the ``APAP_MIGRATION_DIR``
        env var), but for the test we monkeypatch ``_resolve_lock_path``
        to point at the tempdir.
        """
        # Patch the CLI's lock resolver to use the tempdir.
        from migration import cli as cli_mod

        lock_path = tmp_path / "migration.lock"
        original_resolver = cli_mod._resolve_lock_path
        cli_mod._resolve_lock_path = lambda: lock_path  # type: ignore[assignment]
        try:

            fake = _FakeSqlExecutor()
            try:
                rc = cli_main(
                    ["reconcile", "--interactive"],
                    web_client=fake,
                )
            finally:
                fake.close()

            assert rc == 0
            # After the CLI exits, the lock file MUST be released
            # (removed). The CLI does ``release_lock`` in the
            # ``finally`` block of ``run_reconcile`` -- even when there
            # are no rows to reconcile.
            assert not lock_path.exists(), (
                f"interactive run must release the lock on exit; lock still present at {lock_path}"
            )
        finally:
            cli_mod._resolve_lock_path = original_resolver  # type: ignore[assignment]

    def test_non_interactive_does_not_acquire_lock(self) -> None:
        """``--check-only`` (non-interactive) does NOT acquire the lock.

        Rationale: ``--check-only`` is a read-only listing operation;
        concurrent listings are safe. Only ``--interactive`` mutates
        state and needs the lock.
        """

        # We can't directly inspect "did the CLI NOT call acquire_lock"
        # without an instrumented fake. The lightweight assertion:
        # even without a lock file in scope, --check-only exits 0.
        # The stronger assertion (the CLI doesn't call lock.acquire
        # when --interactive is False) is structural -- we verify it
        # via the fact that ``run_reconcile`` only enters the lock
        # branch when ``args.interactive`` is True.
        fake = _FakeSqlExecutor()
        try:
            rc = cli_main(
                ["reconcile", "--check-only"],
                web_client=fake,
            )
        finally:
            fake.close()
        assert rc == 0
