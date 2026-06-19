"""Tests for the FastAPI lifespan: bootstrap of InsForge schema on startup.

The contract is: when the app starts, the schema bootstrap functions are
called in the right order with a real ``InsForgeClient``. If any
bootstrap step raises, the lifespan propagates and the app does not start
(fail fast).

These tests exercise the lifespan directly (it is exported as a top-level
symbol in ``app.main`` for testability) rather than going through
``httpx.AsyncClient``, which does not fire the ASGI lifespan protocol.
``monkeypatch`` replaces the bootstrap functions with captures so we
observe the wiring without exercising the SQL.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.main import app as _app
from app.main import lifespan


async def test_lifespan_calls_ensure_schema_and_seed_on_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_calls: list[Any] = []
    domain_calls: list[Any] = []

    def _record_auth(*args: Any, **kwargs: Any) -> None:
        auth_calls.append((args, kwargs))

    def _record_domain(*args: Any, **kwargs: Any) -> None:
        domain_calls.append((args, kwargs))

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _record_auth)
    monkeypatch.setattr("app.main.ensure_domain_schema", _record_domain)

    async with lifespan(_app):
        pass

    assert len(auth_calls) == 1, f"expected ensure_schema_and_seed called once, got {len(auth_calls)}"
    assert len(domain_calls) == 1, f"expected ensure_domain_schema called once, got {len(domain_calls)}"


async def test_lifespan_calls_domain_bootstrap_after_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The auth bootstrap must finish before the domain bootstrap starts."""
    order: list[str] = []

    def _record_auth(*args: Any, **kwargs: Any) -> None:
        order.append("auth")

    def _record_domain(*args: Any, **kwargs: Any) -> None:
        order.append("domain")

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _record_auth)
    monkeypatch.setattr("app.main.ensure_domain_schema", _record_domain)

    async with lifespan(_app):
        pass

    assert order == ["auth", "domain"], f"bootstrap order wrong: {order!r}"


async def test_lifespan_passes_a_real_insforge_client_to_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bootstrap functions must receive an ``InsForgeClient`` built from settings."""
    from app.core.insforge import InsForgeClient

    seen: list[Any] = []

    def _capture_auth(client: Any, settings: Any) -> None:
        seen.append(client)

    def _capture_domain(client: Any) -> None:
        seen.append(client)

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _capture_auth)
    monkeypatch.setattr("app.main.ensure_domain_schema", _capture_domain)

    async with lifespan(_app):
        pass

    assert len(seen) == 2
    assert all(isinstance(c, InsForgeClient) for c in seen), (
        f"bootstrap received non-InsForgeClient: {[type(c).__name__ for c in seen]!r}"
    )


async def test_lifespan_propagates_bootstrap_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If either bootstrap step raises, the lifespan must propagate (fail fast)."""
    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("bootstrap failed (test)")

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _boom)

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        async with lifespan(_app):
            pass


async def test_lifespan_closes_the_insforge_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bootstrap client must be closed even if the bootstrap functions raise."""
    close_calls: list[None] = []

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def close(self) -> None:
            close_calls.append(None)

    monkeypatch.setattr("app.main.InsForgeClient", _FakeClient)

    def _record_auth(*args: Any, **kwargs: Any) -> None:
        pass

    def _record_domain(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr("app.main.ensure_schema_and_seed", _record_auth)
    monkeypatch.setattr("app.main.ensure_domain_schema", _record_domain)

    async with lifespan(_app):
        pass

    assert close_calls == [None], f"InsForgeClient.close() was not called: {close_calls!r}"
