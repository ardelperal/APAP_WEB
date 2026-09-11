"""Unit coverage for LocalBackend magic-link route contracts."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.local_backend.magic_link import router as magic_link_router


class _MagicLinkPortSpy:
    def __init__(self) -> None:
        self.emails: list[str] = []

    def create_token(self, email: str) -> str:
        self.emails.append(email)
        return "opaque-token"


class _MailTransportSpy:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def send(self, *, to_addr: str, subject: str, body: str) -> None:
        self.messages.append({"to_addr": to_addr, "subject": subject, "body": body})


def _magic_link_app() -> tuple[FastAPI, _MagicLinkPortSpy, _MailTransportSpy]:
    app = FastAPI()
    port = _MagicLinkPortSpy()
    transport = _MailTransportSpy()
    app.state.magic_link_port = port
    app.state.smtp_transport = transport
    app.state.public_base_url = "https://apap.example"
    app.include_router(magic_link_router, prefix="/api")
    return app, port, transport


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"email": "not-an-email"}])
async def test_start_magic_link_rejects_invalid_email(payload: dict[str, Any]) -> None:
    """Missing and malformed addresses fail before token creation."""
    app, port, transport = _magic_link_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/magic/start", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": {"error": "invalid_email"}}
    assert port.emails == []
    assert transport.messages == []


@pytest.mark.asyncio
async def test_start_magic_link_normalizes_and_queues_message() -> None:
    """A valid address is normalized and receives the opaque verify URL."""
    app, port, transport = _magic_link_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/magic/start", json={"email": "  User@Example.COM "})

    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert port.emails == ["user@example.com"]
    assert len(transport.messages) == 1
    assert transport.messages[0]["to_addr"] == "user@example.com"
    assert transport.messages[0]["subject"] == "Tu enlace de acceso a APAP"
    assert (
        "https://apap.example/api/magic/verify?token=opaque-token" in transport.messages[0]["body"]
    )
