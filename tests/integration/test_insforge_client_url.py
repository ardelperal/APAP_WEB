"""AS9: opt-in InsForgeClient base URL resolution."""

from __future__ import annotations

import pytest

from app.core.insforge import InsForgeClient

pytestmark = pytest.mark.integration


def test_as9_unset_and_empty_uses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """No local flag or operator URL preserves the production backend."""
    monkeypatch.delenv("APAP_LOCAL_BACKEND", raising=False)
    monkeypatch.delenv("APAP_INSFORGE_URL", raising=False)
    with InsForgeClient(base_url="", service_key="x") as client:
        assert str(client._client.base_url).rstrip("/") == (
            "https://c3uc9dk6.eu-central.insforge.app"
        )


def test_as9_local_and_empty_uses_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """A truthy local flag defaults to the loopback backend."""
    monkeypatch.setenv("APAP_LOCAL_BACKEND", "TrUe")
    monkeypatch.delenv("APAP_INSFORGE_URL", raising=False)
    with InsForgeClient(base_url="", service_key="x") as client:
        assert str(client._client.base_url).rstrip("/") == "http://localhost:8000"


def test_as9_local_and_custom_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit operator URL overrides the local-backend default."""
    custom = "https://custom.example.com/"
    monkeypatch.setenv("APAP_LOCAL_BACKEND", "true")
    monkeypatch.setenv("APAP_INSFORGE_URL", custom)
    with InsForgeClient(base_url="", service_key="x") as client:
        assert str(client._client.base_url).rstrip("/") == "https://custom.example.com"
