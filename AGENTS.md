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

> **Architecture in transition (read before §1).** The target architecture is
> **hexagonal with vertical slices** — see **§33** for where a slice goes and
> what it contains, and epic #420 for the migration order. Rules §1, §5 and §22
> below describe the route → service → queries layout that is still present in
> unconverted modules under `app/modules/**`. They remain binding **for that
> code**. For new capabilities, and for any module being converted, **§33 is
> authoritative and outranks them**. Never add a new `service.py` that executes
> SQL.

### 1. Layer boundaries are absolute

Routes handle HTTP only: form parsing, auth guards, redirects, HTML rendering.
Services handle all data access: SQL, validation, domain logic.
Never call `client.execute_sql(...)` from a route. If the service method doesn't exist yet, create it first — do not bypass the layer as a temporary measure.

In a converted slice the same boundary holds with different names: the route
delegates to a **use case** in `application/`, which reaches data through a
**port**. See §33.3.

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

In a converted slice, invariants live in `domain/` and are enforced by the use
case in `application/`; the route still only translates the error (§33).

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

This project is **pre-MVP**. The default rule is: **all work lands on `main`; merged branches are retained with `<type>/<issue>-<slug>` names (§15.2), not deleted, so a fork inherits the full branch history and live/dead refs are distinguishable at a glance.** There is no long-lived `staging` branch in pre-MVP. When the user declares MVP reached, the workflow reverts to the standard `staging` + UAT gate described in §"Post-MVP revert" below.

#### 15.1 Pre-MVP gate — all must be true before merging to `main`

1. **Local `pytest` is green.** `python -m pytest -W error::DeprecationWarning` with the same `addopts` from `pyproject.toml` ([tool.pytest.ini_options] block) passes locally. If `tests/test_voluntarios_concurrent.py` is part of the run, the environment must expose `APAP_E2E_BASE_URL` (per `ci.yml` and the REG-S-3 hardening) — in CI the file is `--deselect`-ed because GitHub does not provision Postgres.
2. **`ci.yml` is green on the head of the branch being merged.** Lint (`ruff check .` + the AGENTS.md rule linter `python scripts/check_rules.py .`, rule 20), `test` (pytest with `DeprecationWarning` as error), and `build` (`python -m build`) MUST pass. `e2e` and `deploy` are optional per `.github/workflows/ci.yml`: `e2e` is skipped when `APAP_OAUTH_CLIENT_ID` is not set; `deploy` is skipped when `COOLIFY_WEBHOOK_URL` is not set. Their absence is not a merge blocker in pre-MVP.
3. **Diff is reviewable.** A single PR diff should stay under the `review_budget_lines: 400` (orchestrator default). If a feature is larger, split into chained PRs using the `chained-pr` skill — never blow up main with a single oversized merge.
4. **No `--force`, no history rewrite.** Merge with `--no-ff` to keep the feature commit visible; never `git push --force` to `main`; never rebase already-shipped commits.

**Enforcement** lands in #442: a dedicated `.github/workflows/pr-size.yml` runs `scripts/check_pr_size.py` on every `pull_request`, comparing `git diff --shortstat` against the merge-base. Without an override, any PR over 400 lines fails the build. The `size:exception` label on the PR is the only acceptable override (§15.6) — explicit, visible, intentional. Pinned by `tests/test_ci_workflow.py::test_ci_workflow_pr_size_job_is_wired` and `tests/test_pr_size.py`. Refs Gentleman-Programming/gentle-ai's `Check PR Cognitive Load`, whose labels and budget we adopted but whose gate we did not (issue #442).

#### 15.2 Pre-MVP branch lifecycle — retain merged branches, name them `<type>/<issue>-<slug>` (issue #440)

Merged branches are **retained**, not deleted. Rationale: a fork inherits more value with the full branch history, and abandoned/unmerged branches are otherwise lost outright. The user's decision on 2026-08-06 made retention the policy.

The counter-argument is a factual note that has to live next to the rule so nobody "re-optimises" it back to deletion: deleting a branch ref never deleted its commits. With `--no-ff` (already required by §15.1) they stay in `main`'s history under the merge commit, and GitHub retains `refs/pull/<n>/head` permanently. What deletion actually cost was the **named pointer**, `git log --graph` readability, and any **unmerged** branch. So the benefit of retention is narrower than it looks, while the cost — dozens of dead refs indistinguishable from live ones — is immediate. **Naming is what makes the policy viable**, not a nicety.

**Naming convention.** Branch names MUST follow `<type>/<issue>-<slug>`:

- `<type>` is one of `feat | fix | refactor | docs | ci | test`.
- `<issue>` is the GitHub issue number the branch resolves (no leading `#`).
- `<slug>` is lowercase ASCII kebab-case, `[a-z0-9-]+`.

Examples: `feat/431-mutation-gate`, `fix/429-integration-job`, `refactor/437-slice-boundary`. The issue number is the point — a dead branch must explain itself in two years and link to its issue, which links to its PR.

