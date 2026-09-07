"""Tests for the application settings.

The Settings model is the single source of truth for runtime configuration
loaded from environment variables (with an optional `.env` file). These
tests pin the expected defaults and the env-var prefix so that the rest of
the application can rely on a stable contract.

``get_settings()`` is the cached accessor used everywhere in the app
(see ``app/core/config.py``); tests that mutate ``APAP_*`` env vars and
then call ``get_settings()`` must ``cache_clear()`` to see the new
values, or rely on the autouse fixture in ``conftest.py`` to clear
between tests.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings


def test_settings_loads_with_defaults() -> None:
    """Settings loads with sensible defaults when no env vars are set."""
    settings = Settings(_env_file=None)

    assert settings.debug is False


def test_settings_uses_apap_env_prefix() -> None:
    """Environment variables are read under the APAP_ prefix."""
    import pytest

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("APAP_DEBUG", "true")
        settings = Settings(_env_file=None)

    assert settings.debug is True


def test_settings_exposes_app_metadata() -> None:
    """Settings expose the application name and version."""
    settings = Settings(_env_file=None)

    assert settings.app_name == "APAP_WEB"
    assert settings.version


def test_settings_does_not_expose_insforge_fields() -> None:
    """The InsForge fields are gone (issue #658). The backend is now the
    Coolify-hosted local Postgres via ``APAP_LOCAL_DB_URL``."""
    settings = Settings(_env_file=None)

    for attr_name in ("insforge_url", "insforge_anon_key", "insforge_service_key"):
        with pytest.raises(AttributeError):
            getattr(settings, attr_name)


def test_settings_does_not_pick_up_apap_insforge_env() -> None:
    """Setting ``APAP_INSFORGE_*`` env vars has no effect (no such field)."""
    import pytest

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("APAP_INSFORGE_URL", "https://legacy.example.com")
        mp.setenv("APAP_INSFORGE_SERVICE_KEY", "ik_should_be_ignored")
        settings = Settings(_env_file=None)

    for attr_name in ("insforge_url", "insforge_service_key"):
        with pytest.raises(AttributeError):
            getattr(settings, attr_name)


def test_validate_secrets_does_not_require_insforge_service_key() -> None:
    """The startup validator no longer checks the InsForge service key."""
    import pytest

    from app.core.config import _validate_secrets

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("APAP_SESSION_SECRET", "a" * 32)
        settings = Settings(_env_file=None)
    # Should not raise; the InsForge gate is gone.
    _validate_secrets(settings)


def test_settings_loads_google_oauth_config_defaults() -> None:
    """Google OAuth client and redirect URI have empty defaults that must be set in prod."""
    settings = Settings(_env_file=None)

    assert settings.google_client_id == ""
    assert settings.google_client_secret == ""
    assert settings.google_redirect_uri == "http://127.0.0.1:8000/auth/callback"


def test_settings_reads_google_oauth_config_from_env() -> None:
    """Google OAuth client config can be injected via env."""
    import pytest

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("APAP_GOOGLE_CLIENT_ID", "test-client-id")
        mp.setenv("APAP_GOOGLE_CLIENT_SECRET", "test-client-secret")
        mp.setenv("APAP_GOOGLE_REDIRECT_URI", "https://apap.romancaba.com/auth/callback")
        settings = Settings(_env_file=None)

    assert settings.google_client_id == "test-client-id"
    assert settings.google_client_secret == "test-client-secret"
    assert settings.google_redirect_uri == "https://apap.romancaba.com/auth/callback"


def test_settings_loads_initial_admin_email_default() -> None:
    """The initial admin email has a sensible default for dev (empty = no seed)."""
    settings = Settings(_env_file=None)

    assert settings.initial_admin_email == ""


def test_settings_reads_initial_admin_email_from_env() -> None:
    """The initial admin email is read from env for the bootstrap seed."""
    import pytest

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("APAP_INITIAL_ADMIN_EMAIL", "ardelperal@gmail.com")
        settings = Settings(_env_file=None)

    assert settings.initial_admin_email == "ardelperal@gmail.com"


def test_settings_loads_session_secret() -> None:
    """The session secret used to sign cookies has a default (must be overridden in prod)."""
    settings = Settings(_env_file=None)

    # Non-empty so signed cookies can be issued in dev.
    assert settings.session_secret


# --- get_settings() caching (code-quality-fixes T1) -----------------------
#
# ``get_settings()`` is the only sanctioned accessor for the singleton
# Settings instance used by the app (request handlers, lifespan, the
# dependency injection layer). Pydantic-settings re-reads env + .env
# on every ``Settings()`` call, so without caching every request pays
# that cost. The cache is process-wide, so tests must ``cache_clear()``
# between cases that mutate env — see the autouse fixture in
# ``conftest.py``.


def test_get_settings_devuelve_la_misma_instancia_en_llamadas_repetidas() -> None:
    """``get_settings()`` returns a cached singleton: two calls return the same object."""
    get_settings.cache_clear()  # start from a known state

    first = get_settings()
    second = get_settings()

    assert first is second, (
        "get_settings() debe devolver la misma instancia cacheada, "
        "no una nueva Settings() en cada llamada"
    )


def test_get_settings_cache_clear_permite_releer_el_entorno() -> None:
    """``cache_clear()`` invalida el cache; la siguiente llamada relee ``APAP_*``."""
    get_settings.cache_clear()
    get_settings()  # warm the cache with the current env

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("APAP_DEBUG", "false")
        # While cached, env changes are NOT visible (intentional).
        cached = get_settings()
        # After cache_clear, the new env value is picked up.
        get_settings.cache_clear()
        reread = get_settings()
        assert cached is not reread
