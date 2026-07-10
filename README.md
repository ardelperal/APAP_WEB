# APAP_WEB

Web application for APAP (Asociación para la Atención de Personas con Autismo y otros Trastornos del Desarrollo): intake, foster network, adoptions, and clinical history for sheltered animals, plus the volunteer registry that runs the program. Built on FastAPI + Jinja2 + Tailwind CSS v4 against an InsForge-managed PostgreSQL backend, deployed to Coolify.

> **Status:** pre-MVP, single-branch workflow. All work lands on `main` (see [`AGENTS.md`](AGENTS.md) §15).
> **Python:** 3.11+. **CI:** GitHub Actions (`ci / lint`, `ci / test`, `ci / build`, conditional `ci / e2e` and `ci / deploy`).

---

## What is APAP_WEB

APAP_WEB is the server-rendered web application that replaces APAP's legacy Microsoft Access / VBA tool for animal-shelter operations. The legacy app runs on a single workstation, stores everything in DAO, and has accumulated technical debt that no single rewrite can ignore if it wants to keep the team's day-to-day workflows intact. The web rewrite has three anchors:

1. **Functional superset of the legacy (P1 fidelity premise, [`docs/proceso.md`](docs/proceso.md) §0).** Every legacy capability the team uses today — intake, foster assignment, adoption tracking, health acts, transfers (cesiones), the volunteer registry with role mappings, the catalog fields seeded from Access — is either preserved bit-for-bit or replaced by a documented equivalent in [`docs/decisiones-proyecto.md`](docs/decisiones-proyecto.md). Gaps discovered during the work are tracked as `type:bug` issues with the `gap:legacy` label, never silently ignored.
2. **Allowlisted web access through Google OAuth.** Authentication is delegated to Google (fronted by InsForge's hosted OAuth proxy), authorization is an allowlist (`usuarios_autorizados`) checked against the authoritative store on every request (cached for `APAP_AUTH_CACHE_TTL_SECONDS`, default 300s, so a deactivation takes effect inside that window). There is no anonymous access to anything beyond `/healthz`, `/login`, `/auth/google`, `/auth/callback`, `/logout`, and `/static`.
3. **Server-rendered, minimal-JS, audit-friendly.** Jinja2 templates, Tailwind CSS v4 (CSS-first, no `tailwind.config.js`), one `httpx` client per request to InsForge. Pages are HTML; HTMX-style progressive enhancement is the intended direction but the current surface is mostly full-page reloads. Every state-changing action goes through CSRF middleware and emits a structured `log_safe(...)` event with 12-field PII redaction.

The application's authoritative contract for the rewrite is captured in three docs: [`docs/roadmap.md`](docs/roadmap.md) (feature phases and current status), [`docs/architecture-insforge-stack.md`](docs/architecture-insforge-stack.md) (stack decisions), and [`docs/proceso.md`](docs/proceso.md) (how to take an issue from open to merged-and-closed with evidence). This README points at them rather than duplicating their content.

---

## Features shipped today

The features below are live on `main` (2026-07-05). Each entry references the GitHub issue that delivered it (cross-checked against `app/modules/<area>/` and the closed-issue list).

### Authentication & session

- **Google OAuth 2.0 via InsForge's hosted proxy, with PKCE.** `/login` renders the APAP login page; `/auth/google` mints the PKCE pair and bounces the user to Google; `/auth/callback` exchanges the temporary `insforge_code` (or the legacy `code=...`) for an InsForge JWT and issues a signed session cookie. ([Fase 2 — #16](https://github.com/ardelperal/APAP_WEB/issues/16); callback-loop fix #125, logout fix #124)
- **Per-request authorization revalidation.** The session cookie carries identity only; `require_authorized_user` re-checks `usuarios_autorizados` (cached per `APAP_AUTH_CACHE_TTL_SECONDS`). Deactivating a user in `/admin` takes effect inside the TTL window instead of waiting up to 7 days for the cookie to expire. (#143, hardening follow-ups #144, #145)
- **CSRF middleware on every POST/PUT/PATCH/DELETE.** (`CsrfMiddleware`, registered after the static-files mount, before the auth middleware.) Tokens are issued into the session at login, validated via the `X-CSRFToken` header (HTMX/fetch) or the `csrf_token` form field (traditional POSTs), and surface a `csrf.disabled` warning when the `APAP_CSRF_ENABLED` feature flag rolls the middleware off.
- **Session cookies** are signed (`itsdangerous.URLSafeTimedSerializer`), `HttpOnly`, `Secure`, `SameSite=Strict` (the PKCE cookie used during the OAuth bounce is `SameSite=Lax` so Google can return to `/auth/callback`). Session rotation & deactivation follow [`docs/runbooks/cookie-rotation.md`](docs/runbooks/cookie-rotation.md).

### Domain modules (`app/modules/`)

| Module | What it does | Shipped by |
|---|---|---|
| `animals` | CRUD on `animales` with Access-required fields enforced (`nombre`, `especie`, `fecha_alta`, `chip`, `sexo`, `estado`); list + paginated search; soft-delete preserves FK history; append-only `animal_lifecycle_events` table for the timeline slice shipped with the CRUD. | #28, #31, #67–68, #70–81, #129 |
| `voluntarios` | Volunteer registry. CRUD with validators on core fields; soft-delete (`deactivate_voluntario`) preserves FK history. The active-voluntario check used by other modules lives in the consumer (e.g. `_validate_voluntario_activo` is enforced inside `acogidas` per FOSTER-02). | #34, #82–86 |
| `entradas` | Animal intake. Single + batch API (`/entradas`, `/entradas/batch`); staging + atomic commit CTE for batches; origin/motive routes through `catalogos_origenes` / `catalogos_motivos`; cesión-by-owner workflow with separate contract. | #87–89, #40–42, #65 |
| `foster` | Foster network. `casas_acogida` with capacity and preferred species (FOSTER-01); the `foster_capacity_overrides` audit log (FOSTER-03) when the species gate or capacity advisory is overridden by an operator; `asignar` / `overrides` sub-routers behind the capacity gate + species preference. | #43, #45 (with #44 contributing the FK column) |
| `acogidas` | Stay-of-foster records on top of `casas_acogida` and `voluntarios` (FK-structured `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` per FOSTER-02); `close_acogida` (lifecycle event) vs `delete_acogida` (soft-delete) separation; helpers `compute_duracion` and `is_active`. | #44 |
| `adopciones` | Adoption CRUD with FKs to `animales` + `voluntarios` + `entradas`; conflict detection on the `(animal_id, fecha_adopcion)` natural key; soft-delete preserves history; `tipo_adopcion` enum (regular, preadopcion, …). | #47 |
| `sanidad` | Clinical-history acts (`actuacion_sanitaria`) with the D-24 date validation: ISO format, not future, not earlier than `animales.fecha_alta` (with the documented legacy-NULL exemption). | #50 |
| `cesiones` | Owner transfers (cesión) tied to an `entrada_origen_id`. Used as the entry path for the "owner hands the animal to APAP" workflow. | #41 |

Cross-module:

- **5 reference-data catalogs** (`catalogos_origenes`, `catalogos_motivos`, `catalogos_pruebas`, `catalogos_periodicidad`, `catalogos_tipos_contrato`), seeded from Access and refreshed idempotently with `INSERT ... ON CONFLICT DO NOTHING`. (#65 / CATALOG-01, which subsumes the catalog portion of #42 / INTAKE-04).
- **Admin panel** at `/admin` for the `developer` role: list users, add user by email + role, deactivate. Built on `require_developer_user_redirect` so the role check happens once in the dependency rather than in every handler. (#146)
- **RBAC** across the four roles (`reader`, `key_user`, `writer`, `developer`); `writer` enforced per route via `require_writer_user`. #144 closes the gap where a `reader` could write to every module; #146 cleans the same shape on the admin handler; role literals are consolidated onto `app.core.auth.Rol`.
- **Mobile-aware UI.** `UADetectionMiddleware` classifies each request by User-Agent and renders through `base.html` (desktop) or `base_mobile.html`; nav layout regression sentinel keeps the 1280 px / 375 px viewports usable. (#148, #147)
- **Structured logging with `log_safe`.** All log emission in `app/` goes through `app/core/logging.py::log_safe`, which scrubs a closed 12-field list (`email`, `session_token`, `jwt`, `oauth_code`, `pkce_verifier`, `csrf_token`, `pkce_challenge`, `authorization`, `cookie`, `referer`, `ip_address`, `x_forwarded_for`) before the JSON handler writes to stdout.

### Operations & dev-loop

- **Schema bootstrap on cold start.** The FastAPI `lifespan` runs, in order, `configure_logging` → `ensure_schema_and_seed` (creates `usuarios_autorizados` and seeds `APAP_INITIAL_ADMIN_EMAIL` if set) → `ensure_catalogs` (#65) → `ensure_domain_schema` (animal / voluntario / role / foster / adoption / health tables in dependency order) → `apply_sql_migrations` (versioned DDL from `app/core/migration/sql/`). All five steps are idempotent and fail-fast.
- **Per-user authorization cache.** `app/core/auth_cache.py` wraps the per-request `SELECT usuarios_autorizados` so request handlers don't fan-out the query (default TTL 300s, controlled by `APAP_AUTH_CACHE_TTL_SECONDS`).
- **`scripts/check_rules.py`** enforces project-wide linters as part of the local validation gate: APAP003 ban on `logger.*` chained calls in `app/`, `print(...)` ban, CSRF middleware registration, `SameSite=Strict` enforcement, helper coverage gate via `scripts/pytest_plugin/coverage_gate.py`. Run via `make check-rules`.

---

## Planned (not yet shipped)

The roadmap (Fases 3–7) is fully laid out in [`docs/roadmap.md`](docs/roadmap.md) §3 with issue numbers and dependency state. Highlights of what is currently open against `main`, by area:

- **Volunteers**: VOL-02..05 — `roles_voluntario` junction table with role validation, fuzzy dedup pipeline, name/DNI FK migration, active validation gate (#35–#38).
- **Foster**: FOSTER-04 material assignment to stays; follow-up to move `record_override` inside the `create_acogida` transaction so the audit row and the create commit atomically (#46, #142).
- **Adoptions**: ADOPT-03 4-state follow-up state machine (#49). ADOPT-02 (#48) cancelled for invalid legacy provenance — see `openspec/changes/correct-preadoption-legacy-provenance/`.
- **Health**: HEALTH-02..06 — batch import, summary API (`ActuacionSanitaria` roll-up per test type), therapies CRUD, periodicity engine, prueba-catalog migration (#51–#55).
- **Animal lifecycle**: state resolver mirroring `DameSituacion()`, schema for the append-only `estado_actual_animal` cache, search API, chip-change cascade (#29, #30, #33, #69).
- **Documents & reports**: DOC-01..04 contract-PDF generation, signed-upload registration, polymorphic attachments, legacy-to-object-storage migration; REPORT-01..05 parameterized query builder, server-side execution with PDF/Excel export, quarterly report, notification engine, live dashboard counters (#56–#64).
- **RBAC-01**: full RBAC matrix at the API layer (#66).
- **Foundation UX/UI design system** (#6) and **task engine** (#7) as transversal slices.
- **Documentation translations** to castellano per [`docs/roadmap.md`](docs/roadmap.md) §8 (`docs/architecture-insforge-stack.md`, `docs/development.md`, and the `docs/discovery/*.md` still in English).

For the full picture — every open issue by area, every issue still to be opened, and the cross-references to discovery/legacy/decision docs — see [`docs/roadmap.md`](docs/roadmap.md) §3 (per-phase status), §4 (open issues), §5 (issues yet to be opened), and §6 (doc index).

---

## Tech stack

Pinned per [`docs/architecture-insforge-stack.md`](docs/architecture-insforge-stack.md) and `pyproject.toml`. Runtime deps lift the floor; production runs whatever the latest stable line is.

| Area | Decision | Notes |
|---|---|---|
| Language | Python 3.11+ | `requires-python = ">=3.11"` |
| Web framework | FastAPI (BFF) | Application boundary; owns routing, validation, business rules, authorization |
| ASGI server | Uvicorn (`uvicorn[standard]`) | Dev and production entrypoint |
| Templates | Jinja2 | Server-rendered pages; one `app/templates/<module>/` per domain |
| Data validation / settings | Pydantic 2.13+ + `pydantic-settings` | Single source of truth for env-var parsing in `app/core/config.py` |
| HTTP client | httpx (sync `Client` per request via `InsForgeClient`) | One client per request lifecycle, closed via `get_insforge_client_dep` yield/finally |
| Session signing | itsdangerous `URLSafeTimedSerializer` | One process-cached secret, see [`docs/runbooks/cookie-rotation.md`](docs/runbooks/cookie-rotation.md) |
| Auth | Google OAuth 2.0 via InsForge-hosted proxy, PKCE | `/login` → `/auth/google` → `/auth/callback` → signed cookie |
| Form parsing | python-multipart | Required for form/file parsing in FastAPI |
| Styling | Tailwind CSS v4 (CSS-first, no `tailwind.config.js`) | Compiled once at build (Node 20 stage) into `app/static/css/output.css` |
| Managed backend | InsForge (PostgreSQL + PostgREST + Storage + Functions + Realtime + Auth) | Reached over HTTP from `app/core/insforge.py` |
| Code intelligence | CodeGraph (`@aroman22/codegraph-vba` + MCP `codegraph_explore`) | See [`AGENTS.md`](AGENTS.md) §14 |
| Testing | pytest + pytest-cov | TDD with red → green → refactor discipline per [`docs/proceso.md`](docs/proceso.md) §4; the concurrent volunteer test requires `APAP_E2E_BASE_URL` and is deselected in CI/local |
| Lint | Ruff (`ruff check .`) | Plus the project detectors in `scripts/check_rules.py` |
| Build | `python -m build` (hatchling backend) | Wheel produced for the deploy webhook job |
| Container | Multi-stage Dockerfile (Node 20 for Tailwind, Python 3.11-slim for runtime) | Build-verified by `ci / build` |
| Hosting | Coolify on a project VPS | Auto-deploy via signed webhook on `push: main` |

The InsForge SDK is intentionally not used: there is no `@insforge/sdk` JS bundle in this repo, and there is no Node frontend. The Python `InsForgeClient` in `app/core/insforge.py` talks to the InsForge REST endpoints (`/api/database/advance/rawsql`, `/api/auth/oauth/exchange`, etc.).

---

## Architecture

```text
+------------------ browser -------------------+
| HTML + Tailwind v4 (+ minimal htmx over time) |
+---------------------+------------------------+
                      | session cookie (SameSite=Strict, signed)
                      v
+---------------- FastAPI / Uvicorn -----------------+
|  UADetectionMiddleware  (UA -> is_mobile)          |
|  CsrfMiddleware         (POST/PUT/PATCH/DELETE)    |
|  protect_user_facing_routes (cookie -> /login)     |
|  require_authorized_user (per-request, cached)    |
|  routes (app/main.py + app/modules/<area>/routes.py)|
|  services (app/modules/<area>/service.py)         |
+---------------------+-----------------------------+
                      | httpx.Client (per request, bearer service key)
                      v
+---------------- InsForge (managed) ----------------+
|  PostgreSQL (advance/rawsql)                       |
|  Auth (Google OAuth hosted proxy, /auth/oauth/*)   |
|  Storage (object storage, used in Fase 7)          |
+----------------------------------------------------+
```

The full layered contract is documented in [`docs/architecture-insforge-stack.md`](docs/architecture-insforge-stack.md) (stack choices, InsForge usage rules, MCP tools used for infra), with auth and authorization details in §"Authentication and authorization".

---

## Project structure

The project's actual layout (paths verified by `ls`, not the aspirational tree in `docs/architecture-insforge-stack.md`):

```text
APAP_WEB/
  app/
    main.py                      # FastAPI factory, lifespan, top-level routes
    core/                        # cross-cutting infrastructure (no domain rules)
      config.py                  # Pydantic-settings (env-prefixed APAP_*)
      auth.py                    # InsForge-side auth + usuarios_autorizados
      auth_dependencies.py       # require_authorized_user, _writer, _developer, ...
      auth_cache.py              # TTL cache for per-request authorization (issue #143)
      csrf.py                    # CsrfMiddleware + session-bound tokens
      session.py                 # signed-cookie read/write/clear
      pkce.py                    # PKCE pair mint
      insforge.py                # InsForgeClient + OAuth exchange + execute_sql
      logging.py                 # log_safe + 12-field redaction
      middleware.py              # UADetectionMiddleware + base context processor
      ua.py                      # is_mobile(UA) classification
      catalogs.py                # 5 reference-data catalogs (#65)
      domain.py                  # ensure_domain_schema (the SQL of the app)
      migration/                 # versioned DDL runner + reconcile CLI
    modules/                     # one folder per domain area
      animals/                   # routes.py + service.py (+ forms.py)
      voluntarios/               # routes.py + service.py
      entradas/                  # routes.py + service.py + batch_routes.py + batch_service.py
      foster/                    # routes.py + service.py + assignment_routes.py + assignment.py
      acogidas/                  # routes.py + service.py
      cesiones/                  # routes.py + service.py
      adopciones/                # routes.py + service.py
      sanidad/                   # routes.py + service.py
    templates/                   # Jinja2 templates (base.html, base_mobile.html, login.html,
                                # unauthorized.html, index.html, admin.html,
                                # <module>/{list,form,detail}.html)
    static/css/output.css        # Tailwind v4 compiled output
  tests/                         # pytest suite (TDD per docs/proceso.md §4)
    e2e/                         # Playwright suite (separate CI job)
  scripts/
    check_rules.py               # project-specific detectors
    check_audit_and_runbook.py   # docs/PR aid
    coolify_webhook.py           # HMAC-signed Coolify deploy trigger
    dev_server_no_lifespan.py    # CI/dev start without InsForge bootstrap
    pytest_plugin/               # coverage_gate.py + custom linter fixtures
    ruff_plugin/                 # APAP001 lint plugin
  docs/                          # canonical documentation (see "Documentation index")
  tailwindcss/                   # Node-side Tailwind source + @tailwindcss/cli
  openspec/                      # SDD change workspace (when used)
  .github/workflows/ci.yml       # CI pipeline
  Dockerfile                     # multi-stage build (Node 20 + Python 3.11-slim)
  pyproject.toml                 # project metadata + runtime deps; readme = docs/setup.md
  AGENTS.md                      # agent rules (orchestrator discipline, security baseline,
                                # code-quality rules, merge workflow)
  docs/proceso.md                # operational playbook (pre-flight → issue → TDD → merge → close)
  docs/setup.md                  # local setup walkthrough
  docs/roadmap.md                # live feature roadmap
  docs/architecture-insforge-stack.md
  docs/decisiones-proyecto.md    # formal decision register
```

---

## Quick start

```bash
git clone https://github.com/ardelperal/APAP_WEB.git
cd APAP_WEB

python -m venv .venv
.venv\Scripts\Activate.ps1            # PowerShell
# source .venv/bin/activate           # POSIX shell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

cd tailwindcss
npm install
npx @tailwindcss/cli -i ./styles/app.css -o ../app/static/css/output.css --minify
cd ..

# Copy and edit secrets
Copy-Item opencode.json.example opencode.json     # PowerShell
# cp opencode.json.example opencode.json          # POSIX

# Start the dev server (uvicorn with --reload on 127.0.0.1:8000)
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open <http://127.0.0.1:8000/healthz> for the JSON health probe, or `/login` once you've set `APAP_GOOGLE_CLIENT_ID` / `APAP_GOOGLE_CLIENT_SECRET`. The full walkthrough — including the InsForge MCP setup, secrets management, and the `make run` shortcut — lives in [`docs/setup.md`](docs/setup.md).

---

## Configuration

All runtime configuration is read from environment variables (or `.env`) with the `APAP_` prefix. Defaults exist for local development so the app boots without secrets, but **production must override every value listed below except `APAP_LOG_LEVEL` and `APAP_AUTH_CACHE_TTL_SECONDS`**. The single source of truth is `app/core/config.py` (`Settings`) — if this table and the code disagree, the code wins (per the P3 doc-reflects-code premise in [`docs/proceso.md`](docs/proceso.md) §0).

| Variable | Purpose | Required in prod |
|---|---|---|
| `APAP_INSFORGE_URL` | InsForge base URL (PostgREST-compatible). | yes |
| `APAP_INSFORGE_SERVICE_KEY` | Privileged service key for admin SQL (schema bootstrap, catalog seed, user mgmt). Never expose to the browser. | yes |
| `APAP_INSFORGE_ANON_KEY` | Anonymous JWT for client-side use; not used by the server today. | optional |
| `APAP_GOOGLE_CLIENT_ID` | Google OAuth client id. | yes |
| `APAP_GOOGLE_CLIENT_SECRET` | Google OAuth client secret. | yes |
| `APAP_GOOGLE_REDIRECT_URI` | OAuth callback registered with Google; must match exactly (e.g. `https://apap.romancaba.com/auth/callback` in prod). | yes |
| `APAP_INITIAL_ADMIN_EMAIL` | Email pre-seeded as the first `developer` in `usuarios_autorizados` on first boot. Empty = no seed. | recommended on first deploy |
| `APAP_SESSION_SECRET` | HMAC secret used by `itsdangerous` to sign session cookies. **Rotate to force a system-wide logout** — see [`docs/runbooks/cookie-rotation.md`](docs/runbooks/cookie-rotation.md). | yes |
| `APAP_AUTH_CACHE_TTL_SECONDS` | Per-request authorization cache TTL in seconds. Default `300`. Lower for stricter revocation latency at the cost of an extra SELECT per request. `0` disables the cache. | optional |
| `APAP_CSRF_ENABLED` | Feature flag for `CsrfMiddleware`. Default `true`. Set to `false` only for emergency rollback during an incident — emits a `csrf.disabled` log event per request. | keep `true` |
| `APAP_LOG_LEVEL` | Root level for the JSON stdout handler. Default `INFO`. Unknown values fall back to `INFO` at runtime. | optional |
| `APAP_DEBUG` | Toggle debug-only behavior. Default `false`. | optional |

For the operator procedure to rotate `APAP_SESSION_SECRET` (when to rotate, pre-deploy checklist, Coolify steps, verification, rollback), see [`docs/runbooks/cookie-rotation.md`](docs/runbooks/cookie-rotation.md).

---

## Development workflow

The end-to-end playbook lives in [`docs/proceso.md`](docs/proceso.md). Highlights that the README needs to surface:

- **TDD by default.** Red → green → refactor. Tests come first for every `type:bug`, `type:feature`, and `type:refactor`; docs and pure-ops changes are exempt. ([`docs/proceso.md`](docs/proceso.md) §4)
- **Use CodeGraph before reading source.** `codegraph_explore` (MCP) and `codegraph explore` (CLI) are Read-equivalent; reach for `Read`/`Grep`/`Glob` only to confirm a detail codegraph didn't cover. ([`AGENTS.md`](AGENTS.md) §14)
- **Local validation gate** before commit + push (run from the repo root):

  ```bash
  # Pytest, with deprecations as errors (per pyproject.toml addopts).
  # deselects the PG-requiring concurrent test; CI runs with the same flags.
  python -m pytest -W error::DeprecationWarning \
      --ignore=tests/e2e \
      --deselect tests/test_voluntarios_concurrent.py

  ruff check .
  python -m build
  python scripts/check_rules.py
  ```

- **CodeGraph sessions** start with `codegraph status .` and confirm `[OK] Index is up to date` + a live daemon; run `codegraph sync .` once after creating a brand-new top-level directory (do not re-`init`).
- **Commit & PR conventions.** Conventional Commits in English; PR with `Closes #N` or `Refs #N`; PR under the 400-line review budget by default (use the `chained-pr` skill to slice larger work); review lenses (`code-review-expert`, mandatory `judgment-day` for high-stakes diffs) per [`AGENTS.md`](AGENTS.md) §17.
- **Single-branch pre-MVP.** All work targets `main`; non-`main` branches are deleted after merge. Post-MVP reverts to the staging + UAT channel — see [`AGENTS.md`](AGENTS.md) §15.4 for the procedure.
- **Helper coverage gate.** Anything matching `_row_to_*` or in `CRITICAL_HELPERS` must hold 100% line coverage; `scripts/pytest_plugin/coverage_gate.py` fails the build otherwise. ([`AGENTS.md`](AGENTS.md) §11)
- **Logging discipline.** All log emission in `app/` goes through `log_safe(event, **fields)`; direct `logger.*` and `print(...)` in `app/` are banned by `scripts/check_rules.py`. ([`AGENTS.md`](AGENTS.md) §9)
- **CSRF discipline.** Every form template renders `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">` in every `<form method="post">`; CSRF middleware is the gate. ([`AGENTS.md`](AGENTS.md) §10)

---

## CI/CD

The pipeline is `.github/workflows/ci.yml` with five jobs:

| Job | Trigger | What it does |
|---|---|---|
| `lint` | PR + push to `main`/`staging`, manual | `ruff check .`; secret-leak grep over `.github/` |
| `test` | PR + push, after `lint` | `pytest -W error::DeprecationWarning --ignore=tests/e2e --deselect tests/test_voluntarios_concurrent.py` |
| `build` | after `test` | `python -m build` (hatchling wheel) |
| `e2e` | after `build`, only when `APAP_OAUTH_CLIENT_ID != ''` | boots the dev server with the lifespan off and runs Playwright |
| `deploy` | `push: main` only, after lint/test/build, **skipped on merge commits** | signs and POSTs the Coolify webhook (HMAC SHA-256 with `COOLIFY_WEBHOOK_SECRET`) |

The `e2e` and `deploy` jobs are conditional: `e2e` skips when the e2e/ tree is absent or OAuth env vars are missing; `deploy` skips on merge commits (a push triggered by merging a PR is not a real "deploy this change" event) and skips when `COOLIFY_WEBHOOK_URL` is unset.

The `deploy` job delegates the HMAC signing to `scripts/coolify_webhook.py`, which the test suite covers end-to-end; production and CI share the same code path.

For the full pipeline contract, see the comment block at the top of [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## Deployment

Two paths, both targeting the same Coolify application (`apap-web`, fqdn `apap.romancaba.com`):

1. **Automatic on push to `main`.** The `ci / deploy` job calls `scripts/coolify_webhook.py`, which signs the payload with HMAC-SHA-256 against `COOLIFY_WEBHOOK_SECRET` and POSTs `COOLIFY_WEBHOOK_URL`. Coolify pulls `ardelperal/APAP_WEB:main`, runs the multi-stage Dockerfile (Node 20 to compile Tailwind, Python 3.11-slim as runtime), and ships the container.
2. **Manual.** Operators can deploy by triggering the Coolify `apap-web` application directly from the Coolify UI; useful during incidents or when the webhook secret is being rotated.

The Docker image builds Tailwind inside the Node stage so `app/static/css/output.css` is always in sync with `tailwindcss/styles/app.css` at the moment of release. Secrets (`APAP_*`, `COOLIFY_*`) live in Coolify's environment-variable store and never in the repository.

For the full deployment target diagram and InsForge / Coolify integration, see [`docs/architecture-insforge-stack.md`](docs/architecture-insforge-stack.md).

---

## Security posture

APAP_WEB follows a defense-in-depth model anchored in [`AGENTS.md`](AGENTS.md) rules 1–17 plus the cross-project web-security-quality-baseline.

- **Authorization re-validated per request.** The signed session cookie carries identity only; the `require_authorized_user` dependency re-checks `usuarios_autorizados` (cached for `APAP_AUTH_CACHE_TTL_SECONDS`), so deactivating a user takes effect inside the TTL window instead of waiting up to 7 days for the cookie to expire. ([AGENTS.md](AGENTS.md) §1; web-security-baseline rule 1)
- **Every declared role is enforced at the route layer.** `reader` cannot write (per-route `require_writer_user`), `developer` is the only role allowed on `/admin` (`require_developer_user_redirect`), and consolidation onto `app.core.auth.Rol` keeps role literals out of handler code. (web-security-baseline rules 2, 7)
- **CSRF defense-in-depth.** `CsrfMiddleware` validates a session-bound CSRF token on every POST/PUT/PATCH/DELETE (via `X-CSRFToken` header or the `csrf_token` form field). Every form template renders `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">`. AGENTS §10 documents the exact contract.
- **Session cookies** are `HttpOnly`, `Secure`, `SameSite=Strict` and signed with `itsdangerous`. The PKCE cookie used during the OAuth bounce is `SameSite=Lax` so Google's top-level redirect can read it.
- **Logging redaction.** Every log call goes through `app.core.logging.log_safe`, which scrubs a closed 12-field list (email, session_token, jwt, oauth_code, pkce_verifier, csrf_token, pkce_challenge, authorization, cookie, referer, ip_address, x_forwarded_for) before the JSON handler writes to stdout. AGENTS §9 + `scripts/check_rules.py` ban direct `logger.*` and `print(...)` in `app/`.
- **Insecure defaults fail fast in production.** `Settings` uses a non-empty placeholder for `session_secret` so dev works out of the box; production deploys override the value via Coolify env vars. `tests/test_config.py` pins the contract.
- **HTTP client lifecycle.** `InsForgeClient` is constructed per request and closed via the `yield`/`finally` shape of `get_insforge_client_dep`, so a single shared `httpx.Client` lifecycle is owned by the request scope.
- **Rate limiting** on the login, OAuth callback, and admin endpoints is part of the rollout plan (in the security baseline as rule 5) and lands with the staging hardening slice.
- **Security headers** (`CSP`, `X-Frame-Options`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, and `HSTS` behind TLS) ship with the security-headers middleware slice; today's stack is still iterating on them (see [`docs/audits/`](docs/audits/) for past audits).
- **Secrets in env vars only.** Never committed. `opencode.json` carries the InsForge admin key and is `.gitignore`d; `scripts/check_rules.py` and `tests/test_ci_workflow.py` enforce the boundary.
- **Audit coverage.** Each sensitive slice — auth deactivation, OAuth callback cookies, XSS allowlist, RBAC enforcement, mobile nav overflow, health CRUD — has its own audit doc in `docs/audits/` (e.g. `auth-revalidation-2026-Q3.md`, `rbac-enforcement-2026-Q3.md`, `xss-audit-2026-Q2.md`). New sensitive changes MUST add or update an audit per [`AGENTS.md`](AGENTS.md) §12.

For the cross-project web security & quality baseline that drives these rules, see the `web-security-quality-baseline` block in [`AGENTS.md`](AGENTS.md) (rules 1–10).

---

## Documentation index

- **Project docs** (under `docs/`)
  - [`docs/roadmap.md`](docs/roadmap.md) — live feature roadmap (Fases 0–7 + transversales)
  - [`docs/architecture-insforge-stack.md`](docs/architecture-insforge-stack.md) — stack, InsForge usage rules, deployment target
  - [`docs/proceso.md`](docs/proceso.md) — operational playbook by issue (pre-flight → close-with-evidence)
  - [`docs/setup.md`](docs/setup.md) — local setup walkthrough (developer)
  - [`docs/decisiones-proyecto.md`](docs/decisiones-proyecto.md) — formal decision register (D-01–D-41)
  - [`docs/development.md`](docs/development.md) — local development commands (legacy doc, pending translation to castellano)
  - [`docs/design-tokens-apap-actual.md`](docs/design-tokens-apap-actual.md) — inherited design tokens from the legacy
  - [`docs/hardening-2026-q2-rule-history.md`](docs/hardening-2026-q2-rule-history.md) — resolved conflict tracker from the Q2 hardening chain
- **Discovery** (domain analysis in [`docs/discovery/`](docs/discovery/))
  - [`README.md`](docs/discovery/README.md) — master index
  - [`business-feature-map.md`](docs/discovery/business-feature-map.md), [`feature-01..04-*.md`](docs/discovery/), [`data-model-notes.md`](docs/discovery/data-model-notes.md), [`state-machines.md`](docs/discovery/state-machines.md), and the rest per [`docs/roadmap.md`](docs/roadmap.md) §6.
- **Legacy analysis** (do not clone; consult for parity reasoning only) — [`docs/legacy-health-ui-workflow.md`](docs/legacy-health-ui-workflow.md), [`docs/legacy-initial-dashboard.md`](docs/legacy-initial-dashboard.md), [`docs/legacy-signed-contract-flow.md`](docs/legacy-signed-contract-flow.md), [`docs/legacy-volunteer-roles.md`](docs/legacy-volunteer-roles.md), [`docs/legacy-lifecycle-transition-rules.md`](docs/legacy-lifecycle-transition-rules.md).
- **Audits** in [`docs/audits/`](docs/audits/) — per-sensitivity-slice audit reports (`xss-audit-2026-Q2.md`, `auth-revalidation-2026-Q3.md`, `rbac-enforcement-2026-Q3.md`, `health-data-crud-audit-2026-Q3.md`, `auth-dependencies-audit-2026-Q2.md`, `oauth-callback-cookie-audit-2026-Q2.md`, plus the mobile-menu screenshots).
- **Runbooks** in [`docs/runbooks/`](docs/runbooks/) — operator playbooks (cookie rotation, etc.).
- **Project root rules**
  - [`AGENTS.md`](AGENTS.md) — agent instruction file (project rules 1–17: code quality, security baseline, merge workflow, orchestrator discipline).
- **SDD** in [`openspec/changes/`](openspec/changes/) — historical and active SDD changes (config in `openspec/config.yaml`).

---

## Roadmap and contributing

The roadmap, including Fases 0 (CI/CD), 1 (skeleton), 2 (auth), the in-flight Fases 5/6 (intake, foster, adopciones, sanidad), and the upcoming Fases 5c / 6 / 7 (DOC, REPORT, RBAC, dashboards, task engine), is in [`docs/roadmap.md`](docs/roadmap.md) §3–§5.

Contributions flow through the operational playbook in [`docs/proceso.md`](docs/proceso.md):

1. Pick a GitHub issue from [`docs/roadmap.md`](docs/roadmap.md) §4 (open) or §5 (to-be-opened), or open a new one with the right `type:*` label.
2. Read the relevant [`docs/discovery/`](docs/discovery/) doc + [`docs/decisiones-proyecto.md`](docs/decisiones-proyecto.md) (P1 fidelity premise is non-negotiable — see [`docs/proceso.md`](docs/proceso.md) §0).
3. Branch from `main` with a conventional scope (`feat/<area>`, `fix/<area>`, `refactor/<area>`, `docs/<area>`, `test/<area>`, `chore/<area>`, `ci/<area>`); keep the diff under the 400-line review budget — split with `chained-pr` if not.
4. TDD strictly: red test → minimal green impl → refactor with green tests (TDD exempt for `type:docs` and pure ops).
5. Run the local validation gate (§"Development workflow" above). When green, push and open the PR with `Closes #N` in the body.
6. After CI is green and the user has reviewed, merge to `main`. Close the issue with a comment that names both the implementation commit SHA(s) and the test module path that proves compliance (the cross-project `github-issue-closure-traceability` rule).
7. Update the roadmap in the same session (per [`docs/roadmap.md`](docs/roadmap.md) §9): remove from §4, refresh §3 if the phase state changed.

Review lenses (anchored to the skill registry):

- `code-review-expert` runs on every slice.
- `judgment-day` runs IN ADDITION on high-stakes diffs (auth, sessions, CSRF, PII, security gates, migration / raw SQL writes, seed scripts). See [`AGENTS.md`](AGENTS.md) §17.2.

The orchestrator (the agent reading `AGENTS.md` directly) coordinates and delegates; sub-agents do the writes. AGENTS.md §17 documents the boundary.

---

## License

Proprietary. © APAP.
