"""Shared pytest fixtures for the APAP_WEB test suite.

The ``client`` fixture is the only thing most route tests need: an
``httpx.AsyncClient`` wired to the module-level ``app`` via
``httpx.ASGITransport`` (the current recommended way to exercise an
ASGI app from tests, per the httpx docs). Using the module-level
``app`` (rather than calling ``create_app()`` per test) is what makes
``app.dependency_overrides[...]`` work: the test that overrides a
dependency and the test that uses the client must see the same
``app`` instance.
"""

from __future__ import annotations

import httpx
import pytest_asyncio

from app.main import app as _app


@pytest_asyncio.fixture
async def client() -> httpx.AsyncClient:
    """An ``httpx.AsyncClient`` bound to the module-level ``app``."""
    transport = httpx.ASGITransport(app=_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
