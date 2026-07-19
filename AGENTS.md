---
description: Agent instructions and code-quality rules for APAP_WEB (FastAPI + HTMX + InsForge backend)
globs: *
alwaysApply: true
---

# APAP_WEB — Agent Instructions

Este archivo define **solo reglas locales del repo de código**. Para config de
herramientas (dysflow MCP, codegraph-vba, etc.) ver `~/.config/opencode/AGENTS.md`.

---

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

### 14. CodeGraph index — persistent, auto-synced, never re-initialized

This project uses **CodeGraph** (`@aroman22/codegraph-vba` CLI + MCP `codegraph_explore`) as a persistent code-intelligence index over the Python/YAML tree. The index lives in `.codegraph/` at the repo root.

**Established invariants** (do not violate):

1. **Already initialized.** `.codegraph/` exists, is tracked in git (the root `.gitignore` does NOT list it; the internal `.codegraph/.gitignore` keeps the SQLite DB local-only — only the `.gitignore` itself is committed). Do NOT run `codegraph init` again. Running it would wipe a healthy index. If the directory is missing after a fresh clone, ONE human must run `codegraph init .` once — never the agent.

2. **Auto-sync daemon is already running.** CodeGraph v1.4+ keeps a background `node` daemon that watches the filesystem and updates the index with ~1s lag. Do not poll, do not re-index manually. Trust the freshness flag returned by `codegraph status .` (`Index is up to date` = good; anything else = sync once and re-check).

3. **Read/Grep/Glob are a last resort.** Before opening any file under `app/`, `tests/`, `scripts/`, `pyproject.toml`, or any other source-controlled Python/YAML path, call `codegraph_explore` (MCP) or `codegraph explore` (shell) with the relevant symbol/file names. ONE call usually returns verbatim source grouped by file with the call path between them — that's already Read-equivalent. Only fall back to `Read`/`Grep` to confirm a detail codegraph didn't cover, or to inspect non-indexed files (configs outside the source tree, generated docs, third-party data).

4. **Never gitignore `.codegraph/` at the root level.** The repo-level `.gitignore` MUST NOT list `.codegraph/` or `codegraph.db`. Doing so breaks the "persists across branches" invariant — the next clone on another machine would lose the daemon's working state and the `.codegraph/.gitignore` itself. If you need to silence a transient untracked file (e.g. a `.codegraph-vba/` cache), add a narrow rule scoped to that path only.

5. **Branch checkouts.** When switching branches (`git checkout`, `git pull`, rebase, merge), the index may go stale if the diff touched indexed files. Run `codegraph sync .` ONCE after the operation completes and confirm `Index is up to date`. Do not rebuild from scratch (`codegraph index .`) unless `sync` reports irrecoverable drift — a full rebuild is several seconds for nothing.

6. **Daemon liveness — verify, don't assume.** If a tool response says the daemon is "down" or stale, confirm against the OS with `Get-Process -Id <pid>` (PowerShell) or `ps -p <pid>` (POSIX). The CLI's `codegraph daemons` output is current-state at the moment of the call, not cached. To restart a dead daemon, use `codegraph init .` ONLY as a last resort after `codegraph daemons` reports no live daemon AND a fresh `codegraph sync .` fails to spawn one.

7. **Trust the staleness banner.** When `codegraph_explore` returns a banner like `⚠️ Some files referenced below were edited since the last index sync…`, those specific files need re-indexing — call `codegraph sync .` once. Files NOT in the banner are fresh; do not re-read them. A second, rarer banner `⚠️ CodeGraph auto-sync is DISABLED…` means live watching stopped entirely — diagnose with `codegraph daemons` and re-sync before trusting anything.

Enforcement: PR review. If a change to `.gitignore` would silently re-ignore `.codegraph/`, the reviewer MUST block the PR. If `AGENTS.md` rule 14 itself drifts from reality (e.g. someone deletes `.codegraph/`), the next session's first action must be `codegraph status .` to detect the drift before trusting any `codegraph_explore` result.

