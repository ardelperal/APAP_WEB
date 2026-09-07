# Design: CI/CD Foundation

## Technical Approach

Implement the delivery pipeline in three layers. Historical planning assumed chained PRs landing on `main` while APAP-WEB was pre-MVC; current repository policy uses `staging` for normal work, while production deployment remains guarded on `main`:

1. **Local test surface (CI-01)** — ship `pyproject.toml` with `pytest` + `ruff` config, a `Makefile` entry point, and `docs/development.md`. The deprecation-as-error flag (`filterwarnings = ["error::DeprecationWarning"]`) is set in `pyproject.toml` per `docs/architecture/architecture-local_backend-stack.md § CI/CD Quality Gate`.
2. **GitHub Actions CI (CI-02)** — a single workflow file `.github/workflows/ci.yml` with `lint`, `test`, `build`, and E2E hook coverage. CI runs on `main` and `staging`; branch-protection evidence is operator-owned.
3. **CD pipeline (CD-01)** — a `deploy` job in the same workflow gated on `push: main` and `needs: [lint, test, build]`. The job fires the Coolify webhook using `COOLIFY_WEBHOOK_URL`.

Forward planning for CD-03 and ENV-01 is captured in the spec and tasks but not implemented in this change; their checkboxes remain unchecked until Virginia adopts the MVC/MVP.

## Architecture decisions

| Decision | Choice | Alternative | Why |
|----------|--------|-------------|-----|
| **Workflow file layout** | Single `ci.yml` with `lint`/`test`/`build`/`deploy` jobs | Separate `ci.yml` + `deploy.yml` files | Single file keeps the dependency graph (`needs:`) explicit and reviewable; easier to reason about deploy gating |
| **Test framework** | `pytest` | `unittest`, `nox` | `pytest` is FastAPI-community standard, supports the `filterwarnings` config the architecture doc requires, and is what the archived TDD policy references |
| **Lint tool** | `ruff` | `flake8`, `pylint` | `ruff` is faster, single binary, current best practice per Context7; matches the architecture doc's preference |
| **Branch policy during this change** | Current work targets `staging`; production deploy stays on `main` | Historical `main`-only planning | The repo has moved past the original pre-MVC assumption; SDD status must not keep stale main-only text as current policy |
| **CD trigger** | Push to `main` after CI passes | Manual deploy step | Production deployment remains guarded on `main`; `staging` is the normal integration branch |
| **Coolify integration** | Webhook URL stored in GitHub Actions secret; workflow calls `curl` | Coolify MCP from CI runner | Webhook is the documented integration path; the Coolify MCP requires operator-only authentication and is for management, not CI triggers |
| **LocalBackend integration** | ~~`local_backend_create-deployment` MCP tool via CI step~~ **N/A since 2026-06-19** | LocalBackend REST API direct | Reconsidered: APAP_WEB is a FastAPI backend deployed to Coolify, not an LocalBackend-hosted SPA. LocalBackend acts only as BaaS; schema bootstrap is a separate future issue |
| **E2E test slot in CI** | Explicit E2E job/hook that runs when `tests/e2e/**` exists | Omit entirely | Keeps E2E visible in CI without claiming this foundation change completed the E2E suite |
| **Spec format for new capability** | Full spec + `## Delta from ci-cd-foundation` | Pure delta spec | This is a NEW capability; archive will copy the full content to `openspec/specs/ci-cd-pipeline/spec.md` |

## Data flow

```text
Developer
   │  git push feature-branch
   ▼
GitHub pull request to staging (normal work) or main (production/release)
   │
   ▼
.github/workflows/ci.yml
   ├── lint job      (ruff check)
   ├── test job      (pytest -W error::DeprecationWarning)
   ├── build job     (python -m build / docker build)
   └── E2E job/hook (runs only when tests/e2e/** exists)
        │
         ▼  all green on pull_request/push to main or staging
   ┌────┴────────────────────────────────┐
   │           deploy job                │
    │  (runs only on push:main)           │
   │                                     │
    │  └── curl $COOLIFY_WEBHOOK_URL      │  ──► Coolify (VPS, FastAPI/HTMX)
   └────┬────────────────────────────────┘
        ▼
Production live
```

Future production-gated flow (deferred — captured in spec/tasks, not implemented here):

```text
PR to staging ──► CI ──► Coolify staging ──► UAT checklist ──► Virginia OK
   │
   ▼  merge staging → main
Production deploy (gated on UAT pass or override)
```

