# Local PostgreSQL fallback wiring (#930)

## Objective and boundary

Remove obsolete InsForge environment wiring from the two fallback verifiers and migration E2E seam while preserving bidirectional Access checks and test-schema isolation. Approved issue: https://github.com/ardelperal/APAP_WEB/issues/930. Do not change database schema, synchronization semantics, Git history, storage spike, or route aliases.

## Evidence and approach

- `migration/cli.py` already composes PostgreSQL from `APAP_LOCAL_DB_URL` and `APAP_LOCAL_DB_SCHEMA`.
- The verifier subprocess fixtures still inject `APAP_INSFORGE_*`; the reverse verifier omits the local schema.
- The E2E backend seam passes an obsolete API key as `LocalPostgresExecutor`'s positional `search_path`.
- Route: delegated direct. Mapping needed more than four files; implementation changes multiple non-trivial files.
- A read-only challenge found that a DSN supplied only by `.env` bypassed the ephemeral schema. Both verifier paths must resolve that supported configuration and fail closed when no DSN is available.

## Work unit

- [x] **T1 — Compose both fallback checks from the local PostgreSQL DSN/schema.** Include regression tests for exported and `.env`-only DSNs, current fallback operator guidance, and shrink-only quality baselines. Commit after focused and full checks; record SHA and hosted CI.
- [ ] **T2 — Keep migration E2E on its provisioned PostgreSQL schema.** Remove obsolete credential-based backend selection and its incorrect `LocalPostgresExecutor(url, api_key)` call; test that operator settings cannot redirect the fixture. Commit with its test; record SHA and hosted CI.

## Acceptance and checks

- Neither fallback verifier requires or injects `APAP_INSFORGE_*`.
- E2E seam uses correct DSN and explicit schema search path, never API key as a positional argument.
- Access ↔ web checks and existing data protections remain intact; reverse check receives the same isolated schema.
- Current runbooks no longer tell operators to configure InsForge for fallback checks.
- `make verify`, focused migration tests, build and `verify-fallback-ready` hosted CI pass without relaxed gates.

TDD: **on**, source `docs/proceso.md` §4, runner `.venv/bin/python -m pytest` in the dedicated worktree after `uv sync --frozen --extra dev`. Test type: migration/composition regression tests; any real PostgreSQL-dependent E2E check is reported separately from hermetic local tests. No UI scope.

Delivery: `ask-on-risk`, `stacked-to-main` chosen by the user. Revised forecast ~660 authored changed lines excluding generated files. PR slice 1 targets `main` with T1 verifier behavior, tests, quality baselines and current fallback runbook; its 392-line source diff is below the 400-line gate. PR slice 2 targets updated `main` after PR 1, with T2 E2E behavior/tests and this task document. The task document stays in the local worktree and full Engram mirror until slice 2 because adding it to slice 1 would exceed the gate; no behavior test or operator doc is deferred. RDD mode is on (global preference); native assessment uses each work-unit commit.

## Progress

- Current state: T1 merged via [PR #942](https://github.com/ardelperal/APAP_WEB/pull/942) as merge commit `4a2b560919f9e19a209b6b15bcb6d351e360462c`; its work-unit commit was `1fe84d6dc0518048a3357624e26e57bf77b874cd` (392 authored lines). T2 is implemented on `fix/930-migration-e2e-seam` from that merge; hosted CI and merge remain pending.
- TDD: four expected RED cases for obsolete env/constructor behavior, two more for `.env`-only DSN isolation, and one for active production-executor construction. Focused tests GREEN; PostgreSQL E2E requires `APAP_TEST_POSTGRES_DSN` and is skipped locally.
- T2 local checks: `uv sync --frozen --extra dev`; `.venv/bin/python -m pytest -q tests/migration/test_e2e_legacy_postgres.py tests/migration/test_round_trip.py tests/migration/test_cli.py` (21 passed, 3 skipped); `make verify PYTHON=.venv/bin/python` (4,649 passed, 19 skipped, 1 xfailed, 1 warning); `.venv/bin/python -m build --wheel --sdist` (wheel and sdist built); Ruff, diff check, branch-name and 400-line size gates passed. The three real-PostgreSQL E2E atoms were skipped because `APAP_TEST_POSTGRES_DSN` is unset. Hosted CI and merge remain pending. Rollback boundary: T2's two test-seam files and this task document.
- T2 work-unit commit: `b62560fb69aadd8157954dd4e75e4ef7afd8ceda` (`fix(migration): isolate E2E backend on test PostgreSQL`). The follow-up task-document commit records this identity; no hosted authority is claimed yet.
- Slice 1 checks: `uv sync --frozen --extra dev`, 52 focused tests, `make verify PYTHON=.venv/bin/python` (4,647 passed, 19 skipped, 1 xfailed, 1 warning), wheel/sdist build and hosted [`ci.yml` run 36053513889](https://github.com/ardelperal/APAP_WEB/actions/runs/36053513889) passed. CI exercised `verify-fallback-ready` with PostgreSQL; full E2E is skipped for PR events. The separately cancelled `pr-size` workflow passed on rerun. Rollback boundary: T1's seven changed files only. Native RDD risk `high`; the user authorized this exact candidate and all four lenses returned approved, acknowledged under lineage `review-017118edd47debf5`. One informational finding did not open a correction.
- Next step: commit T2, deliver PR slice 2 against current `main`, run hosted CI, then close T2 and issue #930 only after green gates and merge.