8. **Session-start check + codebase growth.** At the START of every session, run `codegraph status .` once and confirm `[OK] Index is up to date` AND `codegraph daemons` reports a live daemon. If the daemon is missing, follow rule 6 before trusting any `codegraph_explore` result. The file-watcher daemon auto-syncs new/modified files inside already-watched directories with ~1s lag — this is what covers normal "the codebase grew" growth. The one case the watcher does NOT cover by itself is a brand-new top-level directory that didn't exist when the daemon started (e.g. a new `app/core/foo/` package, a fresh `tests/integration/` tree). When you create a top-level directory, run `codegraph sync .` ONCE immediately after — it teaches the watcher about the new root. Do NOT re-run `codegraph init` (that wipes the index). Do NOT re-run `codegraph index` (full rebuild) unless `sync` reports irrecoverable drift.

### 15. Merge workflow — pre-MVP single-branch policy + post-MVP revert path

This project is **pre-MVP**. The default rule is: **all work lands on `main`, every non-`main` branch is deleted immediately after its merge, and at the end of each merge cycle the only branch left standing is `main`.** There is no long-lived `staging` branch in pre-MVP. When the user declares MVP reached, the workflow reverts to the standard `staging` + UAT gate described in §"Post-MVP revert" below.

#### 15.1 Pre-MVP gate — all must be true before merging to `main`

1. **Local `pytest` is green.** `python -m pytest -W error::DeprecationWarning` with the same `addopts` from `pyproject.toml` ([tool.pytest.ini_options] block) passes locally. If `tests/test_voluntarios_concurrent.py` is part of the run, the environment must expose `APAP_E2E_BASE_URL` (per `ci.yml` and the REG-S-3 hardening) — in CI the file is `--deselect`-ed because GitHub does not provision Postgres.
2. **`ci.yml` is green on the head of the branch being merged.** Lint (`ruff check .` + the AGENTS.md rule linter `python scripts/check_rules.py .`, rule 20), `test` (pytest with `DeprecationWarning` as error), and `build` (`python -m build`) MUST pass. `e2e` and `deploy` are optional per `.github/workflows/ci.yml`: `e2e` is skipped when `APAP_OAUTH_CLIENT_ID` is not set; `deploy` is skipped when `COOLIFY_WEBHOOK_URL` is not set. Their absence is not a merge blocker in pre-MVP.
3. **Diff is reviewable.** A single PR diff should stay under the `review_budget_lines: 400` (orchestrator default). If a feature is larger, split into chained PRs using the `chained-pr` skill — never blow up main with a single oversized merge.
4. **No `--force`, no history rewrite.** Merge with `--no-ff` to keep the feature commit visible; never `git push --force` to `main`; never rebase already-shipped commits.

#### 15.2 Pre-MVP branch lifecycle

- Work happens on short-lived feature branches off `main`. Names follow conventional commits' scope: `feat/<scope>`, `fix/<scope>`, `refactor/<scope>`, `docs/<scope>`, `ci/<scope>`, `test/<scope>`.
- After the PR merges to `main` AND CI is green: `git branch -d <branch>` locally, then `git push origin --delete <branch>` (only if the remote allows it and no one else uses it).
- **Never** delete `main`. **Never** create or persist a `staging` branch in pre-MVP — that contradicts the single-branch policy. If `staging` already exists from before this rule was in force, migrate its commits into `main` first, then `git branch -D staging && git push origin --delete staging`.
- After every merge cycle, the only branch left standing is `main`. Anything else is a leak.

#### 15.3 Staging-only pre-push hook — status on this repo

On 2026-07-03 the user unset `git config gentleai.stagingOnly` on this repo specifically. The global pre-push hook at `~/.config/opencode/git-hooks/pre-push` still exists but is a **no-op for THIS repo** (it only acts when the per-repo flag is set to `true`). Other repos in `~/.config/opencode/git-hooks/` opt-ins are untouched — the global guardrail continues to protect them. **Do NOT re-enable the flag in pre-MVP** — that would silently re-arm the hook and contradict the pre-MVP gate.

#### 15.4 Post-MVP revert — procedure when MVP is declared

