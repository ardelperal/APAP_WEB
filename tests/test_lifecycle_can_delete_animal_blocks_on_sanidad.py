"""Use-case tests for ``can_delete_animal`` (LIFECYCLE-03 PR-C).

The use case returns a structured ``CanDeleteResult`` with the offending
table name in the ``reason`` field. Mirrors the legacy ``AnimalBorrable``
contract documented at ``docs/legacy-lifecycle-transition-rules.md:108-113``
where the only "deletable" animal is one with no rows in any of the
``entradas`` / ``acogidas`` / ``adopciones`` / ``actuaciones_sanitarias``
/ ``terapias`` tables.

PR-C surfaces the missing-table case as
``reason='sanidad_table_missing'`` / ``'terapias_table_missing'`` — the
use case must NEVER raise on a missing health/therapy table.
"""
from __future__ import annotations

import pytest


class _FakeSqlExecutor:
    """Stub executor that returns canned counts per table.

    The can_delete use case issues one COUNT(*) per table it inspects;
    the fake matches on the table name in the SQL string and returns
    the configured count. A ``table_error`` table name triggers the
    missing-table branch (use case translates SQL errors into a
    ``<table>_table_missing`` reason).
    """

    def __init__(
        self,
        counts: dict[str, int] | None = None,
        table_error: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, list]] = []
        self._counts: dict[str, int] = dict(counts or {})
        self._table_error = table_error

    def execute_sql(
        self, query: str, params: list | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, list(params or [])))
        normalized = query.strip().upper()
        if self._table_error and self._table_error.upper() in normalized:
            raise RuntimeError(f"relation {self._table_error!r} does not exist")
        for table, count in self._counts.items():
            if f"FROM {table.upper()}" in normalized or (
                f"FROM {table}" in query and f"FROM {table}_" not in query
            ):
                return [{"count": count}] if "COUNT" in normalized else []
        return []


def test_can_delete_animal_allows_when_no_rows_in_any_table() -> None:
    """Happy path: every table returns 0 rows → can_delete=True."""
    from app.modules.lifecycle.application.can_delete_animal import (
        CanDeleteResult,
        can_delete_animal,
    )

    executor = _FakeSqlExecutor(
        counts={
            "entradas": 0,
            "acogidas": 0,
            "adopciones": 0,
            "actuaciones_sanitarias": 0,
            "terapias": 0,
        },
    )
    result = can_delete_animal(executor, "animal-uuid-1")
    assert isinstance(result, CanDeleteResult)
    assert result.can_delete is True
    assert result.reason is None


def test_can_delete_animal_blocks_on_active_foster() -> None:
    """Acogida row → reason='acogida_row'."""
    from app.modules.lifecycle.application.can_delete_animal import (
        can_delete_animal,
    )

    executor = _FakeSqlExecutor(
        counts={
            "entradas": 0,
            "acogidas": 1,
            "adopciones": 0,
            "actuaciones_sanitarias": 0,
            "terapias": 0,
        },
    )
    result = can_delete_animal(executor, "animal-uuid-2")
    assert result.can_delete is False
    assert result.reason == "acogida_row"


def test_can_delete_animal_blocks_on_active_intake() -> None:
    """Entrada row → reason='entrada_row'."""
    from app.modules.lifecycle.application.can_delete_animal import (
        can_delete_animal,
    )

    executor = _FakeSqlExecutor(
        counts={
            "entradas": 1,
            "acogidas": 0,
            "adopciones": 0,
            "actuaciones_sanitarias": 0,
            "terapias": 0,
        },
    )
    result = can_delete_animal(executor, "animal-uuid-3")
    assert result.can_delete is False
    assert result.reason == "entrada_row"


def test_can_delete_animal_blocks_on_active_adoption() -> None:
    """Adopcion row → reason='adopcion_row'."""
    from app.modules.lifecycle.application.can_delete_animal import (
        can_delete_animal,
    )

    executor = _FakeSqlExecutor(
        counts={
            "entradas": 0,
            "acogidas": 0,
            "adopciones": 1,
            "actuaciones_sanitarias": 0,
            "terapias": 0,
        },
    )
    result = can_delete_animal(executor, "animal-uuid-4")
    assert result.can_delete is False
    assert result.reason == "adopcion_row"


