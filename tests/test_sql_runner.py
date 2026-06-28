"""Tests for ``migration.sql_runner``.

The runner records applied migrations in ``web_sql_migrations`` and
re-applies any ``*.sql`` file under ``app/core/migration/sql/`` that is
not yet recorded. The contract: idempotent across restarts, no crash
on the response shape InsForge actually returns.

The runner is exercised directly with a fake ``InsForgeClient`` so the
shape of the response from ``client.execute_sql`` is under our
control. The list query (``SELECT filename FROM web_sql_migrations``)
returns rows in two shapes observed in production:

- List of dicts: ``[{"filename": "001_drop.sql"}, ...]``
- Flat list of strings: ``["001_drop.sql", ...]`` (InsForge collapses
  single-column SELECTs to scalars in some response modes)

The runner must accept both so the first container start on a fresh
database does not crash the lifespan with TypeError.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.migration.sql_runner import apply_sql_migrations


class _FakeClient:
    """Minimal ``InsForgeClient``-shaped stub for the runner.

    Records every ``execute_sql`` call and returns a configurable
    response for the list query so each test can pin the shape it
    cares about. Other queries (bootstrap, migration body, record)
    get a benign empty list.
    """

    def __init__(self, list_response: Any) -> None:
        self._list_response = list_response
        self.calls: list[tuple[str, list[Any] | None]] = []

    def execute_sql(
        self, query: str, params: list[Any] | None = None
    ) -> Any:
        self.calls.append((query, params))
        if "FROM web_sql_migrations" in query and query.lstrip().upper().startswith(
            "SELECT"
        ):
            return self._list_response
        return []


@pytest.fixture
def migrations_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the runner at an isolated ``sql/`` directory with one migration."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "001_first.sql").write_text(
        "-- 001_first.sql (no-op for the runner contract test)",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.core.migration.sql_runner._MIGRATIONS_DIR", sql_dir
    )
    return sql_dir


def test_runner_accepts_list_of_dicts(
    migrations_dir: Path,
) -> None:
    """The runner treats rows as dicts when InsForge returns the object form."""
    client = _FakeClient(list_response=[{"filename": "001_first.sql"}])

    applied = apply_sql_migrations(client)

    assert applied == [], (
        f"001_first.sql is recorded as applied; expected no-op, got: {applied!r}"
    )


def test_runner_accepts_flat_list_of_strings(
    migrations_dir: Path,
) -> None:
    """The runner does NOT crash when InsForge returns ``["001_first.sql"]``.

    Regression test for the deploy failure (commit d8b37ae via merge
    c1bde47 introduced a row shape that broke the list comprehension):
    the list query collapsed single-column rows to scalars, so the
    comprehension ``row["filename"]`` raised
    ``TypeError: string indices must be integers, not 'str'`` and the
    new container failed its healthcheck, rolling back to the prior
    container. The runner must accept the flat shape without the
    lifespan crashing.
    """
    client = _FakeClient(list_response=["001_first.sql"])

    applied = apply_sql_migrations(client)

    assert applied == [], (
        f"001_first.sql is recorded as applied; expected no-op, got: {applied!r}"
    )


def test_runner_applies_pending_when_nothing_recorded(
    migrations_dir: Path,
) -> None:
    """When nothing is recorded, the runner applies the pending file once."""
    client = _FakeClient(list_response=[])

    applied = apply_sql_migrations(client)

    assert applied == ["001_first.sql"], (
        f"expected 001_first.sql to be applied, got: {applied!r}"
    )
    # Bootstrap + list + migration body + record = 4 calls.
    assert len(client.calls) == 4, (
        f"expected 4 execute_sql calls (bootstrap, list, body, record), "
        f"got {len(client.calls)}: {[c[0][:60] for c in client.calls]!r}"
    )
    # The recorded migration uses parameterized INSERT with the filename.
    record_call = next(c for c in client.calls if "INSERT" in c[0])
    assert record_call[1] == ["001_first.sql"]


def test_runner_does_not_reapply_already_recorded_migration(
    migrations_dir: Path,
) -> None:
    """A recorded migration is skipped, no body or record INSERT."""
    client = _FakeClient(list_response=["001_first.sql"])

    applied = apply_sql_migrations(client)

    assert applied == [], (
        f"001_first.sql is recorded; expected no re-apply, got: {applied!r}"
    )
    # Bootstrap + list + (no body, no record) = 2 calls.
    assert len(client.calls) == 2, (
        f"expected 2 execute_sql calls (bootstrap, list), "
        f"got {len(client.calls)}: {[c[0][:60] for c in client.calls]!r}"
    )