When the user signals MVP reached ("ya tenemos MVC", "MVP reached", "pasamos a producción", "vamos a staging", or equivalent), run this procedure IN ORDER:

1. **Re-enable the staging-only hook on this repo.** `git config gentleai.stagingOnly true` — the global hook starts acting again on pushes to `main`.
2. **Recreate `staging` if missing.** `git checkout -b staging main && git push origin staging`. From this point on, **all** subsequent work targets `staging`, not `main`.
3. **Defer to the global staging-acceptance-contract.** The workflow becomes the standard one: code lands on `staging` → UAT run by **Virginia** (validator) using the `feature-acceptance-uat` skill (`docs/uat/uat-staging-<YYYY-MM-DD>.html`) → user reviews Virginia's sign-off → user explicitly instructs "merge to main" → agent merges. `main` is read-only until that explicit instruction lands.
4. **Mark this rule 15 as DORMANT (post-MVP).** Edit AGENTS.md to replace §15.1–§15.3 with a one-paragraph pointer to the global `staging-acceptance-contract` rule and Virginia's name as validator. Keep §15.4 as a historical record of the pre-MVP lifecycle, but mark it "ARCHIVED".
5. **The agent must NOT preemptively flip phases.** MVP declaration is a USER-driven event. Wait for explicit instruction; do not infer from phrases like "ya está" or "vamos cerrando" without the MVP/MVC keyword.

#### 15.5 What's still NOT automatic in pre-MVP (explicit consent required)

- Direct commits to `main` without a PR — still requires user OK. Always land via PR from a feature branch.
- `--force` to any branch — full stop, regardless of CI.
- Tagging releases / cutting `vX.Y.Z` — user OK.
- Renaming the default branch, changing branch protection on GitHub — user OK.
- Anything that touches `git-hooks/`, the user's global `core.hooksPath`, or any other project's `gentleai.stagingOnly` flag — user OK.

Enforcement: each PR merge landed under this rule MUST mention the `ci.yml` run URL that proved the gate green, in the merge commit body or the PR description. After MVP, this rule is dormant and the global `staging-acceptance-contract` is authoritative. If the gate ever drifts (e.g. someone adds an additional required CI job, or branch protection on `main` requires an extra check), this rule 15 is the source of truth to update in pre-MVP.

### 16. Issue work follows `docs/proceso.md` (project-level operational playbook)

The end-to-end playbook for taking a GitHub issue from "open" to "merged and closed with evidence" lives at **`docs/proceso.md`**. It encodes four non-negotiable premises (P1 fidelity to the Access/VBA legacy as a functional superset, P2 resolution of domain doubts in a fixed order with Dysflow at the bottom, P3 docs reflect code, P4 pre-MVP single-branch) plus a concrete workflow (pre-flight → triage → SDD-or-direct → TDD → local validation → merge → close-with-trazability → roadmap sync in the same stride).

**Rules for the agent**:

1. **Read `docs/proceso.md` at the start of every session that touches work beyond trivial docs.** The playbook covers: how to classify an issue, when to launch SDD, how to follow strict TDD, how to validate locally, how to push and close an issue with the traceability the global `github-issue-closure-traceability` rule requires, and how to keep `docs/roadmap.md` in sync. If a question is answered there, do not reinvent it.
2. **The P1 fidelity premise is non-negotiable.** Before adding or changing a field/feature that mirrors the legacy, confirm the new code preserves the legacy's intent (workflow, validation, calculation, state transition, permission). If a gap is discovered, open a `type:bug` issue with label `gap:legacy` — do not silently ignore it. The trace chain per legacy capability is: legacy capability → its representation in the new model → its test coverage.
3. **When in doubt about the domain**, follow the P2 ladder: discovery doc → decisiones-proyecto → legacy-* → Dysflow MCP on the Access binary. Only `vba-access` and `access-vba-tdd` skills are allowed for Access work in APAP_WEB; the rest of the Access skill set is excluded.
4. **The playbook documents process, not new rules.** If `docs/proceso.md` and this AGENTS.md rule 16 ever disagree, AGENTS.md wins for anything in the "rules" column (logging, CSRF, CRITICAL_HELPERS, audit, runbook, codegraph, merge workflow). The playbook is authoritative for the order of operations, the SDD/TDD discipline, and the closeout traceability template.
5. **Refresh rule.** Whenever the global workflow policy changes (new skill available, new GitHub rule, new pre-MVP operational reality), update `docs/proceso.md` in the same PR or commit. The playbook must not lag behind AGENTS.md §15.

