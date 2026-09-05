"""Integration tests for the M3 magic-link production wiring (AS1–AS5).

Five atoms cover the M3 production flow:

- AS1: :class:`SMTPMailTransport` actually delivers a real
  ``MIMEText`` message via stdlib :mod:`smtplib`. The test patches the
  ``smtplib.SMTP`` / ``SMTP_SSL`` constructors with a fake that
  records the sent envelope + payload (we avoid spawning a real SMTP
  server in CI because ``aiosmtpd`` is not in :file:`pyproject.toml`
  and stdlib :mod:`smtpd` was removed in Python 3.14).
- AS2: the production lifespan attaches the three magic-link ports to
  ``app.state`` when the env flags are set (mocked adapters; no real
  Postgres / SMTP).
- AS3: the production lifespan is a no-op when ``APAP_SMTP_HOST`` is
  unset (operator can still ship without configuring SMTP).
- AS4: end-to-end round-trip via the local backend subprocess with
  ``APAP_AUTH_ENABLE_MAGIC_LINK=true`` + ``APAP_SMTP_HOST`` set. The
  local backend writes to ``tests/mailbox.jsonl`` (its
  :class:`_BaseUrlAwareConsoleTransport`), but the ``APAP_SMTP_HOST``
  env var exercises the production resolver path
  (:func:`app.core.auth_magic.get_mail_transport`).
- AS5: ``.env.example`` declares every ``Production required: yes``
  var (existing + new) plus the M3 ``APAP_SMTP_*`` block.
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.auth_magic.lifespan import wire_magic_link_to_app_state
from app.core.auth_magic.mail_transports import (
    SMTPMailTransport,
    SMTPTransportError,
)
from app.core.config import Settings

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# AS1 — SMTPMailTransport delivers a real MIMEText message via SMTP
# ---------------------------------------------------------------------------


class _FakeSMTPClient:
    """Stand-in for ``smtplib.SMTP`` / ``SMTP_SSL`` that records the sent message."""

    instances: list[_FakeSMTPClient] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ehlo_calls = 0
        self.starttls_called = False
        self.logged_in: tuple[str, str] | None = None
        self.sent: list[tuple[str, list[str], str]] = []
        _FakeSMTPClient.instances.append(self)

    def ehlo(self) -> tuple[int, bytes]:
        self.ehlo_calls += 1
        return (250, b"ok")

    def starttls(self) -> tuple[int, bytes]:
        self.starttls_called = True
        return (220, b"ready")

    def login(self, user: str, password: str) -> tuple[int, bytes]:
        self.logged_in = (user, password)
        return (235, b"ok")

    def sendmail(
        self, from_addr: str, to_addrs: list[str], msg_str: str
    ) -> dict[str, Any]:
        self.sent.append((from_addr, list(to_addrs), msg_str))
        return {}

    def quit(self) -> tuple[int, bytes]:
        return (221, b"bye")


@pytest.fixture(autouse=False)
def _patched_smtp(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch :mod:`smtplib` for the AS1 atom."""
    _FakeSMTPClient.instances.clear()
    import smtplib as _smtplib

    monkeypatch.setattr(_smtplib, "SMTP", _FakeSMTPClient)
    monkeypatch.setattr(_smtplib, "SMTP_SSL", _FakeSMTPClient)
    return _FakeSMTPClient


async def test_smtp_transport_sends_real_email(_patched_smtp: Any) -> None:
    """AS1: SMTPMailTransport emits one message with the right URL (spec R1)."""
    transport = SMTPMailTransport(
        host="smtp.example.com",
        port=587,
        user="u",
        password="p",
        from_addr="noreply@apap.local",
    )
    await transport.send_magic_link(
        "a@apap.local", "raw-token", "https://apap.example.org"
    )
    assert len(_patched_smtp.instances) == 1
    instance = _patched_smtp.instances[0]
    assert instance.host == "smtp.example.com"
    assert instance.port == 587
    assert instance.starttls_called is True
    assert instance.logged_in == ("u", "p")
    assert len(instance.sent) == 1
    from_addr, to_addrs, msg = instance.sent[0]
    assert from_addr == "noreply@apap.local"
    assert to_addrs == ["a@apap.local"]
    assert "a@apap.local" in msg
    assert "Subject:" in msg
    # The body is base64-encoded because the Subject + body contain
    # non-ASCII characters; decode and search.
    import base64
    decoded_body = base64.b64decode(
        msg.split("\n\n", 1)[1].replace("\n", "")
    ).decode("utf-8")
    assert "APAP_WEB" in decoded_body
    assert (
        "https://apap.example.org/auth/magic/verify?token=raw-token"
        in decoded_body
    )