**`archive/` rename prefix.** Abandoned branches — superseded, declined, or otherwise retired — MUST be renamed with the `archive/` prefix before being left behind (`git branch -m archive/<old-name>`). Live and dead are distinguishable at a glance, not by reading the last commit.

**Carve-outs.** `main` is the only branch exempt from the convention. `staging` does not exist in pre-MVP and is recreated at the §15.4 MVP flip — that gate is unchanged by this rule. Branches that pre-date the rename live in a shrink-only allowlist inside the #441 enforcement script; entries are removed only when the branch is renamed into compliance or deleted. Adding to the allowlist is a one-shot calibration with explicit justification, never routine.

**Enforcement** lands in #441 (a CI branch-name gate). Pinned by `tests/test_ci_workflow.py::test_ci_workflow_lint_job_runs_branch_name_gate` once that PR lands. Until #441 ships, the convention is enforced by PR review at merge time. Refs #436.

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

#### 15.6 Standing merge authorization (granted 2026-07-26, until project end)

Effective 2026-07-26 and until the user signals the project end, the orchestrator has standing authorization to merge PRs to `main` without per-push user OK. This is a temporary convenience for the pre-MVP phase.

**Scope of the authorization**: the orchestrator may merge a PR to `main` itself when ALL of the following hold:

1. §15.1 pre-MVP gates are visibly green:
   - local `pytest -W error::DeprecationWarning` passes
   - `ci.yml` on the head of the merged branch is green (lint, test, typecheck, build)
   - diff ≤ `review_budget_lines` (or maintainer-approved `size:exception`)
   - no `--force`, no history rewrite
2. The merge is a normal feature-branch → main merge (NOT a force-push, NOT a release tag, NOT a default-branch rename, NOT a change to git-hooks or `gentleai.stagingOnly`).
3. The merge commit body or PR description cites the `ci.yml` run URL that proved the gate green (per §15.5 enforcement note).
4. No change touches any §15.5 list item that still requires explicit user OK.

**Items that STILL require explicit per-push user OK** (the §15.5 list is unchanged):

- Direct commits to `main` without a PR.
- `--force` to any branch.
- Tagging releases / cutting `vX.Y.Z`.
- Renaming the default branch, changing branch protection on GitHub.
- Anything that touches `git-hooks/`, the user's global `core.hooksPath`, or any other project's `gentleai.stagingOnly` flag.

**Revocation**: the user can revoke this standing authorization at any time with phrases like "stop auto-merging", "back to per-push OK", "revoke merge authorization", or equivalent. On revocation, this section becomes dormant and the orchestrator reverts to returning PRs without merging.

**Project-end signal**: when the user signals project end ("MVP reached", "project end", "archive", or equivalent), this section becomes dormant. Subsequent work reverts to the standard post-MVP flow (§15.4 reverts; staging re-engages per the global `staging-acceptance-contract`).

This standing authorization was granted in chat on 2026-07-26 and codified by the same PR that updated §17.3 step 6. Cross-reference: §17.3 step 6.

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
6. **Return and merge if §15.6 authorizes it.** The orchestrator (and the subagent that drove the work) returns the commit SHA on the branch + the PR URL + a summarized diff. If §15.6 standing merge authorization is in effect AND all §15.1 gates are visibly green (local + CI), the orchestrator merges the PR to `main` itself, citing the `ci.yml` run URL in the merge commit body. Otherwise (revoked, dormant, gates red, or any §15.5 list item touched), the orchestrator returns without merging and the user reviews and merges per §15.5.

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

In a converted slice this seam is `adapters/insforge/<slice>_insforge_queries.py`,
next to the adapter that uses it (§33.3). SQL never appears in `application/`.

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

**QA-through-UI only.** Verification of any UI-facing feature slice MUST go through the existing Playwright E2E suite under `tests/e2e/` (or an equivalent in-tree browser test). QA via the Python shell, direct DB inspection, or `curl` against a running server is NOT a substitute and MUST NOT be presented as such in PR descriptions, runbooks, or status reports. The rationale: §32.P1 — hardening concentrates where the work is interesting while the HTTP edge gets nothing; the E2E suite is the layer that catches the edge regressions the unit suite cannot see. PR descriptions that claim a UI slice "verified by inspecting the DB" or "verified by running curl" are review-blockers and MUST be sent back for E2E coverage.

This rule applies to the **verification step** of a PR, not to the **development loop** (developers may use shell, `curl`, or DB inspection to debug while iterating). The rule defines which evidence is accepted as "QA passed" when a PR lands.

