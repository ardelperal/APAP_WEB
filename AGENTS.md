---
description: Instructions building apps with MCP
globs: *
alwaysApply: true
---

# InsForge SDK Documentation - Overview

## What is InsForge?

Backend-as-a-service (BaaS) platform providing:

- **Database**: PostgreSQL with PostgREST API
- **Authentication**: Email/password + OAuth (Google, GitHub)
- **Storage**: File upload/download
- **AI**: OpenRouter key provisioning and model catalog for direct OpenAI-compatible integrations
- **Functions**: Serverless function deployment
- **Realtime**: WebSocket pub/sub (database + client events)

## Installation

The following is a step-by-step guide to installing and using the InsForge TypeScript SDK for Web applications. If you are building other types of applications, please refer to:
- [Swift SDK documentation](/sdks/swift/overview) for iOS, macOS, tvOS, and watchOS applications.
- [Kotlin SDK documentation](/sdks/kotlin/overview) for Android applications.
- [REST API documentation](/sdks/rest/overview) for direct HTTP API access.

### 🚨 CRITICAL: Follow these steps in order

### Step 1: Download Template

Use the `download-template` MCP tool to create a new project with your backend URL and anon key pre-configured.

### Step 2: Install SDK

```bash
npm install @insforge/sdk@latest
```

### Step 3: Create SDK Client

You must create a client instance using `createClient()` with your base URL and anon key:

```javascript
import { createClient } from '@insforge/sdk';

const client = createClient({
  baseUrl: 'https://your-app.region.insforge.app',  // Your InsForge backend URL
  anonKey: 'your-anon-key-here'       // Get this from backend metadata
});

```

**API BASE URL**: Your API base URL is `https://your-app.region.insforge.app`.

## Getting Detailed Documentation

### 🚨 CRITICAL: Always Fetch Documentation Before Writing Code

InsForge provides official SDKs and REST APIs, use them to interact with InsForge services from your application code.

- [TypeScript SDK](/sdks/typescript/overview) - JavaScript/TypeScript
- [Swift SDK](/sdks/swift/overview) - iOS, macOS, tvOS, and watchOS
- [Kotlin SDK](/sdks/kotlin/overview) - Android and Kotlin Multiplatform
- [REST API](/sdks/rest/overview) - Direct HTTP API access

Before writing or editing any InsForge integration code, you **MUST** call the `fetch-docs` or `fetch-sdk-docs` MCP tool to get the latest SDK documentation. This ensures you have accurate, up-to-date implementation patterns.

### Use the InsForge `fetch-docs` MCP tool to get specific SDK documentation:

Available documentation types:

- `"instructions"` - Essential backend setup (START HERE)
- `"real-time"` - Real-time pub/sub (database + client events) via WebSockets
- `"db-sdk-typescript"` - Database operations with TypeScript SDK
- **Authentication** - Choose based on implementation:
  - `"auth-sdk-typescript"` - TypeScript SDK methods for custom auth flows
  - `"auth-components-react"` - Pre-built auth UI for React+Vite (single-page app)
  - `"auth-components-react-router"` - Pre-built auth UI for React(Vite+React Router) (multi-page app)
  - `"auth-components-nextjs"` - Pre-built auth UI for Next.js (SSR app)
- `"storage-sdk"` - File storage operations
- `"functions-sdk"` - Serverless functions invocation
- `"ai-integration-sdk"` - AI integration with the provisioned OpenRouter key and OpenAI SDK
- `"deployment"` - Deploy frontend applications via MCP tool
- `"payments"` - Stripe Checkout, Billing Portal, webhook projections, and fulfillment patterns

These docs are mostly for the TypeScript SDK. For other languages, you can also use the `fetch-sdk-docs` MCP tool to get specific documentation.

### Use the InsForge `fetch-sdk-docs` MCP tool to get specific SDK documentation

You can fetch SDK documentation using the `fetch-sdk-docs` MCP tool with a specific feature type and language.

Available feature types:
- `db` - Database operations
- `storage` - File storage operations
- `functions` - Serverless functions invocation
- `auth` - User authentication
- `ai` - AI integration with the provisioned OpenRouter key and OpenAI SDK
- `realtime` - Real-time pub/sub (database + client events) via WebSockets
- `payments` - Stripe Checkout and Billing Portal with webhook-based fulfillment

