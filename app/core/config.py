"""Application settings loaded from environment variables.

Single source of truth for runtime configuration. Values are read from
process environment variables under the ``APAP_`` prefix, with sensible
defaults so the app can boot in development without any extra setup.

Fase 2 (issue #16) extends this with the InsForge service key, the
Google OAuth client, the bootstrap admin email, and the session secret
used to sign cookies. Production deployments MUST override the defaults
for ``google_client_id``, ``google_client_secret``, ``initial_admin_email``
and ``session_secret`` via env vars or the platform secret store.
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

    # --- InsForge (data, auth, storage) ---------------------------------
    insforge_url: str = "http://localhost:7130"
    insforge_anon_key: str = ""
    # Privileged service key used by the app to run admin SQL (create the
    # `authorized_users` table, seed the bootstrap admin, etc.). Must be
    # set in production. Empty in dev so privileged ops are off by default.
    insforge_service_key: str = ""

    # --- Google OAuth (Fase 2) ------------------------------------------
    google_client_id: str = ""
    google_client_secret: str = ""
    # Callback registered with Google; must match exactly. Defaults to
    # the local dev URL so the app boots in development without any
    # extra config; production must override.
    google_redirect_uri: str = "http://127.0.0.1:8000/auth/callback"

    # --- Bootstrap (Fase 2) ---------------------------------------------
    # Email of the first `developer` user, seeded on first startup if
    # no developer exists. Empty means "do not seed anyone".
    initial_admin_email: str = ""

    # --- Session ---------------------------------------------------------
    # HMAC secret used to sign session cookies. Non-empty default so dev
    # works out of the box, but MUST be overridden in production via env.
    session_secret: str = "dev-only-change-me-in-production"

    debug: bool = False


def get_settings() -> Settings:
    """Return a fresh Settings instance.

    Implemented as a function (rather than a module-level singleton) so
    that tests and request handlers can obtain a clean instance without
    relying on cached state. Future caching can be added here without
    touching call sites.
    """

    return Settings()