Enforcement: PR-level. If a merged PR retroactively violates P1 (drops or breaks a legacy capability without an explicit `decisiones-proyecto.md` entry), open a follow-up `bug` issue immediately. PR review should verify the closeout comment cites both a commit SHA and a test path before approval.

### 17. Orchestrator discipline — coordinate, delegate, and review before merge

The agent that owns this file in the "orchestrator" role is **not** a writer of code or operational docs. Its job is to (1) talk to the user, (2) gather context, (3) delegate every non-trivial write to a subagent, and (4) run the review lenses before any slice lands on `main`. Subagents do the actual work; the orchestrator owns the contract that the work meets the project's quality bar. This rule exists because every time the orchestrator wrote inline, it duplicated logic a subagent should own, skipped a review lens, or silently edited an operational doc that should have gone through the feature-branch + PR flow in §15.5.

#### 17.1 The orchestrator coordinates, subagents write

The orchestrator MUST NOT do any of the following inline:

- Write code under `app/`, `tests/`, or `scripts/` (routes, services, schemas, helpers, tests, fixtures).
- Author SQL or migration scripts under `app/core/migration/`.
- Edit templates under `templates/` or static assets under `static/`.
- Edit operational docs that govern agent or operator behavior: `AGENTS.md`, `docs/proceso.md`, `docs/roadmap.md`, `docs/audits/*`, `docs/runbooks/*`, `docs/uat/*`.
- Author GitHub issues or PR descriptions for work the orchestrator did NOT execute (a subagent did).

The orchestrator's allowed inline actions are limited to: short clarifying questions, short code snippets to illustrate intent in a delegation prompt, and small corrections that do not justify spawning a subagent (a typo fix in a doc string, a one-line config tweak already covered by an existing rule). When in doubt: spawn a subagent.

WRONG — orchestrator writes a helper inline

```python
# orchestrator scratch session, "just a quick patch"
def _row_to_voluntario(row):
    return Voluntario(id=row["id"], nombre=row["nombre"])
```

RIGHT — orchestrator delegates

```
task(subagent="sdd-apply", branch="feat/issue-130-voluntario-row-helper",
     instructions="…implement _row_to_voluntario per TDD, follow §1, §11…")
```

Every delegation prompt to a subagent MUST include:

1. The relevant AGENTS.md rule numbers the subagent must follow (e.g. §1, §11, §14).
2. An explicit instruction to use `codegraph-vba` (MCP `codegraph_explore` + CLI `codegraph`) FIRST before any `Read`/`Grep`/`Glob`, per §14.
3. A concrete "Definition of Done": what files must exist, what tests must pass, what evidence the subagent must return (commit SHA, branch name, PR URL when applicable).
4. The applicable review lenses from §17.2 — the subagent must self-review with `code-review-expert` before reporting "done"; `judgment-day` runs only when the orchestrator launches it.

#### 17.2 Review lenses — anchored to the skill registry

Before any subagent-driven slice lands on `main`, the orchestrator launches the applicable review lens(es) from the skill registry. The skill registry at `.atl/skill-registry.md` is the **ground truth** for which lenses exist. Do NOT invent lens names that are not in the registry. If a future lens is needed, install it via the registry first, then update this section in a follow-up PR.

**Mandatory every slice:** `code-review-expert` — a single senior lens that covers SOLID, security, and maintainability. The orchestrator launches this lens on the diff the subagent produced (the branch vs `main`) and reads the findings before approving the merge.

