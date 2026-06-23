"""Shared pytest fixtures for the APAP_WEB test suite.

The ``client`` fixture is the only thing most route tests need: an
``httpx.AsyncClient`` wired to the module-level ``app`` via
``httpx.ASGITransport`` (the current recommended way to exercise an
ASGI app from tests, per the httpx docs). Using the module-level
``app`` (rather than calling ``create_app()`` per test) is what makes
``app.dependency_overrides[...]`` work: the test that overrides a
dependency and the test that uses the client must see the same
``app`` instance.

The ``_clear_settings_cache`` autouse fixture (function scope) clears
the ``get_settings`` lru_cache before every test. This keeps tests
hermetic even when one test mutates ``APAP_*`` env vars via
``monkeypatch.setenv`` / ``mp.setenv`` and a later test expects the
defaults. It costs one function call per test — negligible.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.main import app as _app


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Reset ``get_settings()`` lru_cache before every test.

    Added for code-quality-fixes T1 (see ``app/core/config.py`` docstring
    and ``openspec/changes/code-quality-fixes/proposal.md``). Tests that
    mutate ``APAP_*`` env vars without explicitly clearing the cache
    would otherwise observe a stale singleton from a previous test.
    """
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> httpx.AsyncClient:
    """An ``httpx.AsyncClient`` bound to the module-level ``app``."""
    transport = httpx.ASGITransport(app=_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