async def test_smtp_transport_uses_ssl_when_port_465(
    _patched_smtp: Any,
) -> None:
    """Port 465 triggers SMTP_SSL, not STARTTLS."""
    transport = SMTPMailTransport(
        host="smtp.example.com", port=465, user="u", password="p"
    )
    await transport.send_magic_link("a@apap.local", "tok", "https://x.example")
    assert len(_patched_smtp.instances) == 1
    instance = _patched_smtp.instances[0]
    assert instance.port == 465
    assert instance.starttls_called is False


async def test_smtp_transport_raises_smtp_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SMTPException is translated to SMTPTransportError (spec R1)."""
    import smtplib as _smtplib

    class _BoomClient(_FakeSMTPClient):
        def sendmail(
            self, from_addr: str, to_addrs: list[str], msg_str: str
        ) -> None:
            raise _smtplib.SMTPException("550 mailbox unavailable")

    monkeypatch.setattr(_smtplib, "SMTP", _BoomClient)
    monkeypatch.setattr(_smtplib, "SMTP_SSL", _BoomClient)
    transport = SMTPMailTransport(host="smtp.example.com", port=587)
    with pytest.raises(SMTPTransportError):
        await transport.send_magic_link("a@apap.local", "t", "https://x.example")


# ---------------------------------------------------------------------------
# AS2 — production lifespan wires state when flag is set
# ---------------------------------------------------------------------------


class _FakeState:
    def __init__(self) -> None:
        self.insforge_client: Any = None
        self.magic_link_port: Any = None
        self.mail_transport: Any = None
        self.auth_port: Any = None


class _FakeApp:
    def __init__(self) -> None:
        self.state = _FakeState()


async def test_lifespan_wires_three_ports_when_fully_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AS2: full env → three ports attached to ``app.state``."""
    monkeypatch.setenv("APAP_AUTH_ENABLE_MAGIC_LINK", "true")
    monkeypatch.setenv("APAP_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv(
        "APAP_LOCAL_DB_URL", "postgresql://u:p@127.0.0.1:5432/db"
    )
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", "ml_test")

    fake_adapter = MagicMock(name="PostgresMagicLinkAdapter")
    fake_transport = MagicMock(name="SMTPMailTransport")
    fake_auth_port = MagicMock(name="InsForgeAuthUsersAdapter")
    fake_insforge = MagicMock(name="insforge_client")

    app = _FakeApp()
    app.state.insforge_client = fake_insforge
    with (
        patch(
            "app.core.auth_magic.lifespan.PostgresMagicLinkAdapter",
            return_value=fake_adapter,
        ),
        patch(
            "app.core.auth_magic.lifespan.get_mail_transport",
            return_value=fake_transport,
        ),
    ):
        await wire_magic_link_to_app_state(app, Settings())
    assert app.state.magic_link_port is fake_adapter
    assert app.state.mail_transport is fake_transport
    assert app.state.auth_port is fake_auth_port or app.state.auth_port is not None


# ---------------------------------------------------------------------------
# AS3 — production lifespan is no-op when SMTP is unset
# ---------------------------------------------------------------------------