**Mandatory when the diff is high-stakes:** `judgment-day` — adversarial dual review with `jd-judge-a` and `jd-judge-b`. The orchestrator launches this lens IN ADDITION to `code-review-expert` when the diff touches any of the following:

- Authentication, authorization, permission checks, role/role-flag logic.
- Secrets handling, cookie flags, CSRF, session lifecycle, PKCE/OAuth, JWT.
- PII handling, data exposure, audit-log emission, log redaction.
- Security gates (gatekeepers, capacity advisories, override mechanisms, bypass flags, manual admin switches).
- Migration scripts, raw SQL writes, fixtures that touch real-shaped data.

A non-exhaustive map of files that automatically trigger `judgment-day` (when modified, not merely read): `app/core/auth*`, `app/core/csrf*`, `app/core/session*`, `app/core/logging*`, `app/core/migration/`, `app/core/insforge.py` when used for writes, any `scripts/seed*` or `scripts/backfill*`, `scripts/check_rules.py`, `scripts/pytest_plugin/coverage_gate.py`. The orchestrator MUST run `judgment-day` if the diff hits any of these paths even if the change looks cosmetic.

WRONG — orchestrator merges a CSRF fix without `judgment-day`

```
# subagent: "added X-CSRFToken header check, all tests green"
# orchestrator: "looks small, merging"
```

RIGHT — orchestrator launches both lenses

```
review-code-expert --diff main...feat/issue-122-csrf-header-check
judgment-day --diff main...feat/issue-122-csrf-header-check \
  --triggers app/core/csrf.py
```

The orchestrator reads both reports, decides which findings are blocking vs informational, and returns a verdict to the user with the commit SHA + PR URL + summarized findings. Findings marked BLOCKER must be addressed before the merge; CRITICAL findings must be addressed or explicitly waived by the user; WARNING and SUGGESTION are tracked but do not block.

#### 17.3 Changes to AGENTS.md and other operational docs go through the feature-branch + PR flow

Operational docs are part of the project's contract — they govern how every agent (orchestrator, subagent, future session) behaves. Editing them inline is the same kind of bypass as writing a route handler in `main` without a PR. The orchestrator MUST treat any change to `AGENTS.md`, `docs/proceso.md`, `docs/roadmap.md`, `docs/audits/*`, `docs/runbooks/*`, `docs/uat/*` exactly like a code change under §15.5.

Concretely, the orchestrator delegates the change to a subagent (typically via `task` with `sdd-apply` or the applicable skill), and the subagent follows this flow:

1. **Branch from `main`.** Branch name follows §15.2: `docs/<scope>` (e.g. `docs/agents-rule-17-orchestrator-discipline`).
2. **Edit on the branch.** Single, focused commit. Conventional commit in English (e.g. `docs(agents): add rule 17 orchestrator discipline`).
3. **Verify locally before push.** Run `git diff main...HEAD -- <file>` and read the full diff. Run a focused `grep` for typos, broken cross-references, and any internal mention that references an item the change was supposed to add or remove.
4. **Push + open PR.** PR title in English, conventional-commit style. PR body: free-form summary of the change + a link or reference to the conversation that requested it. Use `Refs`/`Closes` only when an issue exists.
5. **CI must be green.** For a docs-only PR this is mostly `ruff` and any lightweight check; the gate is "green", not "trivial".
6. **Return, do not merge.** The orchestrator (and the subagent that drove the work) returns the commit SHA on the branch + the PR URL + a summarized diff to the user. **The orchestrator does NOT merge.** The user reviews and merges, per §15.5.

WRONG — orchestrator edits AGENTS.md inline in the chat

```
edit(AGENTS.md)   # orchestrator session, "just adding rule 17"
```

RIGHT — orchestrator delegates to a subagent

```
task(subagent="sdd-apply",
     branch="docs/agents-rule-17-orchestrator-discipline",
     instructions="…add §17 to AGENTS.md per user spec. Anchored to
                   code-review-expert (mandatory each slice) and
                   judgment-day (mandatory for high-stakes). §17.3
                   explicitly forbids orchestrator inline edits.
                   Follow §15.5 flow. Do NOT merge.")
```

