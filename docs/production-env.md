# Production env reference

Single-page operator reference for every `APAP_*` env var declared in
[`app/core/config.py`](../app/core/config.py). Each table below maps
one concern group to the canonical doc anchor, the pydantic-settings
default, and the `StartupConfigError` rule that fires when the value
is missing or invalid at boot. Sorted alphabetically within each
concern.

## 1. InsForge (data, auth, storage)

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_INSFORGE_ANON_KEY` | InsForge | [`app/core/config.py`](../app/core/config.py) | no | `""` | none (Pydantic str default; empty is legal) |
| `APAP_INSFORGE_SERVICE_KEY` | InsForge | [`app/core/config.py`](../app/core/config.py) | yes | `""` | `StartupConfigError(APAP_INSFORGE_SERVICE_KEY, "empty")` when empty and `APAP_DEBUG=false` |
| `APAP_INSFORGE_URL` | InsForge | [`app/core/insforge_url.py`](../app/core/insforge_url.py) | yes | `http://localhost:7130` | none (Pydantic str default; non-empty override at runtime) |

## 2. Google OAuth

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_GOOGLE_CLIENT_ID` | Google OAuth | [`app/core/config.py`](../app/core/config.py) | yes | `""` | none (empty disables the OAuth route; operator-set expected) |
| `APAP_GOOGLE_CLIENT_SECRET` | Google OAuth | [`app/core/config.py`](../app/core/config.py) | yes | `""` | none (empty disables the OAuth route; operator-set expected) |
| `APAP_GOOGLE_REDIRECT_URI` | Google OAuth | [`app/core/config.py`](../app/core/config.py) | yes | `http://127.0.0.1:8000/auth/callback` | none (must match the value registered in Google Cloud Console) |

## 3. Session

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_SESSION_SECRET` | Session | [`app/core/config.py`](../app/core/config.py) | yes | `dev-only-change-me-in-production` | `StartupConfigError(APAP_SESSION_SECRET, "placeholder")` when value equals the published placeholder; `StartupConfigError(APAP_SESSION_SECRET, "too_short")` when length < 32 chars (both bypassed when `APAP_DEBUG=true`) |

## 4. Bootstrap / RBAC

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_INITIAL_ADMIN_EMAIL` | Bootstrap | [`app/core/config.py`](../app/core/config.py) | no | `""` | none (empty disables the bootstrap admin seeding) |

## 5. CSRF

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_CSRF_ENABLED` | CSRF | [`app/core/csrf.py`](../app/core/csrf.py) | yes | `true` | none (Pydantic bool default; runtime warning when false) |

## 6. Rate limiting

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_RATE_LIMIT_ENABLED` | Rate limiting | [`app/core/rate_limit.py`](../app/core/rate_limit.py) | yes | `true` | none (Pydantic bool default; runtime short-circuit when false) |
| `APAP_RATE_LIMIT_OAUTH_PER_MIN` | Rate limiting | [`app/core/config.py`](../app/core/config.py) | yes | `10` | none (Pydantic int default) |
| `APAP_RATE_LIMIT_WRITE_PER_MIN_IP` | Rate limiting | [`app/core/config.py`](../app/core/config.py) | yes | `30` | none (Pydantic int default) |
| `APAP_RATE_LIMIT_WRITE_PER_MIN_USER` | Rate limiting | [`app/core/config.py`](../app/core/config.py) | yes | `60` | none (Pydantic int default) |
| `APAP_TRUST_XFF` | Rate limiting | [`app/core/config.py`](../app/core/config.py) | yes | `false` | none (Pydantic bool default; set true ONLY behind a trusted proxy) |

## 7. Auth cache

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_AUTH_CACHE_BACKEND` | Auth cache | [`app/core/config.py`](../app/core/config.py) | no | `in_process` | Pydantic `Literal["in_process"]` rejects any other value at settings construction; lifespan emits `startup.config_invalid` and the app fails fast |
| `APAP_AUTH_CACHE_TTL_SECONDS` | Auth cache | [`app/core/config.py`](../app/core/config.py) | no | `300` | none (Pydantic int default) |

## 8. Logging

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_DEBUG` | Logging | [`app/core/config.py`](../app/core/config.py) | yes | `false` | none (Pydantic bool default; bypasses `_validate_secrets` when true) |
| `APAP_LOG_LEVEL` | Logging | [`app/core/logging.py`](../app/core/logging.py) | no | `INFO` | none (unknown values fall back to INFO at runtime) |
| `APAP_MODE` | Logging | [`app/core/config.py`](../app/core/config.py) | yes | `web` | none (Pydantic str default; rate-limit middleware short-circuits when `test`) |

