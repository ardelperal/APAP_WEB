---
description: Agent instructions and code-quality rules for APAP_WEB (FastAPI + HTMX + InsForge backend)
globs: *
alwaysApply: true
---

# APAP_WEB — Agent Instructions

APAP_WEB is a **FastAPI + HTMX + Jinja2** web application (Python `>=3.11`).
It is a server-rendered app with a strict layered architecture: routes handle
HTTP, services own all data access.

## Backend: InsForge (accessed from Python)

The data backend is **InsForge** (PostgreSQL + auth + storage). This project
does **NOT** use the `@insforge/sdk` TypeScript SDK — there is no `package.json`
and no Node frontend. All backend access goes through the Python client in
`app/core/insforge.py`. Treat InsForge as a Postgres-backed BaaS reached over
HTTP from Python.

- **Application logic** (auth, CRUD, storage) → call the Python `InsForgeClient`
  in `app/core/insforge.py`. Never reach for the TS SDK or `npm`.
- **Infrastructure** (schema, buckets, functions, deploy) → use the InsForge MCP
  tools: `run-raw-sql`, `get-table-schema`, `create-bucket`,
  `create-function`, `get-backend-metadata`, etc.
- **Docs**: when you need current InsForge API behavior, fetch it with the
  `fetch-sdk-docs` MCP tool using language `rest-api` (or `typescript` for shape
  reference) — do not rely on memory.

---

## Project Code Quality Rules (APAP_WEB — FastAPI + service layer + InsForge)

You are implementing features in a FastAPI application with a strict layered architecture.
Follow these rules exactly. Each rule includes the reason — understand it, don't just copy the pattern.

### 1. Layer boundaries are absolute

Routes handle HTTP only: form parsing, auth guards, redirects, HTML rendering.
Services handle all data access: SQL, validation, domain logic.
Never call `client.execute_sql(...)` from a route. If the service method doesn't exist yet, create it first — do not bypass the layer as a temporary measure.

WRONG — SQL in route

```python
@router.post("/{id}/delete")
def delete_view(id: str, client = Depends(...)):
    client.execute_sql("UPDATE items SET activo = false WHERE id = $1", [id])
```

RIGHT — route delegates to service

```python
@router.post("/{id}/delete")
def delete_view(id: str, client = Depends(...)):
    service.deactivate_item(client, id)
```

### 2. Dependencies that own resources must use yield

Any dependency that creates an object with a `.close()` method must use `yield` so cleanup is guaranteed — even on exceptions.

WRONG — resource leaked on every request

```python
def get_client() -> InsForgeClient:
    return InsForgeClient(url, key)
```

RIGHT — closed after every request

```python
def get_client():
    client = InsForgeClient(url, key)
    try:
        yield client
    finally:
        client.close()
```

### 3. Configuration is parsed once, not per request

`Settings()` reads environment variables. It must be called once at startup, not on every request. Always cache it.

WRONG

```python
def get_client():
    settings = get_settings()   # parses .env on every call
    return InsForgeClient(settings.url, settings.key)
```

RIGHT

```python
@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

### 4. One source of truth per domain concept

Never define the same values twice. If you have a StrEnum for a domain type, derive any sets or lists from it — don't duplicate.

WRONG — same values in two places, they will diverge

```python
VALID_TYPES = frozenset({"intake", "acogida", "salud"})
class TipoRol(StrEnum):
    INTAKE = "intake"
    ACOGIDA = "acogida"
    SALUD = "salud"
```

RIGHT — one source

```python
class TipoRol(StrEnum):
    INTAKE = "intake"
    ACOGIDA = "acogida"
    SALUD = "salud"

VALID_TYPES = frozenset(r.value for r in TipoRol)
```

### 5. Validation lives in the service, not in routes

Business rules (required fields, enum membership, domain constraints) belong in the service layer. Routes translate the service's `ValueError` into an HTTP response — they do not re-implement the rules.

WRONG — validation duplicated in route

```python
def update_view(...):
    if not form_data.get("name"):
        return render_form(error="name required")   # duplicates service logic
