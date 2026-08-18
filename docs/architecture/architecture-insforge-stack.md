# APAP Application Architecture Stack

[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

## Decision

Build the application as a small internal web app using a server-rendered backend with HTMX, while using InsForge as the managed platform for data and infrastructure.

```text
Browser
  - HTML
  - HTMX 2.0
  - Tailwind CSS 4.3
        |
        v
FastAPI application backend / BFF
  - Jinja2 templates
  - business rules
  - authorization checks (allowlist)
  - DAO migration/adaptation layer
        |
        v
InsForge
  - PostgreSQL + PostgREST
  - Auth (Google OAuth)
  - Storage / S3-style buckets
  - Functions, only where useful
  - Realtime, only if a feature needs it
```

## Quick path

- Frontend: HTMX 2.0.4 + Jinja2 + Tailwind 4.3 (server-rendered, no SPA).
- Backend: FastAPI 0.136.x with Pydantic 2.13.x, served by Uvicorn 0.49.x.
- Data: InsForge (PostgreSQL + Auth + Storage + Functions + Realtime).
- Deploy: Coolify on the VPS, webhook on push to `main`.
- Auth: Google OAuth via InsForge + allowlist in `authorized_users`.

If a stack component must change, fill the "When this changes" section first.

## Problem statement

The team needs an internal web app for a small number of users (volunteers, key users) to manage the APAP refuge operations. The app must:

- cover CRUD/backoffice workflows without SEO or public-facing concerns;
- keep business rules and authorization server-side, never in the browser;
- delegate infrastructure (PostgreSQL, Auth, Storage) to a managed backend to avoid ops overhead;
- survive the migration from the Access/VBA legacy while preserving 100% of legacy functionality (see [`decisiones-proyecto.md`](decisiones-proyecto.md) D-05).

Without a fixed stack, contributors introduce new technologies PR-by-PR, fragmenting the codebase and slowing onboarding. The team is small and cannot absorb per-PR stack decisions.

## Evidence and scope

| Evidence | Location |
|---|---|
| Pinned backend versions | [`pyproject.toml`](../../pyproject.toml) — FastAPI 0.136.x, Pydantic 2.13.x, HTTPX 0.28.x, python-multipart 0.0.32 |
| ASGI server | [`pyproject.toml`](../../pyproject.toml) — Uvicorn 0.49.x |
| InsForge client | [`app/core/insforge.py`](../../app/core/insforge.py) — Python HTTP client, no `@insforge/sdk` TS |
| Tailwind v4 setup | [`tailwindcss/`](../../tailwindcss/) — CSS-first config, no `tailwind.config.js` |
| Dockerfile for deploy | [`Dockerfile`](../../Dockerfile) — production image |
| Coolify app | `apap-web` on the VPS — deploys from `ardelperal/APAP_WEB:main` |
| InsForge usage | application code via SDK or REST; MCP tools only for infra |
| Allowlist table | `authorized_users` table (PostgreSQL on InsForge) |
| Architecture decision | [`decisiones-proyecto.md` D-20](decisiones/d-20-stack-fastapi-htmx-insforge.md) |

## Options considered

| Area | Option | Pros | Cons | Decision |
|---|---|---|---|---|
| Frontend approach | HTMX over SPA | Small user count, no SEO, mostly CRUD. No JS state duplication. | No rich client-side state by default. | accepted |
| Frontend approach | React / Next.js SPA | Rich interactivity, mature ecosystem. | Doubles stack (TS + Python); no need for current audience. | rejected |
| Backend framework | FastAPI | Async-native, type hints, Pydantic ecosystem. | Younger than Django. | accepted |
| Backend framework | Django + DRF | Mature, batteries included. | ORM-heavy; less flexible for BaaS. | rejected |
| Templates | Jinja2 | Server-rendered, no JS UI duplication. | Less interactive than SPA. | accepted |
| Data validation | Pydantic 2 | Schema validation, settings management. | Couples app code to Pydantic types. | accepted |
| HTTP client | HTTPX | Async, used for InsForge REST calls. | None material. | accepted |
| Styling | Tailwind CSS v4 | CSS-first, fast compile, design tokens. | Requires Node CLI in build pipeline. | accepted |
| Hosting | Coolify on VPS | Self-hosted, simple webhook on `main`. | Single VPS dependency. | accepted |
| Hosting | Vercel + managed Postgres | Quick deploys. | Vendor lock-in; per-request pricing. | rejected |
| BaaS | InsForge | Postgres + Auth + Storage in one. | Vendor lock-in to one BaaS. | accepted |
| BaaS | Supabase | Same shape, larger community. | Different cost model; no team requirement to switch. | rejected |
| Attachments | InsForge Storage + metadata in Postgres | Traceability, permissions, retention. | Two services to coordinate. | accepted |
| Attachments | Files in Postgres bytea | Simpler. | Bloats DB; no CDN; bad for large files. | rejected |
| Auth | Google OAuth via InsForge + allowlist | No password storage; small user list. | Requires Google account; allowlist management. | accepted |
| Auth | Email + password in Postgres | Self-contained. | Password management overhead; breach risk. | rejected |

## Stack

| Area | Decision | Version | Notes |
|---|---|---|---|
| Frontend approach | HTMX over SPA | 2.0.4 | The app is for a small number of users, does not need SEO, and is expected to be mostly CRUD/backoffice workflows. |
| Backend app | FastAPI | 0.136.3 | FastAPI acts as the real application backend/BFF and returns full pages or HTML partials for HTMX. |
| ASGI server | Uvicorn | 0.49.0 | Production-grade ASGI server for FastAPI. |
| Templates | Jinja2 | 3.1.x | Keep view rendering server-side and avoid duplicating UI state in JavaScript. |
| Data validation | Pydantic | 2.13.4 | Schema validation, settings management, and serialization. |
| HTTP client | HTTPX | 0.28.1 | Async HTTP client for calling InsForge REST APIs. |
| Form handling | python-multipart | 0.0.32 | Required for file uploads and form parsing in FastAPI. |
| Styling | Tailwind CSS | 4.3.1 | CSS-first configuration, Rust-based engine. Use Node.js CLI for compilation. |
| Managed backend platform | InsForge | - | Use InsForge for PostgreSQL, Auth, Storage, Functions, Realtime, and AI infrastructure when needed. |
| Application hosting | Coolify on the project VPS | - | Deploy the FastAPI/HTMX application through Coolify. |
| Attachments | InsForge Storage | - | Store binary files in object storage; store only metadata and references in PostgreSQL. |
| Data model | Redesign allowed | - | Do not inherit legacy schema debt if a cleaner model is needed. |
| Legacy compatibility | DAO migration/adaptation required | - | Any data-model redesign must include a migration path for the current DAOs. |

## Goals

- A single pinned stack with no per-PR technology choices.
- InsForge absorbs infra (Postgres, Auth, Storage) — the team does not operate a Postgres.
- Server-rendered UI with progressive interactivity via HTMX.
- Two-layer security: OAuth (InsForge) + allowlist (FastAPI).
- All AI / OpenRouter integrations routed through FastAPI; no privileged keys reach the browser.
- Attachment binaries in InsForge Storage; metadata in PostgreSQL.

## Non-goals

- Build a React / Next.js SPA by default.
- Store attachment binaries in PostgreSQL by default.
- Expose privileged InsForge keys to the browser.
- Inherit legacy data-model debt only for convenience.
- Use InsForge MCP tools as application runtime code.

## Non-negotiable invariants

- **Stack change requires documented trade-off**: HTMX 2.0.4, FastAPI 0.136.x, Pydantic 2.13.x, Tailwind 4.3.x, and InsForge are the baseline. Replacing one requires an issue with the "When this changes" section filled in.
- **InsForge SDK or REST from the app, MCP only from infra**: application code calls the Python SDK or the REST APIs of InsForge; MCP tools (`run-raw-sql`, `create-bucket`, `create-function`, etc.) are for schema, bucket and function setup. Mixing both breaks the boundary of who touches what.
- **Allowlist authorization, not implicit roles**: the `authorized_users` table is the single source of truth for access. OAuth decides who you are; the allowlist decides who is let in.
- **Coolify + Dockerfile for deploy**: the web app is served via Coolify from `ardelperal/APAP_WEB:main`. Hardcoding InsForge credentials in the repo or skipping Coolify for an ad-hoc deploy is forbidden.
- **Attachments in Storage, metadata in PostgreSQL**: binaries live in InsForge Storage buckets; PostgreSQL only stores `owner_type`, `bucket`, `storage_path`, metadata and status. The storage path is never the source of truth.
- **Model design first, legacy inheritance second**: when the legacy model drags technical debt, it is redesigned; every incompatible change comes with a DAO migration plan documented in [`decisiones-proyecto.md`](decisiones-proyecto.md).
- **OpenRouter and API keys server-side only**: no privileged key reaches the browser. Every AI integration passes through FastAPI.

## Branch and deployment policy

`main` remains the production branch for APAP_WEB. GitHub uses `main` as the default branch, and the Coolify `apap-web` application is configured to deploy from `ardelperal/APAP_WEB:main`.

Normal implementation work targets `main` directly (see [`decisiones-proyecto.md` D-30](decisiones/d-30-pre-mvp-single-branch.md)). CI runs on PRs/pushes to `main`; the production deploy trigger remains guarded on pushes to `main`. The full UAT-gated staging channel is still future D-CD-03 scope.

## InsForge usage rules

Always fetch the relevant InsForge docs before writing integration code.

Use the InsForge SDK or REST APIs from application code for:

- authentication;
- database CRUD;
- storage upload/download;
- serverless function invocation;
- realtime events;
- AI/OpenRouter integrations.

Use InsForge MCP tools only for infrastructure tasks:

- downloading the starter template;
- reading backend metadata;
- creating or changing database schema;
- creating storage buckets;
- creating/updating/deleting edge functions;
- deploying the frontend/application when applicable.

Important InsForge constraints:

- SDK responses use a `{ data, error }` shape.
- Database inserts use array payloads: `[{ ... }]`.
- Edge functions have one endpoint and do not support nested route paths.
- OpenRouter/API keys must stay server-side.

## Available MCP tools

### InsForge MCP

Use for backend infrastructure management:

| Action | Tool | Notes |
|---|---|---|
| Download starter template | `insforge_download-template` | Creates a new project with InsForge pre-configured |
| Get backend metadata | `insforge_get-backend-metadata` | Lists all tables, buckets, functions |
| Get table schema | `insforge_get-table-schema` | Returns schema for a specific table |
| Run raw SQL | `insforge_run-raw-sql` | Admin-only; use with caution |
| Create storage bucket | `insforge_create-bucket` | For file uploads |
| List storage buckets | `insforge_list-buckets` | |
| Create edge function | `insforge_create-function` | |
| Update edge function | `insforge_update-function` | |
| Delete edge function | `insforge_delete-function` | |
| Get function details | `insforge_get-function` | |
| Fetch SDK docs | `insforge_fetch-sdk-docs` | Get SDK documentation for specific features |

### Coolify MCP

Use for deployment and runtime configuration on the VPS:

| Action | Tool | Notes |
|---|---|---|
| Get server info | `coolify_get_server` | View server status and details |
| List servers | `coolify_list_servers` | List all connected servers |
| List applications | `coolify_list_apps` | See all deployed apps |
| Create application | `coolify_create_app` | New app deployment |
| Get application | `coolify_get_application` | View app details |
| Delete application | `coolify_delete_app` | Remove an app |
| Get application logs | `coolify_application_logs` | Debug deployment issues |
| Validate server | `coolify_validate_server` | Check server connection |
| Get server domains | `coolify_server_domains` | List domains on server |
| Get server resources | `coolify_server_resources` | View resources on server |
| Get infrastructure overview | `coolify_get_infrastructure_overview` | Summary of all resources |
| Diagnose app | `coolify_diagnose_app` | Check app health |
| Diagnose server | `coolify_diagnose_server` | Check server health |
| Manage environment variables | `coolify_env_vars` | Set InsForge secrets, DB passwords, etc. |
| Create/update service | `coolify_service` | For Docker Compose services |
| Manage SSH keys | `coolify_private_keys` | Server access management |
| Validate server connection | `coolify_validate_server` | Test MCP connectivity |

## Frontend architecture

Use HTMX for progressive interactivity:

- forms that submit without full-page reloads;
- table/list refreshes;
- validation feedback;
- modal or panel updates;
- small workflow transitions.

Avoid building a React/SPA frontend unless a future requirement proves the need for rich client-side state, complex drag/drop, offline behavior, or highly interactive dashboards.

The browser should not become the business-logic layer. Keep rules and authorization in FastAPI.

## FastAPI backend responsibilities

FastAPI is the application boundary. It should own:

- route handlers for pages and HTMX partials;
- business rules;
- permissions and authorization checks;
- request validation;
- orchestration across InsForge services;
- mapping between the clean data model and any legacy DAO compatibility layer;
- attachment metadata lifecycle;
- audit-friendly error handling.

## Authentication and authorization

### Overview

The application uses a two-layer security model:

1. **Authentication** (who are you): Google OAuth via InsForge.
2. **Authorization** (are you allowed): allowlist-based check in FastAPI.

Only authorized personnel can access the application. Unauthorized users see a friendly "access denied" page.

### Authentication flow

```text
User tries to access app
        ↓
Already logged in? ──No──→ Redirect to Google OAuth (InsForge)
        ↓ Yes
Email in authorized_users? ──No──→ Show "Acceso no autorizado" page
        ↓ Yes
Role = developer? ──Yes──→ Full access (including admin panel)
        ↓ No
Key user access (normal app)
```

### Database: `authorized_users` table

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `email` | text | Authorized Gmail address (unique) |
| `role` | text | `developer` or `key_user` |
| `added_by` | UUID | Who added this user |
| `created_at` | timestamp | When added |

### Roles

| Role | Access level |
|---|---|
| `developer` | Full access: admin panel, user management, all features |
| `key_user` | Standard access: normal app features only |

### Middleware behavior

FastAPI middleware checks authorization on every request:

1. Extract user email from InsForge JWT token.
2. Query `authorized_users` table.
3. If email found → allow request, attach role to request state.
4. If email not found → redirect to `/unauthorized`.

### Admin panel (developer only)

A protected section of the app where the developer can:

- list all authorized users;
- add a new user (email + role);
- remove a user;
- view audit log of who added whom.

Only accessible when `role = developer`. Key users see no trace of this panel.

### Implementation notes

- Do not store passwords; rely entirely on Google OAuth via InsForge.
- The `authorized_users` table is the single source of truth for access control.
- InsForge handles session tokens, refresh, and OAuth flow.
- FastAPI only checks the email against the allowlist after OAuth succeeds.
- The `/unauthorized` page should be helpful: explain that access requires authorization and provide contact info for the developer.

## Tailwind CSS v4 setup

Tailwind CSS v4 uses CSS-first configuration (no `tailwind.config.js`). For FastAPI integration:

```text
project/
  tailwindcss/           # Node.js tooling lives here
    package.json
    styles/
      app.css            # @import "tailwindcss"; + @source directives
  app/
    static/
      css/
        output.css       # Compiled output (gitignored)
  templates/
    base.html            # <link rel="stylesheet" href="/static/css/output.css">
```

Development workflow:

- `npm install -D tailwindcss @tailwindcss/cli` in `tailwindcss/` folder.
- `npx @tailwindcss/cli -i ./styles/app.css -o ../app/static/css/output.css --watch`.
- FastAPI serves `app/static/` as mounted static files.

Production: compile CSS during Docker build, serve the minified output.

## Deployment target

Deploy the FastAPI/HTMX application through Coolify on the VPS.

The expected deployment shape is:

```text
Coolify on VPS
        |
        v
FastAPI application container
  - serves Jinja2 pages and HTMX partials
  - uses environment variables for InsForge URLs and keys
        |
        v
InsForge managed services
```

When the Coolify MCP is available, use it for deployment and runtime configuration tasks. Do not hardcode InsForge credentials in the repository; configure them as Coolify environment variables.

Recommended project shape:

```text
app/
  main.py
  core/
    config.py
    security.py
  modules/
    <domain>/
      routes.py
      service.py
      repository.py
      schemas.py
      templates/
  templates/
    base.html
  static/
```

The exact module names should follow the final domain model, not the legacy database table names by default.

## Data model policy

The new application must not blindly copy the existing data model.

When the legacy model creates technical debt, redesign it.

However, every incompatible change must include a DAO migration/adaptation plan:

- map current table/field names to the new model;
- identify removed, renamed, split, or merged concepts;
- define SQL migrations or import scripts;
- define temporary adapters/bridges for existing DAOs if needed;
- prove that behavior required by the current app is preserved or intentionally replaced;
- document data cleanup assumptions and non-reversible transformations.

The preferred direction is a clean domain model plus explicit migration, not a new app constrained by old schema mistakes.

## Attachments / anexos

Store attachment binaries in InsForge Storage, not directly in PostgreSQL.

PostgreSQL should store attachment metadata, for example:

| Field | Purpose |
|---|---|
| `id` | Attachment identity. |
| `owner_type` / `owner_id` | Entity that owns the attachment. |
| `bucket` | InsForge storage bucket. |
| `storage_path` | Object path inside the bucket. |
| `original_filename` | Filename uploaded by the user. |
| `mime_type` | Content type. |
| `size_bytes` | File size. |
| `checksum` | Optional integrity check. |
| `created_by` / `created_at` | Audit metadata. |
| `status` | Active, deleted, replaced, quarantined, etc. |

Do not treat storage paths as the only source of truth. The metadata table is required for traceability, permissions, retention, and migration.

## Consequences

### What changes by adopting this stack

- A single pinned stack with no per-PR technology choices (see `pyproject.toml`).
- InsForge absorbs infra; the team does not operate its own Postgres.
- Authorization is two-layer (OAuth + allowlist); passwords are never stored.
- Attachment binaries go to InsForge Storage; metadata stays in Postgres.
- Deploys run via Coolify from `ardelperal/APAP_WEB:main`; credentials live in Coolify env vars, never in the repo.

### What does not change

- The Access/VBA legacy remains the source of truth during the migration (see [`decisiones-proyecto.md` D-05](decisiones/d-05-fidelidad-legacy-superset.md)).
- The pre-MVP single-branch workflow stays in place (see [`decisiones-proyecto.md` D-30](decisiones/d-30-pre-mvp-single-branch.md)).
- The team continues to be small; per-PR technology introductions remain discouraged.

### Operational consequences

- [`pyproject.toml`](../../pyproject.toml) is pinned; updates require explicit PRs.
- Coolify is the deploy boundary; no ad-hoc deploys.
- Each PR adding an InsForge endpoint must use the SDK or REST APIs (no MCP tools at runtime).
- New tables in Postgres come with a DAO migration plan if they diverge from legacy.

## When this changes

Do not switch stacks lightly. The baseline holds unless one of the following becomes true:

- the UI requires heavy client-side state or complex real-time interactions;
- offline-first behavior becomes required;
- the app becomes public-facing and SEO becomes important;
- the team strongly standardizes on another backend framework;
- InsForge constraints prevent a critical domain requirement.

If one of those happens, document the trade-off before changing the stack. Specifically:

- **Frontend SPA adoption**: open D-STACK-02 with the interactivity cases that HTMX cannot cover.
- **Backend framework swap**: open D-STACK-03 with benchmarks and migration cost.
- **InsForge exit**: open D-STACK-04 with the replacement BaaS and data migration plan.
- **Public-facing + SEO**: open D-STACK-05 with the public URL strategy and SEO requirements.

Any swap must update this ADR or supersede it with a successor.

## Implementation checklist for a future AI

- [ ] Fetch current InsForge instructions before writing integration code.
- [ ] If starting from scratch, use the InsForge template first.
- [ ] Use Tailwind CSS 4.3 with Node.js CLI for compilation.
- [ ] Build FastAPI routes that return pages and HTMX partials.
- [ ] Keep business rules and authorization in FastAPI, not in HTMX snippets.
- [ ] Design the clean PostgreSQL model before preserving legacy tables.
- [ ] Create `authorized_users` table with email, role, added_by, created_at.
- [ ] Implement FastAPI middleware for allowlist-based authorization.
- [ ] Build admin panel for developer to manage authorized users.
- [ ] Prepare DAO migration/adaptation for every breaking model change.
- [ ] Create an InsForge Storage bucket for attachments.
- [ ] Store attachment metadata in PostgreSQL.
- [ ] Keep OpenRouter/API keys server-side.
- [ ] Deploy the FastAPI/HTMX application through Coolify on the VPS.
- [ ] Configure InsForge and OpenRouter secrets as Coolify environment variables.

## Contributor checklist

- [ ] If you change a pinned stack version, update the corresponding row in the "Stack" table and verify that the lockfile (`uv.lock`, `package-lock.json`) reflects the change.
- [ ] If you add an endpoint that touches InsForge, call the Python SDK or the REST API; do not add MCP tools as runtime dependencies in `pyproject.toml`.
- [ ] If you add a new table, migrate the model first and then add the DAO mapping if there is legacy debt to preserve; document any divergence in [`decisiones-proyecto.md`](decisiones-proyecto.md).
- [ ] If you add a column to `authorized_users`, keep `email` unique and update the admin view before merging.
- [ ] If you add an InsForge bucket, also declare the metadata table and the upload/download hooks that use it.
- [ ] If you introduce an API key or secret, configure it as a Coolify environment variable; never commit `.env*` with real values.
- [ ] If you propose replacing FastAPI, HTMX, Tailwind, or InsForge, open an issue with the "When this changes" section filled in before touching `pyproject.toml`.

## Navigation

Previous: [Codebase Guide](../CODEBASE-GUIDE.md) | Next: [Capas y slices](capas-y-slices.md)