def test_can_delete_animal_blocks_on_sanidad_row() -> None:
    """Pin: sanidad row → reason='sanidad_row'."""
    from app.modules.lifecycle.application.can_delete_animal import (
        can_delete_animal,
    )

    executor = _FakeSqlExecutor(
        counts={
            "entradas": 0,
            "acogidas": 0,
            "adopciones": 0,
            "actuaciones_sanitarias": 1,
            "terapias": 0,
        },
    )
    result = can_delete_animal(executor, "animal-uuid-5")
    assert result.can_delete is False
    assert result.reason == "sanidad_row"


def test_can_delete_animal_blocks_on_terapia_row() -> None:
    """Pin: terapia row → reason='terapia_row'."""
    from app.modules.lifecycle.application.can_delete_animal import (
        can_delete_animal,
    )

    executor = _FakeSqlExecutor(
        counts={
            "entradas": 0,
            "acogidas": 0,
            "adopciones": 0,
            "actuaciones_sanitarias": 0,
            "terapias": 1,
        },
    )
    result = can_delete_animal(executor, "animal-uuid-6")
    assert result.can_delete is False
    assert result.reason == "terapia_row"


def test_can_delete_animal_returns_sanidad_table_missing_when_table_absent() -> None:
    """Missing ``actuaciones_sanitarias`` → reason='sanidad_table_missing'."""
    from app.modules.lifecycle.application.can_delete_animal import (
        can_delete_animal,
    )

    executor = _FakeSqlExecutor(
        counts={
            "entradas": 0,
            "acogidas": 0,
            "adopciones": 0,
            "terapias": 0,
        },
        table_error="actuaciones_sanitarias",
    )
    result = can_delete_animal(executor, "animal-uuid-7")
    assert result.can_delete is False
    assert result.reason == "sanidad_table_missing"


def test_can_delete_animal_returns_terapias_table_missing_when_table_absent() -> None:
    """Missing ``terapias`` → reason='terapias_table_missing'."""
    from app.modules.lifecycle.application.can_delete_animal import (
        can_delete_animal,
    )

    executor = _FakeSqlExecutor(
        counts={
            "entradas": 0,
            "acogidas": 0,
            "adopciones": 0,
            "actuaciones_sanitarias": 0,
        },
        table_error="terapias",
    )
    result = can_delete_animal(executor, "animal-uuid-8")
    assert result.can_delete is False
    assert result.reason == "terapias_table_missing"


def test_can_delete_animal_reraises_on_non_missing_table_error() -> None:
    """SQL errors that are NOT missing-table errors re-raise.

    The use case translates relation-not-found errors into
    ``<table>_table_missing`` reasons; every other SQL error must
    surface to the caller as an exception so transport / programming
    bugs are not masked as a "non-deletable" verdict.
    """
    from app.modules.lifecycle.application.can_delete_animal import (
        can_delete_animal,
    )

    class _RaisingSqlExecutor:
        def __init__(self) -> None:
            self.calls = 0

        def execute_sql(self, query: str, params: list | None = None) -> list:
            self.calls += 1
            raise RuntimeError("connection refused: not a missing-table error")

    executor = _RaisingSqlExecutor()
    with pytest.raises(RuntimeError, match="connection refused"):
        can_delete_animal(executor, "animal-uuid-9")
    assert executor.calls == 1, "use case must stop at the first failing table"


def test_can_delete_animal_reraises_when_bootstrap_table_is_missing() -> None:
    """Missing bootstrap table (entradas) re-raises — config error, not a verdict.

    ``entradas`` / ``acogidas`` / ``adopciones`` are part of the
    bootstrap. A missing one is a config error that must surface to
    the operator, never a deletability verdict.
    """
    from app.modules.lifecycle.application.can_delete_animal import (
        can_delete_animal,
    )

    executor = _FakeSqlExecutor(
        counts={},
        table_error="entradas",
    )
    with pytest.raises(RuntimeError, match="does not exist"):
        can_delete_animal(executor, "animal-uuid-10")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
