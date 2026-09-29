"""Unit tests for ``app.core.schema_provisioning`` (issue #921, A-09).

The provisioning helper must never import ``tests.*`` at runtime: a
deployed wheel or image without the test tree must still be able to
provision the schema (the verify-fallback-ready gate, ad-hoc scripts
and the Coolify local backend depend on it).

These tests block every ``tests.*`` import via a meta-path finder and
exercise the provisioning path in isolation. Against the pre-#921
implementation both tests fail with ``ModuleNotFoundError`` because
``_load_conftest_catalogos`` pulls the catalog DDL from
``tests.integration.conftest``.
"""

from __future__ import annotations

import importlib.abc
import sys
from collections.abc import Iterator
from unittest import mock

import pytest

import app.core.schema_provisioning as schema_provisioning


class _BlockTestsImports(importlib.abc.MetaPathFinder):
    """Meta-path finder that makes every ``tests.*`` import fail."""

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname == "tests" or fullname.startswith("tests."):
            raise ImportError(f"tests tree is absent in production: {fullname}")
        return None


@pytest.fixture()
def no_tests_tree() -> Iterator[None]:
    """Simulate a deployment without the ``tests/`` package.

    Removes any already-imported ``tests.*`` modules from ``sys.modules``
    and installs a meta-path blocker so a fresh import of any ``tests.*``
    module fails. Saved modules are restored afterwards so sibling tests
    (which share the loaded conftest objects with pytest) are unaffected.
    """
    saved = {
        name: module
        for name, module in sys.modules.items()
        if name == "tests" or name.startswith("tests.")
    }
    for name in saved:
        sys.modules.pop(name, None)
    finder = _BlockTestsImports()
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        sys.modules.update(saved)


def test_domain_statements_load_without_tests_tree(no_tests_tree: None) -> None:
    """The ordered DDL list builds with ``tests.*`` unimportable."""
    statements = schema_provisioning._load_domain_statements()

    assert len(statements) > 0


def test_domain_statements_include_all_catalog_tables_in_fk_order(
    no_tests_tree: None,
) -> None:
    """All five catalog DDLs head the statement list in FK-safe order.

    The catalog tables are referenced by later domain tables (e.g.
    ``contratos`` -> ``catalogos_tipos_contrato``), so the provisioning
    list must contain all five before any domain table (issue #329).
    """
    statements = schema_provisioning._load_domain_statements()

    catalog_tables = [
        "catalogos_motivos",
        "catalogos_origenes",
        "catalogos_periodicidad",
        "catalogos_pruebas",
        "catalogos_tipos_contrato",
    ]
    positions = []
    for table in catalog_tables:
        matches = [i for i, s in enumerate(statements) if f"CREATE TABLE IF NOT EXISTS {table}" in s]
        assert matches, f"missing catalog DDL: {table}"
        positions.append(matches[0])
    assert positions == sorted(positions), "catalog DDLs out of FK-safe order"
    first_domain = next(
        i for i, s in enumerate(statements) if "CREATE TABLE IF NOT EXISTS animales" in s
    )
    assert max(positions) < first_domain, "catalog DDL must precede domain tables"


def test_provision_apap_schema_runs_without_tests_tree(no_tests_tree: None) -> None:
    """The full provisioning path executes with ``tests.*`` unimportable.

    ``psycopg.connect`` is mocked so no database is needed: the point is
    that the statement list is assembled without touching the test tree.
    """
    executed: list[str] = []

    class _FakeConn:
        def execute(self, query: object) -> None:
            executed.append(str(query))

        def __enter__(self) -> _FakeConn:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with mock.patch.object(schema_provisioning.psycopg, "connect", return_value=_FakeConn()):
        schema_provisioning.provision_apap_schema("postgresql://unused", "ci_schema")

    assert any("CREATE TABLE IF NOT EXISTS catalogos_motivos" in q for q in executed)
    assert any("CREATE TABLE IF NOT EXISTS usuarios_autorizados" in q for q in executed)
