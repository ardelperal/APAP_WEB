"""Application settings loaded from environment variables.

Single source of truth for runtime configuration. Values are read from
process environment variables under the ``APAP_`` prefix, with sensible
defaults so the app can boot in development without any extra setup.

Fase 2 (issue #16) extends this with the Google OAuth client, the
bootstrap admin email, and the session secret used to sign cookies.
Production deployments MUST override the defaults for ``google_client_id``,
``google_client_secret``, ``initial_admin_email`` and ``session_secret``
via env vars or the platform secret store.

Startup validation: ``_validate_secrets`` (called from the lifespan in
``app/main.py``) enforces that ``session_secret`` is not the published
placeholder and is at least 32 characters. Validation is bypassed when
``debug is True``. See issue #275 and AGENTS.md §32.P2.

``get_settings()`` is cached with ``functools.lru_cache(maxsize=1)`` so
every call returns the same singleton — pydantic-settings re-reads env
on each ``Settings()`` call, so caching avoids that overhead per
request. Tests that mutate ``APAP_*`` env vars between cases must call
``get_settings.cache_clear()`` (the conftest autouse fixture already
does this for safety).
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.logging import log_safe
from app.core.roles import Rol

_PLACEHOLDER_SESSION_SECRET = "dev-only-change-me-in-production"


class StartupConfigError(RuntimeError):
    """Raised when startup finds a critical secret missing or weak.

    The message names the offending env var but never echoes the value.
    """

    def __init__(self, env_var: str, reason: str = "invalid") -> None:
        self.env_var = env_var
        self.reason = reason
        super().__init__(
            f"startup config error: {env_var} is invalid (reason={reason}); "
            "set a real value via the environment"
        )


def _validate_secrets(settings: Settings) -> None:
    """Refuse to boot with placeholder / short critical secrets.

    Bypassed when ``settings.debug is True`` (dev convenience). Each rejection
    emits ``log_safe("startup.config_invalid", env_var=..., reason=...)``
    before raising. ``reason`` is one of ``"placeholder"`` | ``"too_short"``.
    Issue #275 / AGENTS.md §32.P2.
    """
    if settings.debug:
        return
    if settings.session_secret == _PLACEHOLDER_SESSION_SECRET:
        log_safe("startup.config_invalid", env_var="APAP_SESSION_SECRET", reason="placeholder")
        raise StartupConfigError("APAP_SESSION_SECRET", "placeholder")
    if len(settings.session_secret) < 32:
        log_safe("startup.config_invalid", env_var="APAP_SESSION_SECRET", reason="too_short")
        raise StartupConfigError("APAP_SESSION_SECRET", "too_short")


class Settings(BaseSettings):
    """Runtime settings for the APAP_WEB application.

    Environment variables are read with the ``APAP_`` prefix. For
    example, ``APAP_SESSION_SECRET`` populates :attr:`session_secret`.
    ``SOURCE_COMMIT`` is the sole platform-provided alias: Coolify injects it
    at runtime and it takes precedence over the image's ``APAP_BUILD_SHA``.
    """

    model_config = SettingsConfigDict(
        env_prefix="APAP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "APAP_WEB"
    version: str = "0.1.0"
    build_sha: str = Field(
        default="development",
        validation_alias=AliasChoices("SOURCE_COMMIT", "APAP_BUILD_SHA"),
    )

    # Coolify-hosted local backend (issue #641, #648). The only
    # supported production transport as of 2026-09-06: the
    # ``LocalPostgresExecutor`` (see ``app.core.local_backend.db``)
    # runs every SQL against this DSN. ``APAP_LOCAL_DB_URL`` is the
    # DSN (e.g. ``postgresql://apap:<pw>@apap-pg-test:5432/apap``);
    # ``APAP_LOCAL_DB_SCHEMA`` is the schema name (optional,
    # defaults to ``public``; tests pass an ephemeral schema).
    local_db_url: str = ""
    local_db_schema: str = ""

    # --- Google OAuth (Fase 2) ------------------------------------------
    google_client_id: str = ""
    google_client_secret: str = ""
    # Callback registered with Google; must match exactly. Defaults to
    # the local dev URL so the app boots in development without any
    # extra config; production must override.
    google_redirect_uri: str = "http://127.0.0.1:8000/auth/callback"

    # --- E2E test-only OAuth mock (issue #598) ----------------------
    # When True, ``app.core.e2e_auth.register_e2e_auth_routes``
    # registers ``POST /e2e/login`` which mints a session directly
    # when the ``X-E2E-Secret`` request header matches
    # ``e2e_auth_secret``. Defaults to False; production MUST leave
    # this off (the route is not registered otherwise and the
    # existing ``/login`` 503 behaviour stands).
    e2e_auth_enabled: bool = False
    e2e_auth_secret: str = ""
    # Email used by the Playwright conftest when authenticating
    # against the mock route. Must exist as an ``usuarios_autorizados``
    # row in production, but the mock pre-populates the in-process
    # auth cache so the DB row is bypassed during E2E runs.
    e2e_auth_default_email: str = "e2e@apap.local"

    # --- LocalBackend rawsql shared-secret auth (issue #680) ----------
    # Bearer token that gates ``POST /api/database/advance/rawsql``
    # (``app/core/local_backend/rawsql.py``). The handler REJECTS
    # every request unless the ``Authorization: Bearer <token>``
    # header matches this value exactly (constant-time comparison).
    # When empty, the handler rejects every request — there is no
    # default token, even in dev (the operator must set the env var
    # explicitly to opt into the endpoint). The separate LocalBackend
    # lifespan refuses to start with an empty or weak value; ``app.main``
    # does not validate this token because it never mounts the endpoint.
    # Migration scripts that already speak to the executor directly
    # (e.g. ``migration/verify_fallback_ready.py``) never hit this
    # HTTP surface; the migration CLI can set the env var when it
    # needs the fallback compatibility endpoint.
    rawsql_auth_token: str = ""

    # --- Bootstrap (Fase 2) ---------------------------------------------
    # Email of the first `developer` user, seeded on first startup if
    # no developer exists. Empty means "do not seed anyone".
    initial_admin_email: str = ""

    # --- Session ---------------------------------------------------------
    # HMAC secret used to sign session cookies. Non-empty default so dev
    # works out of the box, but MUST be overridden in production via env.
    # The lifespan validates this via ``_validate_secrets``:
    # - placeholder string is rejected (fail-fast; see §32.P2)
    # - secrets shorter than 32 chars are rejected
    # - validation is bypassed when ``debug is True``
    session_secret: str = "dev-only-change-me-in-production"

    # --- Per-request authorization revalidation (issue #143, #262) ---
    # TTL (seconds) for the authorization cache backing
    # ``require_authorized_user``. The cookie signs the identity; the DB
    # (``usuarios_autorizados``) is the source of truth for authorization
    # and is re-validated per request, cached for this many seconds to
    # bound query load. Default 300s (5 min) balances freshness against
    # one SELECT per user per request. Set to 0 to disable the cache for
    # immediate (<1s) revocation at the cost of a query on every request.
    # In multi-worker deployments with the default in-process backend,
    # lowering this value shortens the per-worker staleness window
    # (issue #262). See ``docs/runbooks/auth-cache-multi-worker.md``.
    auth_cache_ttl_seconds: int = 300

    # --- Auth-cache backend compatibility guard (issue #262, #287) ----
    # ``in_process`` is the only supported backend. The field remains so
    # stale or invalid APAP_AUTH_CACHE_BACKEND values fail settings
    # validation during startup instead of being ignored by ``extra=ignore``.
    # Multi-worker deployments must set APAP_AUTH_CACHE_TTL_SECONDS=0 for
    # immediate cross-worker revocation; see the operator runbook.
    auth_cache_backend: Literal["in_process"] = "in_process"

    # --- CSRF defense-in-depth (PR-5B, Slice 5) ------------------------
    # Feature flag for the CSRF middleware (``app/core/csrf.py``). When
    # ``False``, the middleware short-circuits and emits a ``csrf.disabled``
    # warning per request — useful for emergency rollback without a
    # redeploy. Production MUST keep this ``True``; the only legitimate
    # use of ``False`` is during incident response when a CSRF regression
    # blocks legitimate form submissions.
    csrf_enabled: bool = True

    # --- Rate limiting (issue #286) ------------------------------------
    # Feature flag: when False, the middleware short-circuits on every request.
    rate_limit_enabled: bool = True
    # OAuth callback bucket: IP-only, requests per minute.
    rate_limit_oauth_per_min: int = 10
    # Write buckets: per-user and per-IP, requests per minute.
    rate_limit_write_per_min_user: int = 60
    rate_limit_write_per_min_ip: int = 30
    # Whether to trust X-Forwarded-For header (needed when behind a proxy).
    trust_xff: bool = False
    # Runtime mode: "web" or "test". When "test", the middleware short-circuits
    # without consuming any rate budget.
    mode: str = "web"

    # --- Structured logging (PR-6A, Slice 6) --------------------------
    # Root log level for the JSON stdout handler installed by
    # ``app.core.logging.configure_logging``. Unknown values fall back
    # to ``INFO`` at runtime (the typed default is ``"INFO"``).
    log_level: str = "INFO"

    # --- Magic-link SMTP transport (M3.4, issue #651) ------------------
    # When ``smtp_host`` is empty, :class:`SMTPMailTransport` is a no-op
    # (the magic-link route still mints the token for local-dev / E2E
    # inspection, but no email is sent). In production ``smtp_host``
    # must point at the transactional provider (Resend, Mailgun, ...)
    # and the remaining fields carry the credentials.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    # ``From`` address used in the envelope; ``onboarding@resend.dev``
    # is Resend's test-from (no DNS required). Operators must change
    # it once their domain is verified (see
    # ``scripts/setup_resend_smtp.sh``).
    smtp_from: str = ""

    debug: bool = False

    # --- RBAC: roles allowed to write (issue #144) --------------------
    # ``writer_rols`` is the set of roles that ``require_writer_user``
    # allows through to write routes (POST/PUT/PATCH/DELETE). The
    # ``reader`` role is intentionally excluded: a reader is read-only
    # by definition, and the per-route dep raises 403 otherwise. The
    # source of truth is :class:`app.core.roles.Rol` (regla 4 — one
    # source per domain concept).
    @property
    def writer_rols(self) -> frozenset[str]:
        """Roles allowed to write (POST/PUT/PATCH/DELETE) — issue #144."""
        return frozenset({Rol.DEVELOPER.value, Rol.ADMIN.value, Rol.KEY_USER.value})


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-cached ``Settings`` singleton.

    Implemented as a function (rather than a module-level singleton) so
    that tests and request handlers can obtain the cached instance
    without coupling to import order. ``lru_cache(maxsize=1)`` makes
    repeated calls return the same object; pydantic-settings re-reads
    env + ``.env`` on each ``Settings()`` construction, so this caches
    avoids that overhead on every request. Call
    ``get_settings.cache_clear()`` to force a re-read (used by tests
    that mutate ``APAP_*`` env vars).
    """

    return Settings()
