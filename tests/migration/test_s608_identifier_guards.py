"""Regression guards for the S608 triage of ``migration/`` (issue #387).

The triage classified all 11 ``S608`` sites under ``migration/`` as
structural: no operand originates from request data, because ``app/``
never imports ``migration/``. Eight of them already validated their SQL
identifiers through ``migration.apply._safe_table``; three did not.

These tests pin the three guards that were added, so a future edit that
drops the validation fails CI instead of review. Without them the
``# noqa: S608`` annotations would assert a property nothing checks —
AGENTS.md §32.P3, "rules declared without a gate".
"""

from __future__ import annotations

import pytest

from migration.adapters.insforge.web_reader_insforge_adapter import (
    _build_web_select_sql,
)
from migration.legacy_reader import TableSpec, _build_select_sql
from migration.ports.web_reader_port import WebTableSpec

# A payload that would break out of the identifier position if the
# builder interpolated it unchecked.
INJECTION = "animales; DROP TABLE animales --"


class TestLegacyReaderSelectGuard:
    """``migration/legacy_reader.py:_build_select_sql``."""

    def test_rejects_unsafe_table_name(self) -> None:
        spec = TableSpec(legacy_table=INJECTION, columns=("NCHIP",))
        with pytest.raises(ValueError, match="unsafe SQL identifier"):
            _build_select_sql(spec, offset=0, limit=10)

    def test_rejects_unsafe_column_name(self) -> None:
        spec = TableSpec(legacy_table="TbFichaAnimal", columns=(INJECTION,))
        with pytest.raises(ValueError, match="unsafe SQL identifier"):
            _build_select_sql(spec, offset=0, limit=10)

    def test_accepts_access_table_names(self) -> None:
        """The legacy side uses names like ``TbFichaAnimal``; they must pass."""
        spec = TableSpec(legacy_table="TbFichaAnimal", columns=("NCHIP", "Nombre"))
        assert _build_select_sql(spec, offset=0, limit=50) == (
            "SELECT TOP 50 NCHIP, Nombre FROM TbFichaAnimal"
        )

    def test_accepts_star_wildcard(self) -> None:
        """``reverse_apply/orchestrator.py`` passes ``columns=("*",)``."""
        spec = TableSpec(legacy_table="TbFichaAnimal", columns=("*",))
        assert _build_select_sql(spec, offset=0, limit=50) == (
            "SELECT TOP 50 * FROM TbFichaAnimal"
        )

    def test_where_fragment_is_still_honoured(self) -> None:
        """``where`` stays a trusted-caller fragment; behaviour unchanged."""
        spec = TableSpec(
            legacy_table="TbFichaAnimal",
            columns=("NCHIP",),
            where="FDefuncion IS NOT NULL",
        )
        assert _build_select_sql(spec, offset=0, limit=10) == (
            "SELECT TOP 10 NCHIP FROM TbFichaAnimal WHERE FDefuncion IS NOT NULL"
        )


class TestWebReaderSelectGuard:
    """``migration/adapters/insforge/web_reader_insforge_adapter.py``."""

    def test_rejects_unsafe_table_name(self) -> None:
        spec = WebTableSpec(web_table=INJECTION, columns=("id",))
        with pytest.raises(ValueError, match="unsafe SQL identifier"):
            _build_web_select_sql(spec)

    def test_rejects_unsafe_column_name(self) -> None:
        spec = WebTableSpec(web_table="animales", columns=(INJECTION,))
        with pytest.raises(ValueError, match="unsafe SQL identifier"):
            _build_web_select_sql(spec)

    def test_full_sync_sql_is_unchanged(self) -> None:
        spec = WebTableSpec(web_table="animales", columns=("id", "nombre"))
        assert _build_web_select_sql(spec) == "SELECT id, nombre FROM animales"

    def test_incremental_sync_sql_is_unchanged(self) -> None:
        """``since`` is a ``datetime``; ``isoformat()`` cannot inject."""
        from datetime import datetime

        spec = WebTableSpec(
            web_table="animales",
            columns=("id",),
            since=datetime(2026, 8, 5, 12, 0, 0),
        )
        assert _build_web_select_sql(spec) == (
            "SELECT id FROM animales WHERE updated_at > '2026-08-05T12:00:00'"
        )


class TestCliStatusGuard:
    """``migration/cli.py:run_status`` — the count query."""

    def test_rejects_unsafe_web_table(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import argparse
        import io
        from types import SimpleNamespace

        from migration import cli

        monkeypatch.setattr(
            cli, "load_mapping", lambda _table: SimpleNamespace(web_table=INJECTION)
        )

        class _RecordingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def execute_sql(self, sql: str, params: object = None) -> list[dict]:
                self.calls.append(sql)
                return [{"count": 0}]

        client = _RecordingClient()
        with pytest.raises(ValueError, match="unsafe SQL identifier"):
            cli.run_status(
                argparse.Namespace(table="animales"),
                web_client=client,  # type: ignore[arg-type]
                stream=io.StringIO(),
            )
        assert client.calls == [], "the guard must fire before any SQL is issued"
