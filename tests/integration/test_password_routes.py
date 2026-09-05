"""Integration tests for the Phase 2 password routes (F2.1.3).

Spec: openspec/changes/phase2-classic-password/specs/phase2-classic-password/spec.md
- AS2.1: happy path — POST /auth/login with valid creds returns 200 + apap_session cookie
- AS2.2: wrong password — 401
- AS2.3: unknown user — 401
- AS2.4: NULL password_hash — 401
- AS3.1: POST /auth/forgot-password mints token for known user with hash
- AS4.1: POST /auth/reset-password consumes token, sets hash, logs in
- AS4.2: expired / invalid token → 400 invalid_token

These tests drive an in-process FastAPI TestClient with the lifespan
mocked to install a controlled ClassicPasswordAuthPort + mail_transport.
"""
from __future__ import annotations

import asyncio
import datetime
import os
import time
from typing import Any

import argon2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.adapters.auth.classic_password_auth_port import (
    ClassicPasswordAuthPort,
)
from app.core.auth_password.routes import register_password_routes


class _FakeExecutor:
    """In-memory SqlExecutor for integration tests (see unit tests for the
    full implementation — same semantics, simpler surface here)."""

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def seed(self, email: str, *, password_hash: str | None) -> None:
        self._rows[email] = {
            "email": email,
            "id": "11111111-1111-1111-1111-111111111111",
            "rol": "developer",
            "activo": True,
            "password_hash": password_hash,
        }

    def execute_sql(self, query, params=None):  # type: ignore[no-untyped-def]
        text = query.lower()
        if "select password_hash from usuarios_autorizados" in text:
            r = self._rows.get((params or [None])[0])
            return [{"password_hash": r["password_hash"]}] if r else []
        if "select id, email, rol, activo" in text and "where email" in text:
            r = self._rows.get((params or [None])[0])
            return [{"id": r["id"], "email": r["email"], "rol": r["rol"], "activo": r["activo"]}] if r else []
        if "update usuarios_autorizados set password_hash" in text:
            new_hash, email = (params or [None, None])[0], (params or [None, None])[1]
            if email in self._rows:
                self._rows[email]["password_hash"] = new_hash
        if "update usuarios_autorizados set password_reset_token" in text:
            params = params or []
            email = params[-1]
            if len(params) >= 3 and email in self._rows:
                self._rows[email]["password_reset_token"] = params[0]
                self._rows[email]["password_reset_expires_at"] = params[1]
            elif email in self._rows:
                self._rows[email]["password_reset_token"] = None
                self._rows[email]["password_reset_expires_at"] = None
        if "select email, password_reset_expires_at" in text and "where password_reset_token" in text:
            token = (params or [None])[0]
            for em, row in self._rows.items():
                if row.get("password_reset_token") == token:
                    return [{"email": em, "password_reset_expires_at": row["password_reset_expires_at"]}]
            return []
        return []


class _FakeMailTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_magic_link(self, email: str, raw_token: str, base_url: str) -> None:
        self.sent.append({"email": email, "token": raw_token, "base_url": base_url})


@pytest.fixture
def app():
    from contextlib import asynccontextmanager

    fake_executor = _FakeExecutor()
    fake_executor.seed("admin@example.com", password_hash=argon2.PasswordHasher().hash("correct-horse-battery-staple"))
    fake_executor.seed("magic@example.com", password_hash=None)

    port = ClassicPasswordAuthPort(fake_executor)
    mail = _FakeMailTransport()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.password_auth = port
        application.state.mail_transport = mail
        yield

    app = FastAPI(lifespan=lifespan)
    register_password_routes(app)
    return app, fake_executor, mail


@pytest.fixture
def client(app):
    a, _, _ = app
    with TestClient(a) as c:
        yield c