```

RIGHT — service owns validation, route translates the exception

```python
def update_view(...):
    try:
        service.update_item(client, form_data)
    except ValueError as exc:
        return render_form(error=str(exc))
```

### 6. Security defaults deny, not permit

When reading a flag from a session or payload, default to the most restrictive value. A missing field should be treated as the safest option.

WRONG — missing flag grants access

```python
if not payload.get("is_authorized", True):
    redirect("/unauthorized")
```

RIGHT — missing flag denies access

```python
if not payload.get("is_authorized", False):
    redirect("/unauthorized")
```

### 7. Redirects are not exceptions

Use `RedirectResponse` for control flow redirects. Reserve `HTTPException` for actual HTTP error conditions (4xx, 5xx). Mixing them confuses error tracking, middleware, and Sentry.

WRONG — abusing HTTPException for redirect

```python
raise HTTPException(status_code=302, headers={"location": "/login"})
```

RIGHT

```python
return RedirectResponse(url="/login", status_code=302)
```

### Summary checklist before submitting any route or service

- [ ] Does the route call `client.execute_sql(...)` directly? → Move to service.
- [ ] Does any dependency create a closeable resource? → Use yield + finally.
- [ ] Does the code call `get_settings()` more than once in the same request? → Cache it.
- [ ] Is the same domain value list defined twice? → Derive one from the other.
- [ ] Does any auth check default to `True`? → Change to `False`.
- [ ] Does any redirect use `HTTPException`? → Use `RedirectResponse`.

### 8. No deprecated libraries, no DeprecationWarnings

When adding or upgrading a Python dependency in `pyproject.toml`, **the pinned minimum must be a non-deprecated release**. "Deprecated" here means:

- The upstream project has formally EOL'd the major version (e.g. psutil 6.1.x was the last with Python 2.7 support; 7.x is the current line).
- The library emits `DeprecationWarning` on import or basic use in the targeted Python range (here `>=3.11`).
- The library has a published successor and recommends migration.

#### How to verify before pinning

Use the **context7 MCP** to look up the current state of any dependency before adding it to `pyproject.toml`:

1. `mcp__context7__resolve-library-id` with the library name (e.g. "psutil", "fastapi", "pydantic") — pick the most-reputed result.
2. `mcp__context7__query-docs` with the query "latest version current release stable Python 3.11 3.12 recommended install pip" or similar.
3. Read the "Latest version" / "Current stable" line and confirm the version you are pinning is the one upstream considers supported, not a legacy line.

Pin to the **current major.minor floor**, not a legacy line. Example: when adding psutil for `app/core/migration/lock.py`, context7 confirmed 7.2.x is the current stable; we pinned `psutil>=7.0` (the current major's floor) rather than `>=5.9` (a legacy line).

#### How to verify locally after pinning

`pip install -e ".[dev]"` in a fresh venv must succeed **and** `python -c "import thelib"` must not emit any `DeprecationWarning`. The project's pytest suite has `-W error::DeprecationWarning`, so any library warning becomes a CI failure — that's the safety net, not a substitute for checking upstream.

### 9. `log_safe()` is the only allowed logging call in `app/`

Every code path under `app/` that wants to emit a log MUST go through `log_safe(event, **fields)` from `app.core.logging`. Direct calls to `logging.getLogger(__name__).{info,warning,error,debug,critical,exception}(...)` AND `print(...)` are banned in `app/`. The redaction list (12 closed fields) automatically scrubs `email, session_token, jwt, oauth_code, pkce_verifier, csrf_token, pkce_challenge, authorization, cookie, referer, ip_address, x_forwarded_for` from log payloads.

WRONG — raw logger or print

```python
logger.info(f"user {user_id} did X")
print(f"failed: {error}")
```

RIGHT — log_safe

```python
log_safe("user.did_x", user_id=user_id, action="X")
```

Enforcement: APAP003 detector (`scripts/check_rules.py` Detector 5) bans `logger.*` chained calls in `app/`. The new `print_in_app` detector (Detector 6) bans `print(...)` in `app/`. Run via `make check-rules`. `app/core/logging.py` is the only excluded path (it owns the wrapper).

### 10. CSRF defense per default

Every POST/PUT/DELETE/PATCH route MUST be protected by `CsrfMiddleware` (`app/core/csrf.py`). Every form template (`templates/`) MUST render `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">` in every `<form method="post">`. The middleware validates the token via either the `X-CSRFToken` header (for HTMX/fetch) or the `csrf_token` form field (for traditional form posts). Session and PKCE cookies ship with `SameSite=Strict` — `Lax` is a regression.

