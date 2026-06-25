# APAP Application Architecture Stack

This document is the baseline architecture for the future APAP application. It exists so a future AI or developer can start implementation without rediscovering the stack decisions already made.

## Architecture decision

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

## Branch and deployment policy

`main` remains the production branch for APAP_WEB. GitHub uses `main` as the default branch, and the Coolify `apap-web` application is configured to deploy from `ardelperal/APAP_WEB:main`.

Normal implementation work targets `staging`. CI runs on PRs/pushes to both `staging` and `main`; the production deploy trigger remains guarded on pushes to `main`. The full UAT-gated staging channel is still future CD-03 scope.

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

1. **Authentication** (who are you): Google OAuth via InsForge
2. **Authorization** (are you allowed): allowlist-based check in FastAPI

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

1. Extract user email from InsForge JWT token
2. Query `authorized_users` table
3. If email found → allow request, attach role to request state
4. If email not found → redirect to `/unauthorized`

### Admin panel (developer only)

A protected section of the app where the developer can:

- List all authorized users
- Add a new user (email + role)
- Remove a user
- View audit log of who added whom

Only accessible when `role = developer`. Key users see no trace of this panel.

### Implementation notes

- Do not store passwords; rely entirely on Google OAuth via InsForge
- The `authorized_users` table is the single source of truth for access control
- InsForge handles session tokens, refresh, and OAuth flow
- FastAPI only checks the email against the allowlist after OAuth succeeds
- The `/unauthorized` page should be helpful: explain that access requires authorization and provide contact info for the developer

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
- `npm install -D tailwindcss @tailwindcss/cli` in `tailwindcss/` folder
- `npx @tailwindcss/cli -i ./styles/app.css -o ../app/static/css/output.css --watch`
- FastAPI serves `app/static/` as mounted static files

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

## When to choose another stack

Do not switch stacks lightly. Prefer the baseline unless one of these becomes true:

- the UI requires heavy client-side state or complex real-time interactions;
- offline-first behavior becomes required;
- the app becomes public-facing and SEO becomes important;
- the team strongly standardizes on another backend framework;
- InsForge constraints prevent a critical domain requirement.

If one of those happens, document the tradeoff before changing the stack.

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

## Non-goals

- Do not build a React/Next.js SPA by default.
- Do not store attachment binaries in PostgreSQL by default.
- Do not expose privileged InsForge keys to the browser.
- Do not inherit legacy data-model debt only for convenience.
- Do not use InsForge MCP tools as application runtime code.