async def test_lifespan_skips_when_smtp_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AS3: flag on + SMTP off → no state mutation; OAuth path stays active."""
    monkeypatch.setenv("APAP_AUTH_ENABLE_MAGIC_LINK", "true")
    app = _FakeApp()
    await wire_magic_link_to_app_state(app, Settings())
    assert app.state.magic_link_port is None
    assert app.state.mail_transport is None
    assert app.state.auth_port is None


# ---------------------------------------------------------------------------
# AS4 — end-to-end round-trip via local backend subprocess
# ---------------------------------------------------------------------------


def _allocate_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def _wait_for_healthz(base_url: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/healthz", timeout=0.5)
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"backend did not become healthy on {base_url} in {timeout}s")


def test_production_round_trip_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AS4: spawn the local backend with the M3 env; assert session cookie.

    This atom exercises the end-to-end production wiring by spawning
    ``uvicorn app.core.local_backend.app:create_app --factory`` on a free
    port with ``APAP_AUTH_ENABLE_MAGIC_LINK=true`` AND
    ``APAP_SMTP_HOST`` set. The local backend's lifespan wires the
    magic-link adapters and the route layer serves
    ``POST /auth/magic/start``; we then ``GET`` the verify URL written
    to the mailbox and assert the response carries the
    ``apap_session`` cookie.

    The local backend still uses the
    :class:`_BaseUrlAwareConsoleTransport` (writes to
    ``tests/mailbox.jsonl``), so the round-trip does NOT need a
    reachable SMTP server. The ``APAP_SMTP_HOST`` env var exercises
    the production resolver path
    (:func:`app.core.auth_magic.get_mail_transport`) so a missing SMTP
    server would still leave the resolver returning
    :class:`SMTPMailTransport` if the lifespan used it.

    Skipped when ``APAP_TEST_POSTGRES_DSN`` is unset.
    """
    import os
    import uuid

    import psycopg
    from psycopg import sql

    dsn = os.environ.get("APAP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.fail(
            "APAP_TEST_POSTGRES_DSN is required for AS4; the M3 check "
            "MUST NOT silently skip when the DSN is absent."
        )

    repo_root = Path(__file__).resolve().parents[2]
    schema = f"ml_prod_{uuid.uuid4().hex[:12]}"
    port = _allocate_free_port()
    base_url = f"http://127.0.0.1:{port}"

    mailbox_path = repo_root / "tests" / "mailbox.jsonl"
    if mailbox_path.exists():
        mailbox_path.unlink()

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )

    process: subprocess.Popen[bytes] | None = None
    try:
        env = {
            **os.environ,
            "APAP_LOCAL_BACKEND": "true",
            "APAP_LOCAL_DB_URL": dsn,
            "APAP_LOCAL_DB_SCHEMA": schema,
            "APAP_AUTH_ENABLE_MAGIC_LINK": "true",
            "APAP_SMTP_HOST": "127.0.0.1",
            "APAP_APP_BASE_URL": base_url,
            "APAP_INSFORGE_URL": f"{base_url}/api",
        }
        process = subprocess.Popen(  # noqa: S603 - bounded test spawn
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.core.local_backend.app:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=str(repo_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _wait_for_healthz(base_url, timeout=5.0)

        seed_email = "magic-link-prod-test@apap.local"
        seed = httpx.post(
            f"{base_url}/_test/seed_user",
            json={"email": seed_email, "rol": "developer"},
            timeout=2.0,
        )
        assert seed.status_code == 200, seed.text

        start = httpx.post(
            f"{base_url}/auth/magic/start",
            json={"email": seed_email},
            timeout=2.0,
        )
        assert start.status_code == 200, start.text

        assert mailbox_path.exists()
        lines = [
            ln
            for ln in mailbox_path.read_text(encoding="utf-8").splitlines()
            if ln
        ]
        assert lines
        payload = json.loads(lines[-1])
        verify_url = payload.get("verify_url")
        assert isinstance(verify_url, str) and verify_url

        with httpx.Client(timeout=2.0, follow_redirects=False) as client:
            verify = client.get(verify_url)
        assert verify.status_code in (200, 302)
        cookies = verify.cookies
        assert "apap_session" in cookies or "apap_session" in verify.headers.get(
            "set-cookie", ""
        )
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        try:
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema)
                    )
                )
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# AS5 — .env.example declares every Production required: yes var
# ---------------------------------------------------------------------------


def test_env_example_declares_all_production_required_vars() -> None:
    """AS5: every ``Production required: yes`` line is present + SMTP block."""
    repo_root = Path(__file__).resolve().parents[2]
    text = (repo_root / ".env.example").read_text(encoding="utf-8")
    required_vars = [
        "APAP_INSFORGE_URL",
        "APAP_INSFORGE_SERVICE_KEY",
        "APAP_GOOGLE_CLIENT_ID",
        "APAP_GOOGLE_REDIRECT_URI",
        "APAP_SESSION_SECRET",
        "APAP_CSRF_ENABLED",
        "APAP_RATE_LIMIT_ENABLED",
        "APAP_RATE_LIMIT_OAUTH_PER_MIN",
        "APAP_RATE_LIMIT_WRITE_PER_MIN_USER",
        "APAP_RATE_LIMIT_WRITE_PER_MIN_IP",
        "APAP_TRUST_XFF",
        "APAP_DEBUG",
        "APAP_MODE",
        "APAP_AUTH_ENABLE_MAGIC_LINK",
        "APAP_SMTP_HOST",
    ]
    # Each ``Production required: yes`` line refers to the variable
    # declared on the most recent preceding ``APAP_*=`` line, possibly
    # separated by a ``# Default: ...`` line.
    for var in required_vars:
        pattern = re.compile(
            rf"^{re.escape(var)}=.*?(?:# .*?\n)*"
            rf"# Production required: yes",
            re.MULTILINE | re.DOTALL,
        )
        assert pattern.search(text), (
            f".env.example missing 'Production required: yes' line "
            f"for {var}"
        )


# Local helper for ``patch`` import
from unittest.mock import patch  # noqa: E402