The orchestrator MAY write the proposed §17 text in the delegation prompt itself (as a reference snippet), but the file write, commit, push, and PR open MUST happen on the subagent's side. The orchestrator does not own those operations.

Enforcement: a violation of §17.1 (orchestrator writes inline) is a discipline failure and the work MUST be reverted and re-done via a subagent on a branch. A violation of §17.2 (skipping a mandatory lens on a high-stakes diff) is a merge blocker — the merge cannot proceed without the lens sign-off. A violation of §17.3 (orchestrator edits `AGENTS.md` or another operational doc inline) is the same as a §15.5 violation: the change must be reverted and re-landed through the proper flow, and the orchestrator must acknowledge the slip before continuing.

### 18. Web ↔ Legacy mutual exclusion + mandatory sync (project-level)

APAP_WEB runs as a **web app OR a legacy Access/VBA app, never both at the same time**. The two modes share the domain model (animales, voluntarios, entradas, acogidas, adopciones, sanidad, etc.) but the runtime backend differs:

| Mode | Backend | Code path |
|---|---|---|
| **Web** | InsForge (PostgREST-compatible PostgreSQL BaaS) | `app/core/insforge.py` → InsForgeClient |
| **Legacy** | Access `.accdb` linked tables (legacy schema `Tb*`) | `app.core` delegates to a legacy adapter that reads via DAO or Dysflow |

**Mode selection** is a runtime configuration (env-flag or `Settings.mode`). When `mode = "web"`, the app talks to InsForge exclusively. When `mode = "legacy"`, it talks to the Access backend exclusively. The two are NEVER both running against the same dataset in the same session.

### 18.1 Mandatory sync function (HARD)

**Both modes write to their respective backends independently**. There is no shared live state. To move data between them, the project ships a **MANDATORY bidirectional sync function** (per user directive 2026-07-05):

- Lives in `migration/` package (engine + CLI).
- Direction is configurable: `legacy → web`, `web → legacy`, or `bidirectional` with last-write-wins / merge-by-natural-key.
- The sync MUST be **idempotent**: re-running with no changes produces no diff. Implementation uses `web_only_feature_shadow` table (or equivalent) to track divergence between the two backends and only writes the rows that actually differ.
- The sync MUST be **auditable**: every row written is logged via `log_safe("sync.applied", table, pk, direction, source_hash, target_hash)`.
- The sync MUST be **safe under concurrent mutation**: the engine holds an advisory lock (file-based or DB-level) so two operators don't run conflicting syncs simultaneously.

### 18.2 CLI surface (already exists)

The sync CLI is `python -m migration reconcile` (see `migration/cli.py`):

```bash
# Read-only: enumerate divergences without writing
python -m migration reconcile --check-only

# Walk divergences interactively
python -m migration reconcile --interactive

# Filter to one table
python -m migration reconcile --table voluntarios

# Filter by divergence timestamp
python -m migration reconcile --since 2026-06-20T00:00:00+00:00
```

The CLI ships `apap-migrate reconcile <flags>` as the entry point.

### 18.3 Failure modes (HARD REJECT)

- ❌ Code paths that read BOTH backends in the same request. Pick one per request.
- ❌ Code paths that write to one mode while reading the other. Pick one per request.
- ❌ Configuration that lets both backends be live simultaneously (env-flag gate at startup, fail-fast if both are reachable).
- ❌ Sync runs that don't idempotency-check before applying. Use the diff engine.
- ❌ Sync runs without `log_safe` audit. Every row written is logged.

### 18.4 Enforcement

The mode-toggle and sync-function are enforced at three layers:

1. **Settings** (`app/core/config.py`) reads `APAP_MODE` env (`web` | `legacy`). Startup fails fast if both `APAP_INSFORGE_URL` and `APAP_LEGACY_ACCDB_PATH` are reachable.
2. **`InsForgeClient`** is the only object allowed to talk to InsForge. **`LegacyAdapter`** is the only object allowed to talk to the Access backend. Service code imports ONE, never both.
3. **`migration/`** is the only package allowed to read BOTH backends. Route + service code MUST NOT import `migration/`.

