"""Application settings loaded from environment variables.

Single source of truth for runtime configuration. Values are read from
process environment variables under the ``APAP_`` prefix, with sensible
defaults so the app can boot in development without any extra setup.

Future phases will extend this with OAuth, InsForge service keys, and
deployment-specific settings (CD-02, issue #1).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the APAP_WEB application.

    Environment variables are read with the ``APAP_`` prefix. For
    example, ``APAP_INSFORGE_URL`` populates :attr:`insforge_url`.
    """

    model_config = SettingsConfigDict(
        env_prefix="APAP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "APAP_WEB"
    version: str = "0.1.0"

    insforge_url: str = "http://localhost:7130"
    insforge_anon_key: str = ""

    debug: bool = False


def get_settings() -> Settings:
    """Return a fresh Settings instance.

    Implemented as a function (rather than a module-level singleton) so
    that tests and request handlers can obtain a clean instance without
    relying on cached state. Future caching can be added here without
    touching call sites.
    """

    return Settings()
