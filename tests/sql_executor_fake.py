"""Test-only SQL executor backed by an HTTP-style response handler.

This preserves the existing service-test fixtures while keeping production
code coupled only to the backend-agnostic ``SqlExecutor`` contract.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.core.data_access import BackendError, UniqueViolationError


class _RequestTransport(Protocol):
    def handle_request(self, request: httpx.Request) -> httpx.Response: ...


class HandlerSqlExecutor:
    """Adapt a deterministic response handler to the ``SqlExecutor`` shape."""

    def __init__(
        self,
        handler_or_url: Callable[[httpx.Request], httpx.Response] | str = "",
        _service_key: str | None = None,
        *,
        base_url: str | None = None,
        service_key: str | None = None,
        transport: _RequestTransport | None = None,
    ) -> None:
        del base_url, service_key
        if callable(handler_or_url):
            self._handler = handler_or_url
            return
        if transport is None:
            raise TypeError("transport is required for an HTTP-style test fixture")
        self._handler = transport.handle_request

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        request = httpx.Request(
            "POST",
            "https://sql-executor.test/execute",
            headers={"Authorization": "Bearer test"},
            content=json.dumps({"query": query, "params": params or []}).encode(),
        )
        response = self._handler(request)
        body = response.json()

        if response.is_error:
            body_text = str(body).lower()
            if response.status_code == 409 and any(
                marker in body_text for marker in ("23505", "duplicate", "unique")
            ):
                raise UniqueViolationError(body_text)
            raise BackendError(response.status_code, body)

        if isinstance(body, dict) and isinstance(body.get("rows"), list):
            return body["rows"]
        if not isinstance(body, list):
            raise AssertionError(f"SQL handler returned a non-list body: {body!r}")
        return body

    def close(self) -> None:
        """Mirror closable historical fixtures without owning resources."""