Enforcement: PR review + `tests/test_mode_isolation.py` (atomic test that confirms a single request reads from exactly one backend).

### 19. Global coverage floor — 80% enforced in CI

The `fail_under = 80` threshold declared in `pyproject.toml` (`[tool.coverage.report]`) is not documentation: the CI `test` job runs pytest with `--cov=app --cov-report=json --cov-fail-under=80`, so any change that drops total coverage of `app/` below 80% fails the build. The same run writes `coverage.json`, which feeds the `CRITICAL_HELPERS` 100% gate (rule 11) — that gate is unchanged and still applies on top of the global floor. Removing any of the coverage flags from `ci.yml` (or lowering the floor) is a blocked change: it silently disables both gates.

Enforcement: `tests/test_ci_workflow.py::test_ci_workflow_test_job_enforces_global_coverage_floor` pins the flags in `ci.yml` and their parity with `fail_under` in `pyproject.toml`; `--cov-fail-under=80` makes pytest exit non-zero below the floor; `scripts/pytest_plugin/coverage_gate.py` keeps enforcing 100% on `CRITICAL_HELPERS` from the produced `coverage.json`.

### 20. APAP001/APAP003 rule linter enforced in CI

The custom AGENTS.md rule linter (`scripts/check_rules.py` — APAP001 route/SQL isolation, APAP003 raw-logger ban, plus Detectors 2-8: auth default-deny, redirects, DDL role lists, `print` ban, CSRF middleware/SameSite) is a CI gate, not just a local convenience. The `lint` job in `.github/workflows/ci.yml` runs `python scripts/check_rules.py .` after `ruff check .`; any violation fails the build. Ruff cannot run these rules itself (ruff 0.15+ rejects Python-defined rule selectors in `select`), so the AST linter step is the ONLY automated enforcement of APAP001/APAP003 — removing the step from `ci.yml` is a blocked change. The linter must scan the repo root (`.`): passing `app` as the scan root silently disables Detectors 5-8, which resolve `app/`-relative paths against the scanned root. Known false positives stay silenced via `DEFAULT_EXCLUDES` and `.check_rulesignore`.