Available languages:
- `typescript` - JavaScript/TypeScript SDK
- `swift` - Swift SDK (for iOS, macOS, tvOS, and watchOS)
- `kotlin` - Kotlin SDK (for Android and JVM applications)
- `rest-api` - REST API

Payments currently has TypeScript SDK docs only. Use the Payments API reference for non-TypeScript clients.

## When to Use SDK vs MCP Tools

### Always SDK for Application Logic:

- Authentication (register, login, logout, profiles)
- Database CRUD (select, insert, update, delete)
- Storage operations (upload, download files)
- AI integration via the provisioned OpenRouter key with the OpenAI SDK or OpenRouter HTTP API
- Serverless function invocation
- Payments checkout and customer portal session creation

### Use MCP Tools for Infrastructure:

- Project scaffolding (`download-template`) - Download starter templates with InsForge integration
- Backend setup and metadata (`get-backend-metadata`)
- Database schema management (`run-raw-sql`, `get-table-schema`)
- Storage bucket creation (`create-bucket`, `list-buckets`, `delete-bucket`)
- Serverless function deployment (`create-function`, `update-function`, `delete-function`)
- Frontend deployment (`create-deployment`) - Deploy frontend apps to InsForge hosting

## Important Notes

- For auth: use `auth-sdk` for custom UI, or framework-specific components for pre-built UI
- SDK returns `{data, error}` structure for all operations
- Database inserts require array format: `[{...}]`
- Serverless functions have one endpoint and do not support nested route paths
- Storage: Upload files to buckets, store URLs in database
- AI integrations should call OpenRouter directly with `baseURL: "https://openrouter.ai/api/v1"` and a server-side `OPENROUTER_API_KEY`
- **EXTRA IMPORTANT**: Use Tailwind CSS 3.4 (do not upgrade to v4). Lock these dependencies in `package.json`

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

### Known conflicts with existing code (do not silently fix — see follow-up plan)

These rules are forward-looking. They are violated by code that pre-dates the rule; each row carries the follow-up plan that closes the gap.

| Rule | Where | Reason it still exists | Follow-up |
|---|---|---|---|
| 4 — one source of truth | ~~`app/core/auth.py:30` (`VALID_ROLES` hardcoded) and `app/modules/voluntarios/service.py:47` (`VALID_ROL_TYPES` hardcoded)~~ | ~~The `StrEnum` for roles does not exist yet. The frozenset is the only source.~~ | **DONE** — Slice 2 (PR-2). `VALID_ROLES` and `VALID_ROL_TYPES` are now derived from their `StrEnum`s; the inline `CHECK (rol IN (...))` in `CREATE_TABLE_SQL` was removed; migration `004_drop_rol_check.sql` cleans up the constraint on databases deployed before PR-2. See `openspec/changes/hardening-2026-q2/specs/02-rule-4-ddl/spec.md` and audit `engram:14516`. |
| ~~6 — defaults deny~~ **DONE** | ~~`app/core/auth_dependencies.py:80` uses `payload.get("is_authorized", True)` (default permits)~~ — **FIXED at PR-3 of hardening-2026-q2** | Was deliberate: pre-fix cookies didn't carry the flag. The default `True` kept them working. | ~~Flip default to `False` once all live sessions have expired AND pre-fix cookies invalidated.~~ **DONE — Slice 3 PR-3 flipped both call sites (`app/main.py:165` middleware + `app/core/auth_dependencies.py:130` dependency) to `payload.get("is_authorized", False)`. For pre-fix cookies still in flight, rotate `APAP_SESSION_SECRET` per [`docs/runbooks/cookie-rotation.md`](runbooks/cookie-rotation.md). The runbook is the operator procedure for that rotation.** |
| 7 — no `HTTPException` for redirects | `app/core/auth_dependencies.py:77-83` raises `HTTPException(302, headers={"location": ...})` for both `/login` and `/unauthorized` redirects | Pre-existing pattern; works because FastAPI's `HTTPException` honors the `Location` header and 302 status. | Replace with `Response(status_code=302, headers={"location": ...})` or change the guards to return `RedirectResponse` directly. Pure refactor; public behavior unchanged. **Slated for Slice 5 (Auth hardening) per the audit at `docs/audits/auth-dependencies-audit-2026-Q2.md`.** |

### 8 — No deprecated libraries, no DeprecationWarnings

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