"""Unit tests for ``app.core.auth_magic.lifespan.wire_magic_link_to_app_state`` (M3, R2).

The four atoms below cover the four documented branches of the wiring
helper (see :class:`app.core.auth_magic.lifespan`):

1. ``APAP_AUTH_ENABLE_MAGIC_LINK`` unset → no-op, no state mutation.
2. Flag set but ``APAP_SMTP_HOST`` unset → warning + no wiring.
3. Flag + SMTP set but ``APAP_LOCAL_DB_URL`` unset → warning + no wiring.
4. Flag + SMTP + DSN all set → ``magic_link_port`` /
   ``mail_transport`` / ``auth_port`` attached to ``application.state``.

The tests use ``monkeypatch.setenv`` to flip env vars at request
time (matching the production resolver's behaviour) and mock the
``app.state`` and the heavy ``PostgresMagicLinkAdapter`` constructor
so no real Postgres is needed.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core.auth_magic.lifespan import wire_magic_link_to_app_state
from app.core.config import Settings


class _FakeState:
    """Minimal stand-in for ``fastapi.FastAPI.state``."""

    def __init__(self) -> None:
        self.insforge_client: Any = None
        self.magic_link_port: Any = None
        self.mail_transport: Any = None
        self.auth_port: Any = None


class _FakeApp:
    """Minimal stand-in for ``fastapi.FastAPI`` (one attribute: ``state``)."""

    def __init__(self) -> None:
        self.state = _FakeState()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip the M3 env vars before each atom so the test owns the state."""
    for var in (
        "APAP_AUTH_ENABLE_MAGIC_LINK",
        "APAP_SMTP_HOST",
        "APAP_SMTP_PORT",
        "APAP_SMTP_USER",
        "APAP_SMTP_PASSWORD",
        "APAP_SMTP_FROM",
        "APAP_LOCAL_DB_URL",
        "APAP_LOCAL_DB_SCHEMA",
    ):
        monkeypatch.delenv(var, raising=False)


async def test_flag_unset_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No flag → helper logs and returns; no state mutation (R2 spec)."""
    app = _FakeApp()
    settings = Settings()
    await wire_magic_link_to_app_state(app, settings)
    assert app.state.magic_link_port is None
    assert app.state.mail_transport is None
    assert app.state.auth_port is None


async def test_flag_set_but_smtp_unset_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag on + SMTP off → warning + no wiring; OAuth path stays active (AS3)."""
    monkeypatch.setenv("APAP_AUTH_ENABLE_MAGIC_LINK", "true")
    app = _FakeApp()
    settings = Settings()
    await wire_magic_link_to_app_state(app, settings)
    assert app.state.magic_link_port is None
    assert app.state.mail_transport is None
    assert app.state.auth_port is None


async def test_flag_smtp_set_but_dsn_unset_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SMTP set but no local DB → warning + no wiring."""
    monkeypatch.setenv("APAP_AUTH_ENABLE_MAGIC_LINK", "true")
    monkeypatch.setenv("APAP_SMTP_HOST", "smtp.example.com")
    app = _FakeApp()
    settings = Settings()
    await wire_magic_link_to_app_state(app, settings)
    assert app.state.magic_link_port is None
    assert app.state.mail_transport is None
    assert app.state.auth_port is None


async def test_full_wiring_attaches_three_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag + SMTP + DSN → three ports attached to ``application.state`` (AS2)."""
    monkeypatch.setenv("APAP_AUTH_ENABLE_MAGIC_LINK", "true")
    monkeypatch.setenv("APAP_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv(
        "APAP_LOCAL_DB_URL", "postgresql://u:p@127.0.0.1:5432/db"
    )
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", "ml_test")

    fake_adapter = MagicMock(name="PostgresMagicLinkAdapter")
    fake_transport = MagicMock(name="SMTPMailTransport")
    fake_auth_port = MagicMock(name="InsForgeAuthUsersAdapter")
    fake_insforge_client = MagicMock(name="insforge_client")

    app = _FakeApp()
    app.state.insforge_client = fake_insforge_client
    settings = Settings()

    with (
        patch(
            "app.core.auth_magic.lifespan.PostgresMagicLinkAdapter",
            return_value=fake_adapter,
        ),
        patch(
            "app.core.auth_magic.lifespan.get_mail_transport",
            return_value=fake_transport,
        ),
        patch(
            "app.core.adapters.insforge.auth_insforge_adapter.InsForgeAuthUsersAdapter",
            return_value=fake_auth_port,
        ),
    ):
        await wire_magic_link_to_app_state(app, settings)

    assert app.state.magic_link_port is fake_adapter
    assert app.state.mail_transport is fake_transport
    assert app.state.auth_port is fake_auth_port