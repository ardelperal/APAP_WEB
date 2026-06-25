# Archive Report: ui-apap-design-system

## Status

Archived with warnings on 2026-06-25.

## Scope archived

The change applied the real APAP Alcalá visual tokens to the FastAPI/Jinja2 + Tailwind UI and added Playwright E2E coverage for the public landing/brand behavior.

Source of truth for visual tokens:

- `docs/design-tokens-apap-actual.md`
- `tailwindcss/styles/app.css`
- `app/static/css/output.css`

OpenSpec active artifacts found before archive:

- `proposal.md` ✅
- `tasks.md` ✅
- `archive-report.md` ✅ (created during archive)
- `specs/` ⚠️ not present in this historical change; no delta spec to merge
- `design.md` ⚠️ not present in this historical change
- `verify-report.md` ⚠️ not present as a standalone file; verification evidence is recorded in `tasks.md`, PR #108, commit messages, and Engram observations

## Task completion gate

`tasks.md` had stale unchecked PR-mechanics checkboxes (`T11.3`, `T13.1`-`T13.4`) even though the implementation was already merged into `staging`. The archive launch explicitly asked to verify and document whether those historical branch/push/PR mechanics were stale, satisfied/N/A, or blockers.

Archive-time reconciliation marked them complete because current evidence proves they are satisfied:

- PR #108 is `MERGED` into `staging` with merge commit `ec99037ecb7bc4e0703781a0377bbbf344fdb97d`.
- `git merge-base --is-ancestor ec99037 staging` returned success.
- Documentation reconciliation commit `ce190583a862daaf6f141fc5eb819ea3877d3ae9` is also reachable from `staging`.
- `gh pr view 108` reports `baseRefName: staging`, `headRefName: feat/ui-apap-design-system`, `mergedAt: 2026-06-23T18:58:42Z`.

The archived `tasks.md` now has no unchecked task items.

## Implementation commits

| Commit | Work unit | SDD tasks | Verification | Access sync |
|---|---|---|---|---|
| `60f6c8728e02432a950bc8349479723746e2bc86` | Add APAP design tokens to Tailwind v4 theme | T1 | CSS build in PR #108 | N/A |
| `597691af372a99c24b4dbb68d9ec980e2e65910c` | Repaint base chrome, landing, admin, unauthorized | T2-T5 | Template preservation + PR #108 verification | N/A |
| `806b56598ae2b0bfeb103c3b44332610b6e129e6` | Repaint animales templates | T6-T8 | Template preservation + PR #108 verification | N/A |
| `e58686709432ec37fd4b21891a544b547483f3cd` | Repaint voluntarios templates and finalize change | T9-T13 | PR #108 verification notes | N/A |
| `f4c441b9f9fe4d93630f1be0a82cacf326202fe4` | Replace showcase palette with real APAP Alcalá tokens | T1, T11 | Playwright visual verification recorded in commit body | N/A |
| `7f4c64ce53d0ab17457d72a796c497cc80336397` | Add Playwright E2E tests for APAP brand palette | T12 | `tests/e2e/test_landing.py` | N/A |
| `aac464ef2fe474577502233df52d1fb95ef9b3c2` | Tighten E2E assertions and path normalization after review | T12/T13 review follow-up | E2E assertion hardening | N/A |
| `ec99037ecb7bc4e0703781a0377bbbf344fdb97d` | Merge PR #108 into staging | T1-T13 | PR #108 merged to `staging` | N/A |
| `ce190583a862daaf6f141fc5eb819ea3877d3ae9` | Reconcile APAP palette source of truth in active OpenSpec | Archive precondition | OpenSpec artifact reconciliation | N/A |

## Verification evidence

Archive verification on 2026-06-25:

- Current branch: `staging`.
- Working tree was clean before archive operations.
- `git merge-base --is-ancestor ec99037 staging` ✅
- `git merge-base --is-ancestor ce19058 staging` ✅
- `python -m pytest -q` ✅ — 421 passed / 2 skipped.
- `python -m ruff check .` ✅ — all checks passed.
- `python -m build` ✅ — sdist and wheel built successfully.
- Tailwind CLI build ✅ — `npx tailwindcss -i ./styles/app.css -o ../app/static/css/output.css --minify`; rebuilt CSS was restored to avoid line-ending-only working-tree noise.
- Direct `pytest tests/e2e/test_landing.py` was not runnable in this local venv because `playwright` is not installed, but PR #108 added the E2E test suite and its commit evidence documents the browser-level checks.

## Spec sync

No `openspec/changes/ui-apap-design-system/specs/` directory exists, so there was no delta spec to promote into `openspec/specs/`. Existing main specs were left untouched.

## Engram traceability

Related observations consulted:

- #14301 — `sdd/ui-apap-design-system/apply-progress`
- #14305 — `Approved APAP palette reconciliation review`
- #14307 — `Reconciled UI SDD to real APAP palette`

Exact SDD artifact observations (`sdd/ui-apap-design-system/proposal`, `spec`, `design`, `tasks`, `verify-report`) were searched and not found; this archive report is persisted as `sdd/ui-apap-design-system/archive-report`.

## Risks / warnings

- This was a historical proposal/tasks-only change. Missing standalone `spec`, `design`, and `verify-report` files are recorded rather than invented.
- Local direct E2E execution requires installing the dev dependency `playwright` and Chromium (`playwright install chromium`).
- Protected-page screenshots remain limited without local OAuth/InsForge credentials; the committed E2E suite pins public brand behavior and auth redirects.