## 9. E2E (test-only OAuth mock)

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_E2E_AUTH_DEFAULT_EMAIL` | E2E | [`app/core/config.py`](../app/core/config.py) | no | `e2e@apap.local` | none (Pydantic str default) |
| `APAP_E2E_AUTH_ENABLED` | E2E | [`app/core/e2e_auth.py`](../app/core/e2e_auth.py) | no | `false` | none (Pydantic bool default; production MUST be false — see audit) |
| `APAP_E2E_AUTH_SECRET` | E2E | [`app/core/config.py`](../app/core/config.py) | no | `""` | none (Pydantic str default; mock route rejects mismatched header) |

## 10. M0 local backend (POST-M0, MONITORING-ONLY)

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_APP_BASE_URL` | M0 local backend | [`app/core/local_backend/app.py`](../app/core/local_backend/app.py) | no | `""` | none (consumed at request time by ConsoleMailTransport) |
| `APAP_INSFORGE_URL_OVERRIDE` | M0 local backend | [`app/core/insforge_url.py`](../app/core/insforge_url.py) | no | `http://localhost:8000` | none (consumed at request time when `APAP_LOCAL_BACKEND=true`) |
| `APAP_LOCAL_BACKEND` | M0 local backend | [`app/core/insforge_url.py`](../app/core/insforge_url.py) | no | `false` | none (truthy `1|true|yes|on` flips the InsForge URL switch) |
| `APAP_LOCAL_DB_SCHEMA` | M0 local backend | [`app/core/local_backend/app.py`](../app/core/local_backend/app.py) | no | `""` | none (consumed at request time by the Postgres adapter) |
| `APAP_LOCAL_DB_URL` | M0 local backend | [`app/core/local_backend/app.py`](../app/core/local_backend/app.py) | no | `""` | none (consumed at request time by the Postgres adapter) |
| `APAP_SMTP_FROM` | M0 local backend | [`app/core/auth_magic/mail_transports.py`](../app/core/auth_magic/mail_transports.py) | no | `noreply@apap.local` | none (consumed at request time; M1.5 placeholder) |
| `APAP_SMTP_HOST` | M0 local backend | [`app/core/auth_magic/get_mail_transport.py`](../app/core/auth_magic/get_mail_transport.py) | no | `""` | none (selects SMTPMailTransport when non-empty; placeholder raises NotImplementedError today) |
| `APAP_SMTP_PASSWORD` | M0 local backend | [`app/core/auth_magic/mail_transports.py`](../app/core/auth_magic/mail_transports.py) | no | `""` | none (consumed at request time; M1.5 placeholder) |
| `APAP_SMTP_PORT` | M0 local backend | [`app/core/auth_magic/mail_transports.py`](../app/core/auth_magic/mail_transports.py) | no | `587` | none (consumed at request time; M1.5 placeholder) |
| `APAP_SMTP_USER` | M0 local backend | [`app/core/auth_magic/mail_transports.py`](../app/core/auth_magic/mail_transports.py) | no | `""` | none (consumed at request time; M1.5 placeholder) |

## 11. M1 magic-link (POST-M1, MONITORING-ONLY)

| Var name | Concern | Doc anchor | Required? | Default | Startup check |
|---|---|---|---|---|---|
| `APAP_AUTH_ENABLE_MAGIC_LINK` | M1 magic-link | [`app/core/auth_magic/routes.py`](../app/core/auth_magic/routes.py) | no | `false` | none (truthy `1|true|yes|on` registers `POST /auth/magic/start`; production MUST be false until M1.5) |

## Cross-references

- [`.env.example`](../.env.example) — template form with `Default:` and `Production required:` lines per block.
- [`docs/runbooks/coolify-deploy.md`](runbooks/coolify-deploy.md) — 7-step deploy + verify + rollback runbook.
- [`app/core/config.py`](core/config.py) — pydantic-settings class with the canonical defaults.
- [`app/core/config.py::_validate_secrets`](core/config.py) — the `StartupConfigError` rules for `APAP_INSFORGE_SERVICE_KEY` and `APAP_SESSION_SECRET`.
