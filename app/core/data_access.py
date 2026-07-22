"""Backend-agnostic data-access contracts used by domain services."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SqlExecutor(Protocol):
    """Minimal SQL execution surface required by domain services."""

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...