The CI `e2e` job is currently skipped when `APAP_OAUTH_CLIENT_ID` is not configured (see `.github/workflows/ci.yml`). Once OAuth secrets exist in CI, the job stops being optional and becomes a required check (tracked in issue #206) — do not add new reasons to skip it.

Enforcement: PR review. A PR whose diff touches `templates/` or adds/changes a UI route without touching `tests/e2e/` must justify the exemption explicitly in the PR description or be blocked.

### 24. mypy typecheck gate — zero errors on `app/` + `migration/`

Static typing is enforced, not aspirational: the CI `typecheck` job runs `python -m mypy` and any error fails the build. Scope and flags live in `pyproject.toml` under `[tool.mypy]` — the **single source of truth** (`files = ["app", "migration"]`, `warn_unused_ignores`, `warn_redundant_casts`, `show_error_codes`, `enable_error_code = ["ignore-without-code"]`, `python_version = "3.11"`, `platform = "linux"` — CI's platform is the authoritative view); neither the CI job nor the Makefile repeats them, so `make typecheck` locally runs the exact same check as the CI `typecheck` job. Every `# type: ignore` MUST carry its specific error code (e.g. `# type: ignore[assignment]`) — bare ignores are rejected by the `ignore-without-code` error code enabled in `enable_error_code`, while `warn_unused_ignores` deletes ignores that are no longer needed. Removing the `typecheck` job, removing flags from `[tool.mypy]`, or shrinking `files` is a blocked change: it silently un-types whole packages. Tightening is one-way — the config may only ADD flags (e.g. per-module `strict = true`), never drop them.

Enforcement: `tests/test_ci_workflow.py::test_ci_workflow_defines_typecheck_job_running_mypy` pins the CI job and its `python -m mypy` invocation; the deploy job `needs` list includes `typecheck`, so a typing regression blocks deploys; mypy exits non-zero on any error, failing the job.

### 25. No duplicated cross-module helper functions

Rule 4 says one source of truth per domain concept for *values* (enums, lists). For the helper names explicitly watched by Detector 10, apply the same principle: do not copy-paste them across modules. The 2026-07-20 architecture review found `_opt()` copied near-identically into five `routes.py` files (`app/modules/{animals,entradas,foster,materiales}/routes.py` + `materiales/acogida_routes.py` — and, once the full watch-list ran, into several more) and `_required_text`/`_optional_text` reimplemented across eight `service.py` files. Each copy's docstring literally says "mirrors X" — the duplication was *noticed* and left anyway, because there was no shared module to import from and no gate stopping the copy-paste. Issue #227 tracks consolidating these into one shared module; this rule prevents those specifically watched helpers from spreading again once #227 is fixed.

WRONG — noticing the duplication and copy-pasting anyway

```python
# app/modules/materiales/routes.py
def _opt(value: str | None) -> str | None:
    """Mirrors the ``_opt`` precedent in ``app/modules/foster/routes.py``."""
    if value is None:
        return None
    return value.strip() or None
```

RIGHT — one shared helper, every module imports it

```python
# app/core/form_helpers.py
def opt(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None

# app/modules/materiales/routes.py
from app.core.form_helpers import opt as _opt
```

Enforcement: a **watch-list regression guard**, not a general duplicate-code detector — `scripts/check_rules.py` Detector 10 (`duplicate_helper_definition`) inspects only names explicitly listed in `WATCHED_DUPLICATE_HELPERS` (initially `_opt`, `_required_text`, and `_optional_text`). For each watched name, definitions already recorded in the shrink-only `BASELINE_DUPLICATE_HELPERS` ratchet are tolerated; any definition in an additional file fails. A watched name without a baseline fails when it is defined in more than one file. Calls, imports, differently named helpers, and semantic duplicates are outside this detector's scope. Tests: `tests/test_check_rules.py` (Detector 10 section).

### 26. Justify or eliminate lazy-import cycle workarounds

A local `import` inside a function or method body under `app/` is a deliberate escape hatch for circular imports — it should never be silent, and **adding a new one is a regression** the project does not authorise. The 2026-07-20 review found exactly two such imports (`app/core/config.py`'s `writer_rols` property importing `Rol` from `auth.py`; `app/core/auth_dependencies.py` importing `get_user_by_email` from `auth.py` inside a function), tracked as issue #226. By 2026-08-07 the count had grown to **19 lazy-import markers across 7 files**, with no machine rejecting new ones — that is the §32.P3 anti-pattern this rule was supposed to prevent, and what issue #443 fixes.

WRONG — unexplained local import

```python
def get_settings_rol(self):
    from app.core.auth import Rol
    return Rol
```

RIGHT — the marker references an entry in the baseline; it does not authorise a new one

```python
def get_settings_rol(self):
    # lazy-import: BASELINE entry app.core.config -> app.core.auth
    # (see scripts/check_import_cycles.py). Break the cycle at source.
    from app.core.auth import Rol
    return Rol
```

Enforcement is **two layers**, not one:

1. **Marked** — `scripts/check_rules.py` Detector 11 (`unjustified_lazy_import`) still flags any `Import`/`ImportFrom` node whose nearest enclosing scope is a function/method (not module level) under `app/`, unless its own source line or the line immediately before it contains the substring `lazy-import:`. A bare marker is a precondition, not a justification.
2. **Gated** — `scripts/check_import_cycles.py` (issue #443) runs Tarjan SCC over the app/ import graph and fails on any cycle that is not in its `BASELINE`. A new `lazy-import` that creates a fresh cycle fails the CI `lint` job; a `lazy-import` against an already-baselined cycle still fails review if it grows the cycle's footprint. The baseline is **shrink-only**: removing an entry requires deleting it together with the lazy-import it documents.

Adding a lazy-import is only allowed if the cycle it dodges is already in `BASELINE` and the import keeps the cycle's footprint unchanged. Anything else is either "fix the cycle at source" or "freeze the new cycle in `BASELINE` with an explicit reason in a follow-up PR". The marker never authorises a new cycle on its own — that is the rubber stamp issue #443 retired.

Tests: `tests/test_check_rules.py` (Detector 11), `tests/test_import_cycles.py`, and `tests/test_ci_workflow.py::test_ci_workflow_lint_job_runs_import_cycle_detector`.

### 27. Cross-module imports go through the target module's public API only

The 2026-07-20 dependency-map audit confirmed this project is otherwise a clean DAG with almost zero inter-module coupling — most domain modules under `app/modules/` import nothing from each other. Two exceptions surfaced: `app/modules/foster/assignment.py` imported `app.modules.animals.service` directly (bypassing `animals/__init__.py`, which exposes no public API — issue #231), and `app/modules/acogidas/routes.py` did the equivalent shorthand-submodule import into `foster.assignment` instead of using the `assignment_service` name `foster/__init__.py` already exports publicly (fixed directly in the PR that added this rule). This rule exists to keep the DAG clean as the project grows to more modules.

From within `app/modules/<A>/`, an import of `app/modules/<B>/` (A != B) MUST (a) import from the package `app.modules.<B>` (its `__init__.py` public surface), never a submodule path like `app.modules.<B>.service` — including the `from app.modules.<B> import service` shorthand, which reaches the same submodule — and (b) never import a name starting with `_`, regardless of source.

WRONG — reaching into a sibling module's submodule directly

```python
# app/modules/foster/assignment.py
from app.modules.animals import service as animals_service
```

RIGHT — importing from the target module's declared public API

```python
# app/modules/animals/__init__.py
from app.modules.animals.service import get_animal_by_id

# app/modules/foster/assignment.py
from app.modules.animals import get_animal_by_id
```

Enforcement: `scripts/check_rules.py` Detector 12 scans every `ImportFrom` under `app/modules/**/*.py` whose module path starts with `app.modules.` and targets a *different* module than the importing file's own. It flags `cross_module_submodule_import` when the import reaches past `app.modules.<name>` (either literally, or via the `from app.modules.<name> import <submodule>` shorthand, detected by checking whether the imported name matches an actual file/package under the target module), and `cross_module_private_import` when any imported name starts with `_`. The one still-open instance (issue #231 — `animals/__init__.py` needs a real public API designed before the import can be fixed, which is out of scope for a docs/tooling change) is grandfathered in a shrink-only `BASELINE_CROSS_MODULE_IMPORTS` allowlist; no new entries may be added. Same-module "private helper reused by a sibling file" drift (e.g. issue #232, `entradas/batch_service.py` importing `entradas/service.py`'s underscore-prefixed helpers) is a real but *different* pattern — same directory, not cross-module — and is intentionally out of this detector's scope; it stays PR review until a same-module variant is worth the false-positive risk of flagging legitimate intra-package helper sharing. Tests: `tests/test_check_rules.py` (Detector 12 section).

### 28. Thin routes: route-handler size ratchet

Rule 1 already says routes must be HTTP-only. This rule adds a concrete, automatable ratchet for it. The 2026-07-20 review found `app/modules/animals/routes.py::animal_foto` at 103 lines, mixing HTTP response-building with domain fail-closed photo policy (issue #233), when the median route handler in this codebase is 22 lines. A route handler that keeps growing is usually a sign that validation, retry/fallback policy, or business rules leaked into the route instead of the service layer.

WRONG — domain policy decided inline in the route

```python
@router.get("/{animal_id}/foto")
def animal_foto(animal_id: str, ...):
    try:
        animal = animals_service.get_animal_by_id(client, animal_id)
    except Exception:
        return Response(content=_PLACEHOLDER_PHOTO_PNG, media_type="image/png")
    # ...60+ more lines deciding placeholder-vs-stream fail-closed policy...
```

RIGHT — the route delegates the policy decision, and only builds the response

```python
@router.get("/{animal_id}/foto")
def animal_foto(animal_id: str, ...):
    outcome = photo_service.resolve_animal_photo(client, animal_id)
    return outcome.to_response()
```

Enforcement: `scripts/check_route_size.py` (stdlib-only, mirrors `scripts/check_module_size.py`'s ratchet shape) parses every `app/**/*routes*.py` file plus `app/main.py` with `ast`, finds every function decorated with `@router.<verb>(...)` or `@application.<verb>(...)`, and enforces a **50-line** hard cap on new handlers (calibrated against the real distribution: median 22, mean ~32 lines). The 15 handlers already over budget when the rule landed (`animal_foto` plus 14 siblings, including `app/main.py::callback` and `foster/assignment_routes.py::asignar_submit`) live in a shrink-only `BASELINE` dict — growing a baselined handler fails the check; no new entry may ever be added. Wired into the CI `lint` job immediately after the module-size ratchet step; removing the step is a blocked change. Tests: `tests/test_route_size.py` (mirrors `tests/test_module_size.py`'s shape: baseline-matches-measured-tree, CI-job-runs-the-gate).

### 29. Auth cache: single in-process backend + per-worker scope (issues #262, #287)

<!-- BEGIN region:issue-262-shared-auth-cache -->
The auth cache backing `require_authorized_user` (`app/core/auth_cache.py`, original issue #143) supports only the `in_process` backend. `APAP_AUTH_CACHE_BACKEND` remains as a compatibility guard: `in_process` is accepted; `redis` and every unknown value fail settings validation during application startup, before any request is served. Each uvicorn worker process holds its own in-memory cache, so `invalidate_auth(email)` reaches only the worker that called it and the worst-case cross-worker staleness window is `APAP_AUTH_CACHE_TTL_SECONDS` (default 300s). The current Coolify deployment was confirmed on 2026-07-25 as one application replica using the Dockerfile `CMD` with Uvicorn and no `--workers` override, so it runs one worker today. Before increasing the worker or replica count, set `APAP_AUTH_CACHE_TTL_SECONDS=0` for immediate revocation at the cost of one extra authorization `SELECT` per authenticated request. Full deploy, verification, and rollback steps live in `docs/runbooks/auth-cache-multi-worker.md`.
<!-- END region:issue-262-shared-auth-cache -->

### 30. Docstrings are synchronized contracts

Docstrings are part of the code contract: claims about current behavior, inputs, outputs, errors, or side effects MUST be covered by a test. Issue/PR references and production scars that are useful for onboarding MUST be labeled as historical context (not a contract) and preferably moved to `docs/` with a link; this policy complements the Domain services Protocol rule in §31.

**Cheap drift check (required in review):** for each behavioral claim, identify the test that proves it; verify every referenced symbol still exists; and verify every issue/PR reference still describes the current code. If a claim has no test, either add one or rewrite it as explicitly non-contract historical context.

```python
# Historical context — non-contract: see docs/audits/<feature>-audit-YYYY-Qn.md.
# Current contract: invalid tokens return 401 and never reach the service.
```

Enforcement: PR review using the checklist above. Do not add a new AST detector for prose matching; the heuristic is intentionally cheap and outcome-focused, while §31's Protocol boundary remains enforced independently.

---

> **History:** the resolved "Known conflicts with existing code" tracker (all
> rows DONE during the `hardening-2026-q2` chain) was moved out of this file to
> [`docs/hardening-2026-q2-rule-history.md`](docs/hardening-2026-q2-rule-history.md).
> This file carries only the live rules.

### 31. Domain services depend on Protocol abstractions

Domain services MUST depend on Protocol abstractions, never concrete backend clients.
`app.core.data_access.SqlExecutor`, introduced in #259, is the precedent.
Example: `def list_items(client: SqlExecutor) -> list[Item]: ...` — not `client: InsForgeClient`.

§33 is the slice-shaped form of this rule: the Protocol is the slice's own port
in `ports/<slice>_port.py`, expressed in domain terms rather than as a generic
SQL executor.

### 32. Anti-patterns — reject these by name

The 2026-07-25 full-codebase audit (issue #294) found that most defects were not
independent mistakes but **eight recurring shapes**. The individual instances are
tracked as their own issues; this rule exists so the *shapes* get rejected in
review before they produce new instances. The project is pre-MVP — this is the
window where conventions harden, and an anti-pattern that survives to MVP
survives forever.

Each pattern below names its 2026-07-25 instance so the rule stays concrete.
When you catch one in review, cite it by number: "this is §32.P4".

#### 32.P1 — Perimeter blindness

Hardening concentrates where the work is interesting (auth cache generations,
CSRF token comparison, PII redaction lists) while the HTTP edge gets nothing.

*Instance:* zero security headers anywhere in `app/` (#276), no rate limiting
(#286), email never normalised at the boundary (#278) — all while the core
auth model was revised four times (#143, #145, #146, #262).

**Criterion:** a PR that hardens an internal mechanism must state, in one line,
what the corresponding edge-layer exposure is and whether it is already covered.
"Not applicable" is a valid answer; silence is not.

#### 32.P2 — Insecure defaults that still boot

A missing secret degrades into an insecure-but-running app instead of a failed
deploy.

*Instance:* `session_secret` ships a working development placeholder and
`insforge_service_key` defaults to `""` (#275). A missing env var meant every
session cookie was signed with a secret published in this repository.

**Criterion:** no `Settings` field carrying a secret may have a default that
works in production. Either it has no default and pydantic fails, or startup
validates it and refuses to serve. A default that is *convenient in dev* must be
gated on an explicit development flag.

WRONG — the app boots and is silently insecure

```python
session_secret: str = "dev-only-change-me-in-production"
```

RIGHT — dev convenience, production refusal

```python
session_secret: str = "dev-only-change-me-in-production"

# …and in the lifespan, before serving:
if not settings.debug and settings.session_secret == _DEV_PLACEHOLDER:
    log_safe("startup.config_invalid", reason="session_secret_placeholder")
    raise RuntimeError("APAP_SESSION_SECRET must be set in production")
```

#### 32.P3 — Rules declared without a gate

A rule whose only enforcement is "PR review" does not change behaviour.

*Instance:* rule 22 (query-builder seam) needed a dedicated issue (#205) to get
its first application, months after landing; eight of nine modules still do not
follow it (#290). Every rule in this file that actually holds — §1, §9, §20,
§21, §25, §26, §27, §28 — has an AST detector or a shrink-only ratchet behind it.

**Criterion:** a new rule in this file ships with (a) a detector or ratchet, or
(b) an explicit baseline plus an adoption deadline. If neither is feasible, write
it as a documented *preference* and do not claim enforcement it does not have.

#### 32.P4 — Partial exception handling

The expected failure is caught; the adjacent one from the layer below escapes.

*Instance:* `admin_add_user` catches `ValueError` from the service and lets
`InsForgeError` from the transport reach an unhandled 500 (#277). There is no
global exception handler in `app/` to catch it either.

**Criterion:** any route calling a service that reaches InsForge handles both the
domain error and `InsForgeError` — or a global exception handler exists and is
tested. Never widen to a bare `except Exception` to satisfy this; name the errors.

#### 32.P5 — Docstrings left behind by refactors

*Instance:* the #233 route-thinning changed `photo_service` from streaming to
buffering and left the module docstring describing the old `StreamingResponse`
contract, including a `next(byte_iter)` pre-advance step that no longer exists
(#285).

Rule §30 already forbids this and did not catch it, because the refactor touched
the *function* while the stale contract lived in the *module* docstring.

**Criterion:** §30's drift check extends to the module docstring of every file in
the diff, not only the docstrings of the functions that changed. If a module
docstring describes a data flow, and the diff changes that flow, the docstring is
part of the diff.

#### 32.P6 — Tests that exist but never run

*Instance:* `test_voluntarios_concurrent.py` hard-fails without PostgreSQL and is
`--deselect`-ed in CI, so the only regression guard for the TOCTOU fix executes
nowhere (#282). Same family: the E2E job gated on a secret that is not set
(#206, #223).

**Criterion:** no test may be simultaneously hard-failing in the default local
run and excluded in CI. It runs somewhere, or it is a `skip` with a documented
reason and a linked issue. "Hard fail, not skip" is only a defensible design when
some pipeline actually satisfies the precondition.

#### 32.P7 — Guards that cancel themselves

Two individually reasonable rules that annihilate each other, with no test
pinning the interaction.

*Instance:* the CI `deploy` job skips commits matching `^Merge pull request #`,
while §15.2 makes every deploy-worthy push to `main` exactly such a commit
(#281). The deploy step had been dead for the entire pre-MVP period.

**Criterion:** every conditional guard in `ci.yml` carries a comment naming which
real events reach it and which are skipped, and `tests/test_ci_workflow.py` pins
the condition. A guard nobody can trigger is indistinguishable from a deleted step.

#### 32.P8 — Aggregate metrics hiding per-layer gaps

*Instance:* 89.18% global coverage concealed a route layer between 57% and 83%,
with `voluntarios/routes.py` at 57.3% (#288). The floor in `pyproject.toml` is
global, so nothing complained.

**Criterion:** quality floors are declared per layer, not only in aggregate. When
you raise a global threshold, check the distribution underneath it first and say
in the PR which file is the current minimum.

Enforcement: PR review, using the numbered criteria above as the checklist.
§32.P2, §32.P3, §32.P6 and §32.P7 are the four that are mechanically checkable —
when a PR adds a `Settings` secret, a new rule, a test, or a CI guard, the
reviewer applies the matching criterion before approving. The audit that produced
this rule is issue #294; its findings are labelled `audit-2026-07-25`.

### 33. Slice location — `app/core/` vs `app/modules/<slice>/`

The architecture is **hexagonal with vertical slices** (epic #420). This rule
answers the one question that comes up every single time a slice is written:
**where does it go?** Get this wrong repeatedly and the codebase ends up a
layered monolith with a hexagonal veneer.

#### 33.1 The two locations

- **`app/core/<layer>/<slice>/`** — cross-cutting capability. Today: `auth-users`
  (#414), `catalogos` (#415), `schema-bootstrap` (#416). Layers are global
  folders (`domain/`, `ports/`, `application/`, `adapters/insforge/`, `di/`) and
  the slice is a subdirectory inside each.
- **`app/modules/<slice>/`** — business capability. The slice owns its whole
  stack in **one** folder.

#### 33.2 The rule that decides

Apply in order:

1. Is it consumed by **two or more** slices, **and** does it have no business
   reason of its own to change? → `app/core/`.
2. Does it own business vocabulary and change for its own reason?
   → `app/modules/<slice>/`.
3. **In doubt, module.** Promoting into `core` later is cheap. Pulling something
   out of `core` once five consumers hang off it is not.

Criterion 1 needs **both** halves. "Feels foundational" is not a reason.
"Auth is already there" is not a reason. A single consumer is never enough.

#### 33.3 Layout of a module slice

```
app/modules/<slice>/
├── domain/                          # pure entities and rules, no I/O
├── ports/<slice>_port.py            # Protocol: what the use case needs
├── application/                     # one use case per file
├── adapters/insforge/
│   ├── <slice>_insforge_adapter.py  # implements the port
│   └── <slice>_insforge_queries.py  # SQL lives here (§22)
├── di/<slice>_di.py                 # composition root for the slice
└── routes.py                        # thin: parse, delegate, render (§28)
```

#### 33.4 What holds in either location

- `InsForgeClient` and `InsForgeError` are imported **only** under `adapters/`
  and `di/`, plus `app/main.py` which builds the pooled client. Domain, ports
  and application are transport-agnostic (§31 is the general form of this).
- No new `service.py` executing SQL. That is the layer this refactor retires;
  §1 and §5 describe it because it is still present in unconverted modules, not
  because new code should look like it.
- Acceptance criteria name the **capability** (store a file, send a
  notification), never the vendor that provides it.
- Every slice ships an architectural pin test that fails when a transport import
  leaks into the wrong layer. A rule without a gate is §32.P3.

#### 33.5 Known exception, recorded on purpose

`app/core/application/admin/` is consumed only by `app/core/admin_handlers.py`
and `app/main.py` — no second slice. By §33.2 it belongs in `app/modules/`. It
landed in `core` because it was converted early (#419), not because it is
cross-cutting.

It is **not** being moved: relocating a freshly merged slice is churn with no
functional gain. It is recorded here so it reads as a deliberate exception
rather than a precedent. Do not cite `admin` to justify putting the next
business capability in `core`.

Enforcement: `scripts/check_layers.py` is a CI gate in the `lint` job (issue
#436) — it enforces dependency direction, inner-layer purity and slice
boundaries over `app/`, exits non-zero on any new violation, and is pinned by
`tests/test_layers.py::test_ci_workflow_lint_job_runs_layers_gate`. The 53
violations that predate the gate live in a shrink-only `BASELINE` measured
against main @41fbd2a; entries may only disappear. One boundary semantic is
still an open design question (#437) and is marked `xfail(strict)` rather than
assumed. Plus PR review against §33.2 and the per-slice pin tests from §33.4.
The slice index, execution order and definition of done live in issue #420.

### 34. Test strength is measured, not assumed

Rules 11 and 19 gate **coverage**. Coverage answers "was this line executed",
which is not the question anyone actually cares about. The question is "if this
line were wrong, would a test fail?" — and a suite can hold 85% coverage while
answering *no*. The first mutation measurement of this codebase found
`migration/derivation.py` at 22.75% surviving mutants with 31 green tests over
it (#433). Nothing in the gate stack before #431 could see that.

This rule adopts the discipline from
[unclebob/swarm-forge](https://github.com/unclebob/swarm-forge), whose
`cleaner` / `hardener` / `QA` roles each own a named quality dimension with a
numeric target rather than a judgement call. We have no agent swarm; we have
gates. Same idea, different mechanism.

**Before extending the harness, read
[`docs/quality/hardening-roadmap.md`](docs/quality/hardening-roadmap.md).** It
carries the ordered plan, the standing assessment of what each gate does and does
not guarantee, and the measured facts about the tooling — including the ones that
cost hours to discover and will cost them again if re-derived. It is the handoff
document for any agent continuing this work.

#### 34.1 The quality ladder — cheap and structural first, semantic last

Run in this order. Each step is meaningless if the one before it is red.

| Order | Question | Owner |
|---|---|---|
| 1 | Does it parse, type, and lint? | `ruff`, `mypy` (§24) |
| 2 | Does it respect the boundaries? | `check_rules.py` (§20), `check_layers.py`, `check_module_size.py` (§21), `check_route_size.py` (§28) |
| 3 | Is complexity bounded and duplication flat? | `check_complexity.py`, `check_jscpd.py`, `check_mutation_sites.py` |
| 4 | Is it executed by tests? | coverage floors (§11, §19) |
| 5 | **Is it actually asserted by tests?** | `check_mutation.py` (§34.2) |

Steps 1–4 run per PR. Step 5 is a nightly/manual job — a 233-mutant session is
not a per-PR check. That split is deliberate, not a compromise.

#### 34.2 The mutation gate

Owned by `scripts/check_mutation.py`, configured in
`docs/quality/cosmic-ray.toml`, baselined in
`docs/quality/mutation-baseline.json`, run by the `mutation` job in `ci.yml`.
Full procedure: `docs/runbooks/mutation-testing.md`.

- The baseline is a **shrink-only ratchet**, exactly like §21 and §28: surviving
  mutant counts may only decrease. Raising an entry to make a run green is a
  blocked change — it converts a test-quality regression into the new normal.
- Adding a module to the target set is a PR of its own, with its measured entry
  in the same commit. Growth order and rationale live in #434.
- **Linux only.** cosmic-ray 8.4.6 reports every mutant as `INCOMPETENT` on
  native Windows while still printing a passing score. Reproduce locally through
  WSL; `make mutation` refuses to run anywhere else.

#### 34.3 Never trust a score without checking the run that produced it

This is the rule that generalises beyond mutation testing, and it is the one
worth internalising.

`cr-rate --fail-over 20` — the obvious gate, and the one the original design
specified — exits **0** on a session where 27 of 27 mutants failed to execute,
because a survival rate of `0.00` is indistinguishable from a perfect score. A
gate that cannot fail is §32.P7 with extra steps.

WRONG — gating on the score alone

```yaml
- run: cr-rate --fail-over 20 mutation.sqlite
```

RIGHT — reject a degenerate run before believing any number

```yaml
# 0 results, all INCOMPETENT, or 0 killed => FAIL, before any score is compared
- run: python scripts/check_mutation.py mutation.sqlite
```

Generalised: **when you add a quality metric, write down what a broken
measurement looks like and make the gate fail on it.** A metric whose failure
mode is silence is worse than no metric, because it manufactures confidence. If
you cannot describe how the measurement could break, you do not understand it
well enough to gate on it yet.

#### 34.4 Equivalent mutants are noise — filter them and say why

A mutant that no test could ever kill is not debt.
`ReplaceBinaryOperator_BitOr_*` mutates the `|` in PEP 604 annotations
(`str | None`); every module here carries `from __future__ import annotations`,
so those never evaluate. On the pilot they were **66 of 104 reported
survivors** — 63% of the score was noise about to be frozen into a baseline as
if it were real.

`cr-filter-operators` runs between `init` and `exec` and is not optional. Any
addition to `exclude-operators` must carry a comment stating what class of
mutant it removes, why that class is unkillable, and what genuine signal is lost
with it.

#### 34.5 Testability is a design constraint, not a testing problem

swarm-forge separates *testable* modules from *environmentally unsuitable* ones
— code that opens GUIs, drives external devices, or hangs under automation — and
requires the unsuitable boundary to be as small as possible and excluded from
tools that run tests. This project has exactly such a boundary: the Access half
of `migration/` (`legacy_access_client.py`, `legacy_reader.py`, and the MSACCESS
pre-flight in `apply.py`) cannot run on the Linux CI runner at all.

The constraint that follows is the same one §31 already states for Protocols,
applied to the process boundary:

- Domain and derivation logic must be reachable **without** Access, InsForge, or
  HTTP. `migration/derivation.py` is the model: pure functions, 31 unit tests, a
  mutation target.
- Access-bound code stays a thin adapter shell. When a behaviour is worth
  testing, it does not belong in the shell — move it out first, then test it.
- A module that cannot run in CI is excluded from the coverage and mutation
  targets rather than silently dragging their numbers around.

WRONG — policy trapped behind the unsuitable boundary

```python
# migration/legacy_access_client.py
def read_ficha(self, pk):
    row = self._dao.OpenRecordset(...)               # Windows-only, untestable
    if row["FechaAlta"] and not row["FechaBaja"]:    # domain rule, stranded
        return "activo"
```

RIGHT — the rule moves out, the shell stays dumb

```python
# migration/derivation.py  (pure, tested, mutation-gated)
def derive_state(fecha_alta, fecha_baja) -> str: ...

# migration/legacy_access_client.py
def read_ficha(self, pk):
    row = self._dao.OpenRecordset(...)
    return derive_state(row["FechaAlta"], row["FechaBaja"])
```

Enforcement: §34.2's ratchet is a CI gate — `scripts/check_mutation.py` exits
non-zero and the step is pinned by `tests/test_ci_workflow.py`. §34.1's ordering
is enforced by the existing per-step gates it indexes. **§34.3, §34.4 and §34.5
are PR review**, and per §32.P3 they are documented preferences with no detector
behind them — do not claim otherwise. §34.5's boundary is partially covered by
§31's Protocol rule and `check_layers.py`; the Access-shell judgement is not
automatable today.

