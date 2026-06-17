"""Tests for the application settings.

The Settings model is the single source of truth for runtime configuration
loaded from environment variables (with an optional `.env` file). These
tests pin the expected defaults and the env-var prefix so that the rest of
the application can rely on a stable contract.
"""

from __future__ import annotations

from app.core.config import Settings


def test_settings_loads_with_defaults() -> None:
    """Settings loads with sensible defaults when no env vars are set."""
    settings = Settings(_env_file=None)

    assert settings.insforge_url.startswith("http")
    assert settings.insforge_anon_key == ""
    assert settings.debug is False


def test_settings_uses_apap_env_prefix() -> None:
    """Environment variables are read under the APAP_ prefix."""
    import pytest

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("APAP_INSFORGE_URL", "https://custom.example.com")
        mp.setenv("APAP_DEBUG", "true")
        settings = Settings(_env_file=None)

    assert settings.insforge_url == "https://custom.example.com"
    assert settings.debug is True


def test_settings_exposes_app_metadata() -> None:
    """Settings expose the application name and version."""
    settings = Settings(_env_file=None)

    assert settings.app_name == "APAP_WEB"
    assert settings.version