Enforcement: `tests/test_ci_workflow.py::test_ci_workflow_lint_job_runs_check_rules_gate` pins the step (scoped to the lint job's executable lines) and the repo-root invocation; `scripts/check_rules.py` exits non-zero on any violation, failing the `lint` job; the visitors stay pinned by `tests/test_ruff_apap001.py` and `tests/test_apap003.py` so the ruff-plugin mirror and the CI gate cannot drift.

### 21. Module-size budget — 700 lines, shrink-only baseline

No Python module under `app/` or `migration/` may exceed **700 lines** (`tests/` and `scripts/` are exempt — the budget targets product code, where god-files hide layering violations). The modules that already exceeded the budget when this rule landed (2026-07-18 audit: `migration/cli.py`, `migration/reconcile.py`, `migration/apply.py`, `app/modules/materiales/service.py`) live in an explicit `BASELINE` dict inside `scripts/check_module_size.py` that is a **ratchet**: entries may only shrink or disappear, never grow, and no new entry may ever be added. When a feature would push a module over the budget, split it (extract a `queries.py`, a subcommand module, a helpers module) instead of growing it.

WRONG — growing a god-file because "it's where the other handlers are"

```python
# migration/cli.py, line 1072+ — new subcommand appended to the god-file
def cmd_export(...): ...
```

RIGHT — new capability in its own module, god-file only shrinks

```python
# migration/export.py — new module, well under budget
def cmd_export(...): ...
```

Enforcement: `python scripts/check_module_size.py` (stdlib-only, exit 1 on violation) runs as its own step in the CI `lint` job — removing the step is a blocked change, pinned by `tests/test_module_size.py::test_ci_workflow_lint_job_runs_module_size_gate` (scoped to the lint job's executable lines). `tests/test_module_size.py::test_baseline_matches_measured_tree` fails on any drift between `BASELINE` and the real tree, so shrinking a baselined module requires updating its entry in the same PR.

### 22. SQL/service separation — query construction is its own seam

New or refactored services separate **query construction** from **validation/orchestration**. SQL strings and their parameter shaping live in a dedicated `queries.py` (or builder module) per feature module; the service imports those builders, applies domain validation, and talks to the client. The point is testability: the shape of the SQL must be assertable in a plain unit test without spinning up transport, InsForge, or HTTP.

WRONG — SQL interpolated inline among validation and mapping (untestable without transport)

```python
def update_material(client, material_id, form):
    if not form.get("nombre"):
        raise ValueError("nombre required")
    client.execute_sql(
        f"UPDATE materiales SET nombre = $1 WHERE id = $2", [form["nombre"], material_id]
    )
```

RIGHT — query builder is a pure function, service orchestrates

```python
# app/modules/materiales/queries.py
def build_update_material(material_id: str, nombre: str) -> tuple[str, list]:
    return "UPDATE materiales SET nombre = $1 WHERE id = $2", [nombre, material_id]

# app/modules/materiales/service.py
def update_material(client, material_id, form):
    if not form.get("nombre"):
        raise ValueError("nombre required")
    sql, params = queries.build_update_material(material_id, form["nombre"])
    client.execute_sql(sql, params)
```

This applies to **new services and to any existing service being refactored** (e.g. when splitting a rule-21 baselined module, the extracted seam is exactly this one). It does not mandate a big-bang rewrite of existing services.

Enforcement: PR review. A PR that adds a service with inline SQL mixed into validation/orchestration, or refactors one without introducing the query seam, must be blocked with a pointer to this rule.

### 23. E2E expectation — every UI feature slice grows the E2E net

Every feature slice that adds or changes UI (routes rendering templates, forms, HTMX interactions) MUST add or update at least one Playwright E2E flow under `tests/e2e/`. Backend-only slices (services, migration, scripts) are exempt. The E2E suite is the only net that catches template/route/CSRF wiring regressions that unit tests structurally cannot see.

The CI `e2e` job is currently skipped when `APAP_OAUTH_CLIENT_ID` is not configured (see `.github/workflows/ci.yml`). Once OAuth secrets exist in CI, the job stops being optional and becomes a required check (tracked in issue #206) — do not add new reasons to skip it.

Enforcement: PR review. A PR whose diff touches `templates/` or adds/changes a UI route without touching `tests/e2e/` must justify the exemption explicitly in the PR description or be blocked.

### 24. mypy typecheck gate — zero errors on `app/` + `migration/`

Static typing is enforced, not aspirational: the CI `typecheck` job runs `python -m mypy` and any error fails the build. Scope and flags live in `pyproject.toml` under `[tool.mypy]` — the **single source of truth** (`files = ["app", "migration"]`, `warn_unused_ignores`, `warn_redundant_casts`, `show_error_codes`, `python_version = "3.11"`); neither the CI job nor the Makefile repeats them, so `make typecheck` locally runs the exact same check as the CI `typecheck` job. Every `# type: ignore` MUST carry its specific error code (e.g. `# type: ignore[assignment]`) — bare ignores are banned, and `warn_unused_ignores` deletes stale ones. Removing the `typecheck` job, removing flags from `[tool.mypy]`, or shrinking `files` is a blocked change: it silently un-types whole packages. Tightening is one-way — the config may only ADD flags (e.g. per-module `strict = true`), never drop them.

Enforcement: `tests/test_ci_workflow.py::test_ci_workflow_defines_typecheck_job_running_mypy` pins the CI job and its `python -m mypy` invocation; the deploy job `needs` list includes `typecheck`, so a typing regression blocks deploys; mypy exits non-zero on any error, failing the job.

---

> **History:** the resolved "Known conflicts with existing code" tracker (all
> rows DONE during the `hardening-2026-q2` chain) was moved out of this file to
> [`docs/hardening-2026-q2-rule-history.md`](docs/hardening-2026-q2-rule-history.md).
> This file carries only the live rules.