WRONG — form without CSRF token

```html
<form method="post" action="/users">
  <input name="email" type="email">
  <button type="submit">Submit</button>
</form>
```

RIGHT — form with CSRF token

```html
<form method="post" action="/users">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
  <input name="email" type="email">
  <button type="submit">Submit</button>
</form>
```

Enforcement: `CsrfMiddleware` at runtime returns 403 for missing/invalid tokens. `tests/test_all_post_forms_have_csrf_input.py` (10 cases) and `tests/test_csrf_form_enumeration.py` (10 cases) catch regressions. The new `csrf_middleware_registered` and `csrf_samesite_strict` detectors (`scripts/check_rules.py` Detectors 7 and 8) catch accidental removal from the middleware chain and accidental `Lax` regressions.

### 11. Coverage gate for `CRITICAL_HELPERS`

Helpers in `app/` (functions matching `_row_to_*` regex + the explicit list `{_redirect, _render_form, _is_duplicate_error, _validate_create_params, _build_insert_params}`) MUST have 100% line coverage. If you add a new helper that contains testable product logic, add it to `CRITICAL_HELPERS` in the same PR.

Enforcement: `scripts/pytest_plugin/coverage_gate.py` reads `coverage.json` after pytest and fails the build if any `CRITICAL_HELPERS` entry has <100% line coverage. Helper auto-discovery via `_row_to_*` regex catches new helpers that match the convention; the explicit list is for non-regex helpers.

### 12. Audit doc for sensitive features

If your PR touches auth, secrets, cookies, CSRF, XSS, idempotency, or PII, you MUST create or update a doc in `docs/audits/<feature>-audit-YYYY-Qn.md` with: Scope, Methodology, Findings (severity table), Verdict. Template: `docs/audits/xss-audit-2026-Q2.md`.

Enforcement: PR review (the audit doc is a checklist item). `scripts/check_audit_and_runbook.py` is a developer aid that flags changes to sensitive paths (`app/core/auth*`, `app/core/csrf*`, `app/core/session*`, `app/core/logging*`, `app/core/migration/`) and suggests creating or updating an audit doc.

### 13. Runbook for code requiring operator action

If your PR introduces or changes a secret rotation, manual deploy step, cache invalidation, cron trigger, env-var change, or any operation the user must perform manually, you MUST create a runbook in `docs/runbooks/<thing>.md` with sections: When to trigger, Pre-deploy checklist, Deploy steps, Verification, Rollback. Reference the runbook from the PR description.

Enforcement: PR review. `scripts/check_audit_and_runbook.py` flags changes to `app/core/config.py` (env-var settings) and suggests runbook creation. The check is a developer aid, not a CI gate — the operator responsibility is documented in the PR.

---

> **History:** the resolved "Known conflicts with existing code" tracker (all
> rows DONE during the `hardening-2026-q2` chain) was moved out of this file to
> [`docs/hardening-2026-q2-rule-history.md`](docs/hardening-2026-q2-rule-history.md).
> This file carries only the live rules.
