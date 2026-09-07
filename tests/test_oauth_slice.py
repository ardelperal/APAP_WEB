"""Focused contract tests for the OAuth hexagonal slice."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.adapters.local_backend import oauth_local_backend_adapter as adapter_module
from app.core.adapters.local_backend.oauth_local_backend_adapter import (
    LocalBackendOAuthAdapter,
)
from app.core.data_access import BackendError
from app.core.di.oauth_di import get_oauth_port
from app.core.ports.oauth_port import OAuthUser
from tests.sql_executor_fake import HandlerSqlExecutor


def test_exchange_projects_backend_user_to_oauth_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter_module,
        "exchange_oauth_code",
        lambda _payload: {"user": {"id": "user-1", "email": "user@example.com"}},
    )
    adapter = LocalBackendOAuthAdapter(HandlerSqlExecutor(lambda _request: None))

    result = adapter.exchange_oauth_code("oauth-code", "verifier")

    assert result == OAuthUser(id="user-1", email="user@example.com")


def test_exchange_propagates_backend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_exchange(_payload: dict[str, str]) -> dict:
        raise BackendError(503, "service unavailable")

    monkeypatch.setattr(adapter_module, "exchange_oauth_code", fail_exchange)
    adapter = LocalBackendOAuthAdapter(HandlerSqlExecutor(lambda _request: None))

    with pytest.raises(BackendError):
        adapter.exchange_oauth_code("oauth-code", "verifier")


def test_di_yields_oauth_port_bound_to_application_executor() -> None:
    executor = HandlerSqlExecutor(lambda _request: None)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sql_executor=executor))
    )

    dependency = get_oauth_port(request)
    try:
        port = next(dependency)
    finally:
        dependency.close()

    assert isinstance(port, LocalBackendOAuthAdapter)