def test_login_returns_200_and_cookie_on_valid_creds(client):
    """AS2.1 — happy path."""
    r = client.post("/auth/login", json={"email": "admin@example.com", "password": "correct-horse-battery-staple"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "authenticated"
    assert body["email"] == "admin@example.com"
    # Set-Cookie header has apap_session
    set_cookie = r.headers.get("set-cookie", "")
    assert "apap_session=" in set_cookie
    assert "HttpOnly" in set_cookie or "httponly" in set_cookie.lower()
    assert "Max-Age=604800" in set_cookie


def test_login_returns_401_on_bad_password(client):
    """AS2.2 — wrong password."""
    r = client.post("/auth/login", json={"email": "admin@example.com", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_credentials"


def test_login_returns_401_on_unknown_email(client):
    """AS2.3 — unknown user returns 401 (no leak)."""
    r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "anything"})
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_credentials"


def test_login_returns_401_for_null_password_hash_user(client):
    """AS2.4 — magic-link-only user (NULL password_hash) cannot password-login."""
    r = client.post("/auth/login", json={"email": "magic@example.com", "password": "any-password"})
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_credentials"


def test_forgot_password_mints_token_for_user_with_password(app, client):
    """AS3.1 — POST /auth/forgot-password mints a token; writes to mail_transport."""
    r = client.post("/auth/forgot-password", json={"email": "admin@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    # reset_url is in the response (per the test-only envelope)
    assert body.get("reset_url") is not None
    assert "token=" in body["reset_url"]
    # Mail transport got the message
    _, _, mail = app
    assert len(mail.sent) == 1
    assert mail.sent[0]["email"] == "admin@example.com"
    assert mail.sent[0]["token"]  # non-empty


def test_forgot_password_returns_200_for_unknown_email_no_leak(app, client):
    """AS3 — unknown email returns 200 with no reset_url."""
    r = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    assert r.json().get("reset_url") is None
    # Mail transport did NOT get a message
    _, _, mail = app
    assert len(mail.sent) == 0


def test_forgot_password_returns_200_for_null_hash_user(app, client):
    """User with NULL password_hash doesn't get a reset token."""
    r = client.post("/auth/forgot-password", json={"email": "magic@example.com"})
    assert r.status_code == 200
    assert r.json().get("reset_url") is None


def test_reset_password_consumes_token_and_logs_user_in(app, client):
    """AS4.1 — POST /auth/reset-password consumes the token, sets the hash, logs the user in."""
    # First mint a token
    r1 = client.post("/auth/forgot-password", json={"email": "admin@example.com"})
    token_match = r1.json()["reset_url"].split("token=")[-1]

    r2 = client.post("/auth/reset-password", json={"token": token_match, "new_password": "new-pass-9876"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "authenticated"
    assert body["email"] == "admin@example.com"

    # Now login with the new password should work
    r3 = client.post("/auth/login", json={"email": "admin@example.com", "password": "new-pass-9876"})
    assert r3.status_code == 200

    # Token is single-use — second consume fails
    r4 = client.post("/auth/reset-password", json={"token": token_match, "new_password": "another-new-pass"})
    assert r4.status_code == 400


def test_reset_password_rejects_invalid_token(client):
    """AS4.2 — invalid token returns 400."""
    r = client.post("/auth/reset-password", json={"token": "does-not-exist", "new_password": "strong-password-1234"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_token"


def test_reset_password_rejects_expired_token(app, client):
    """AS4.2 — token past expires_at returns 400."""
    _, executor, _ = app
    # Mint a token, then manually rewrite its expires_at to past
    r1 = client.post("/auth/forgot-password", json={"email": "admin@example.com"})
    token = r1.json()["reset_url"].split("token=")[-1]
    executor._rows["admin@example.com"]["password_reset_expires_at"] = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)

    r2 = client.post("/auth/reset-password", json={"token": token, "new_password": "strong-password-1234"})
    assert r2.status_code == 400
    assert r2.json()["error"] == "invalid_token"


def test_reset_password_rejects_weak_password(client):
    """Spec R4 — passwords shorter than 12 characters are rejected with 400."""
    r1 = client.post("/auth/forgot-password", json={"email": "admin@example.com"})
    token = r1.json()["reset_url"].split("token=")[-1]
    r2 = client.post("/auth/reset-password", json={"token": token, "new_password": "short"})
    assert r2.status_code == 400
    assert r2.json()["error"] == "weak_password"


def test_login_cookie_format_matches_magic_link(app, client):
    """AS6.1 — the apap_session cookie format is identical (modulo issue time) to the magic-link verify path."""
    r = client.post("/auth/login", json={"email": "admin@example.com", "password": "correct-horse-battery-staple"})
    set_cookie = r.headers.get("set-cookie", "")
    # Same shape as OAuth + magic-link
    assert "apap_session=" in set_cookie
    assert "HttpOnly" in set_cookie or "httponly" in set_cookie.lower()
    assert "SameSite=strict" in set_cookie or "samesite=strict" in set_cookie.lower()
    assert "Max-Age=604800" in set_cookie
