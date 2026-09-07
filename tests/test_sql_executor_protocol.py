"""Architecture contract for backend-agnostic domain services."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, get_type_hints

import httpx

from app.core.data_access import SqlExecutor
from app.core.local_backend.db import LocalPostgresExecutor

_SERVICE_PATHS = tuple(sorted(Path("app/modules").rglob("*service.py"))) + (
    Path("app/modules/foster/assignment.py"),
)


class _FakeSqlExecutor:
    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        return [{"query": query, "params": params or []}]


class _MissingExecuteSql:
    pass


def test_sql_executor_accepts_a_structural_fake() -> None:
    fake = _FakeSqlExecutor()

    assert isinstance(fake, SqlExecutor)
    assert fake.execute_sql("SELECT $1", ["value"]) == [
        {"query": "SELECT $1", "params": ["value"]}
    ]


def test_sql_executor_rejects_an_object_without_execute_sql() -> None:
    assert not isinstance(_MissingExecuteSql(), SqlExecutor)


def test_local_backend_client_satisfies_sql_executor_without_inheritance() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/database/advance/rawsql"
        return httpx.Response(200, json={"rows": [{"value": 1}]})

    client = LocalPostgresExecutor(
        "https://example.local_backend.test",
        "service-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert isinstance(client, SqlExecutor)
        assert client.execute_sql("SELECT 1") == [{"value": 1}]
    finally:
        client.close()


def test_catalog_reader_accepts_sql_executor_contract() -> None:
    from app.core.catalogs import list_catalogos_pruebas

    hints = get_type_hints(list_catalogos_pruebas)

    assert hints["client"] is SqlExecutor


def test_domain_services_do_not_depend_on_concrete_local_backend_client() -> None:
    violations: list[str] = []

    for path in _SERVICE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_sql_executor = False
        calls_execute_sql = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.core.data_access":
                imports_sql_executor = imports_sql_executor or any(
                    alias.name == "SqlExecutor" for alias in node.names
                )
            if isinstance(node, ast.ImportFrom) and node.module == "app.core.local_backend":
                if any(alias.name == "LocalPostgresExecutor" for alias in node.names):
                    violations.append(f"{path}:{node.lineno} imports LocalPostgresExecutor")
            if isinstance(node, ast.Name) and node.id == "LocalPostgresExecutor":
                violations.append(f"{path}:{node.lineno} annotates LocalPostgresExecutor")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                calls_execute_sql = calls_execute_sql or node.func.attr == "execute_sql"
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for argument in (*node.args.posonlyargs, *node.args.args):
                    if argument.arg == "client" and argument.annotation is None:
                        violations.append(f"{path}:{node.lineno} leaves client untyped")
        if calls_execute_sql and not imports_sql_executor:
            violations.append(f"{path} calls execute_sql without importing SqlExecutor")

    assert _SERVICE_PATHS
    assert violations == []