## File changes

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Create | Project metadata, pytest config with `filterwarnings = ["error::DeprecationWarning"]`, ruff config |
| `Makefile` | Create | `make test`, `make lint`, `make build` targets wrapping the canonical commands |
| `tests/test_smoke.py` | Create | One passing assertion so the CI test job is never vacuous |
| `docs/development.md` | Create/update | Clone, install, env vars, test/lint/build commands, expected output, branch/deploy policy note |
| `.github/workflows/ci.yml` | Create/update | GitHub Actions workflow: lint, test, build, E2E hook, deploy job |
| `.github/branch-protection.md` | Create/update | Operator-facing note: required CI check names and how to enable branch protection on the active protected branch policy (`staging` for normal work; `main` for production if required) |
| `.gitignore` | Modify | Add `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `dist/`, `build/`, `*.egg-info/` |
| `openspec/config.yaml` | Modify | `strict_tdd: true`, `test_command: "pytest"`, `build_command: "python -m build"`, `linter: ruff`, `coverage_threshold: 80` |
| `openspec/changes/ci-cd-foundation/{proposal,design,tasks,specs/ci-cd-pipeline/spec.md}` | Create | SDD artifacts for this change |

## Interfaces and contracts

### Workflow contract (`.github/workflows/ci.yml`)

| Job | Trigger | Steps | Required secrets |
|-----|---------|-------|------------------|
| `lint` | `pull_request`/`push` to `main` or `staging` | Checkout → setup-python → install dev dependencies → `ruff check .` | none |
| `test` | same | Checkout → setup-python → pip install -e ".[test]" → `pytest -W error::DeprecationWarning` | none |
| `build` | same | Checkout → setup-python → pip install build → `python -m build` | none |
| `deploy` | `push` to main only; `needs: [lint, test, build]` | Checkout → secret-leak grep → curl `${{ secrets.COOLIFY_WEBHOOK_URL }}` | `COOLIFY_WEBHOOK_URL` |

### OpenSpec config contract

After CI-01 lands, `openspec/config.yaml` MUST read:

```yaml
testing:
  has_test_runner: true
  strict_tdd: true
  test_framework: pytest
  test_layers: [unit, integration]
  coverage_tool: pytest-cov
  linter: ruff
  type_checker: none
  formatter: ruff
```

## Testing strategy

This change is infrastructure; it does not produce application logic. The TDD cycle (RED → GREEN → REFACTOR) does not apply to the workflow file itself, but the workflow file is verifiable through its downstream effect.

| Layer | What it tests | Approach |
|-------|---------------|----------|
| **Smoke test** | The CI test job is non-vacuous | `tests/test_smoke.py` with one passing assertion; CI must execute it |
| **Workflow file validity** | The YAML parses and the jobs are reachable | GitHub Actions parses the file on push; a syntax error fails the run before any job starts |
| **Lint self-check** | The CI workflow reports potential hardcoded secrets | A diagnostic grep in CI reports suspicious workflow strings without blocking v1 |
| **Dry-run deploy** | The `deploy` job's commands do not error in a dry-run mode | First merge to `main` after this change lands is a dry-run; success criterion is job exits zero |
| **Downstream TDD readiness** | Future application PRs can land strict-TDD tests | The CI workflow's `pytest -W error::DeprecationWarning` config is documented and matches `docs/architecture/architecture-local_backend-stack.md § Web Strict TDD Policy` |

E2E coverage was originally out of scope for this foundation change. The workflow now has an explicit E2E job/hook, but this change still does not claim completion of the broader E2E ticket set listed under Future work.

## Migration and rollout

No data migration. The change is configuration + documentation. The first production deploy evidence is operator-owned: the `deploy` job fires the Coolify webhook on `main` and either succeeds or fails safely with an explicit configuration error. No LocalBackend deployment call is part of this change.

## Open questions

- [ ] **Operator-controlled secrets**: confirm the operator (not the AI) will populate `COOLIFY_WEBHOOK_URL` and LocalBackend dashboard env vars before the CD PRs land. Documented in PR body but not enforceable by the workflow file.
- [ ] **First deploy target**: the first `deploy` job run will hit Coolify with whatever the operator has configured. If the Coolify app is not yet pointing at this repo, the deploy fails safely (no production state change) but the workflow run is red. Acceptance: operator provisions Coolify app for `apap-web` before merging the CD PRs.
- [ ] **E2E hook timing**: the commented E2E job is added in this change but flipped on by E2E-01. If E2E-01 lands first (shouldn't, since it depends on CI-02), the workflow file needs no change. Documented in `tasks.md` for the E2E ticket owner.
- [ ] **Coverage threshold of 80**: aligns with the architecture doc's "80% of meaningful methods" floor. Will be tuned per-ticket in follow-up changes if specific tickets can't hit it without shallow tests.

## Future work (not in this change)

The following are referenced in the spec and tasks as forward planning only:

- **CD-03** — Staging branch and UAT channel; trigger: Virginia MVC/MVP adoption.
- **ENV-01** — Two Coolify environments; depends on CD-03.
- **CD-04** — UAT-gated production promotion; depends on CD-03 + UAT-01.
- **UAT-01..03** — Interactive UAT page, release-to-ticket traceability, Virginia feedback workflow.
- **E2E-01..06** — Playwright E2E harness and per-domain smoke tests.
- **E2E-M1..M4** — Mobile-viewport E2E coverage.
- **WORKER-01..04** — Background processing infrastructure, triggered by a concrete background need.
