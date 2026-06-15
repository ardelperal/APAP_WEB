# Development workflow

This guide walks a new developer from a fresh clone to a green test run on the APAP web application. It is the canonical reference for the local commands. The CI workflow (delivered in a follow-up PR) and the deploy job (delivered later still) call the same commands, so what works locally is what works on `main`.

For per-developer environment setup and the InsForge MCP credentials, see [`docs/setup.md`](setup.md). For the architectural decisions that shape this workflow, see [`docs/architecture-insforge-stack.md`](../docs/architecture-insforge-stack.md).

## Prerequisites

| Tool | Minimum version | Why |
|------|----------------|-----|
| Python | 3.11 | Pinned in `pyproject.toml` (`requires-python = ">=3.11"`). Matches the architecture doc and FastAPI 0.136.x. |
| pip | 23.0+ | Modern resolver; required for editable installs and `[dev]` extras. |
| Git | 2.30+ | For working with feature branches and the pre-MVC `main`-only flow described below. |
| GNU Make | any recent | Optional but recommended. The `Makefile` is the convenience entry point; the canonical commands also work directly. |
| Node.js | 18+ | Only needed for Tailwind CSS compilation once the web-app-skeleton PR lands. Not required for PR 1. |
| InsForge account | free tier | For the InsForge MCP integration. See `docs/setup.md`. |

Windows users can run the same commands in PowerShell. The cross-platform equivalents are listed under each step. macOS and Linux users can use the `make` shortcuts verbatim.

## Step 1 — Clone the repository

```bash
git clone <repo-url>
cd APAP_WEB
```

PowerShell:

```powershell
git clone <repo-url>
Set-Location APAP_WEB
```

## Step 2 — Create a virtual environment and install dev dependencies

A virtual environment keeps APAP dependencies isolated from system Python.

```bash
python3 -m venv .venv
source .venv/bin/activate            # POSIX
# .venv\Scripts\Activate.ps1         # PowerShell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The `-e ".[dev]"` line installs:

- The local project in editable mode (so `import apap_web` works once that package exists).
- The `[dev]` extras: `build`, `pytest`, `pytest-cov`, and `ruff`.

If you do not have `make` and prefer a one-liner, `python -m pip install -e ".[dev]"` is the only install step required.

## Step 3 — Configure the InsForge MCP (one-time, per developer)

The repository excludes the real `opencode.json` from git because it holds the per-developer InsForge API key. Follow [`docs/setup.md`](setup.md#2-configure-the-insforge-mcp) to copy `opencode.json.example` to `opencode.json` and fill in your own credentials. The smoke test in `tests/test_smoke.py` does not require the MCP, but the future application code (PR: web-app-skeleton) will.

## Step 4 — Run the test suite

The canonical test command is `pytest`, with the deprecation-strictness flags baked into `pyproject.toml`.

```bash
pytest
```

Via the Makefile:

```bash
make test
```

PowerShell:

```powershell
python -m pytest
```

### Expected output for a green run

```text
============================= test session starts ==============================
platform linux -- Python 3.11.x, pytest-8.x.x, pluggy-1.x.x
rootdir: <repo-root>
configfile: pyproject.toml
tests/test_smoke.py::test_smoke_passes PASSED                            [100%]
============================== 1 passed in 0.0xs ===============================
```

A single `PASSED` line is the current expected output. As the application code lands, more tests will appear and the count will grow.

### What "green" means here

- The smoke test in `tests/test_smoke.py` passes.
- pytest exits 0.
- No `DeprecationWarning` is printed (because `pyproject.toml` promotes them to errors and the smoke test uses no deprecated APIs).

A non-green run is a `make test` failure that must be fixed before opening a PR.

## Step 5 — Run the linter

The canonical lint command is `ruff check .`, run on the whole repository.

```bash
ruff check .
```

Via the Makefile:

```bash
make lint
```

PowerShell:

```powershell
python -m ruff check .
```

### Expected output for a clean tree

```text
All checks passed!
```

If ruff reports violations, fix them in the file/line indicated. The rule selection (`E`, `F`, `W`, `I`, `UP`, `B`) is documented in `pyproject.toml` § `[tool.ruff.lint]`. The CI workflow will run the same command and fail the build on any violation.

## Step 6 — Build the package

The canonical build command is `python -m build`, which produces a wheel and an sdist in `dist/`.

```bash
python -m build
```

Via the Makefile:

```bash
make build
```

PowerShell:

```powershell
python -m build
```

### Expected output for a green build

```text
* Creating sdist...
* Creating wheel...
Successfully built apap_web-0.1.0.tar.gz and apap_web-0.1.0-py3-none-any.whl
```

The `dist/` directory is gitignored (added by PR 1, task 0.5). It is safe to delete between builds; the `make clean` target removes it along with the cache directories.

## Step 7 — Run the green-PR gate

`make all` is the single command that mirrors the future CI check on a pull request: it runs `make test` and `make lint` in sequence.

```bash
make all
```

A green run is the local signal that the PR is ready for review.

## CI workflow and future E2E hook

The GitHub Actions workflow runs the same local commands on pull requests to `main` and on pushes to `main`:

| Job | Command | Purpose |
|-----|---------|---------|
| `ci / lint` | `ruff check .` | Static linting and import-order checks. |
| `ci / test` | `python -m pytest -W error::DeprecationWarning` | Unit/integration tests with deprecations promoted to errors. |
| `ci / build` | `python -m build` | Package build validation. |

The workflow also includes a disabled `e2e` placeholder with `TODO(E2E-01): enable when Playwright harness lands`. Do not enable it in this CI/CD foundation slice; the Playwright harness is delivered by the separate E2E-01 change.

## Pre-staging branch note

While APAP-WEB is pre-MVC, every implementation PR targets `main` and every merge to `main` triggers a continuous deployment through Coolify (FastAPI/HTMX app) and InsForge (BFF/data layer). There is no `staging` branch and no UAT gate yet.

The transition to a `staging` branch + UAT channel is captured as **CD-03** in the `ci-cd-foundation` SDD change (`openspec/changes/ci-cd-foundation/`). Implementation of CD-03 is **deferred** until Virginia adopts the MVC/MVP in production. Until that trigger fires:

- All PRs target `main`.
- The `deploy` job runs on every push to `main` after CI passes.
- There is no pre-production validation step; the first production-grade safety net is the CI quality gate (lint, unit, integration, build) and the operator-side code review.

The `openspec/changes/ci-cd-foundation/design.md § Future work` section lists every ticket deferred to the staging transition (CD-03, CD-04, ENV-01, UAT-01..03, E2E-01..06, E2E-M1..M4, WORKER-01..04). When the trigger fires, those ticket seeds become the next SDD change.

## Where to look next

- [`docs/setup.md`](setup.md) — one-time per-developer environment setup and InsForge MCP credentials.
- [`docs/architecture-insforge-stack.md`](../docs/architecture-insforge-stack.md) — the stack decisions, dependency policy, and CI/CD and testing policies that this workflow implements.
- [`openspec/changes/ci-cd-foundation/`](../openspec/changes/ci-cd-foundation/) — the SDD change that plans the full delivery pipeline (PR 1 = this surface; PR 2 = CI workflow; PR 3 = CD pipeline).
- `pyproject.toml` — the canonical configuration for pytest (deprecation strictness) and ruff (lint rules). The architecture doc's quality gate is encoded here.
- `Makefile` — the convenience targets documented above.
