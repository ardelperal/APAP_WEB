# Animal creation wizard (#823)

## Objective and scope

Adopt the existing stepper for `/animales/new` without changing the animal form payload, server validation, or edit flow. The shared template must remain a single-page form for edits. Group the 21 rendered editable controls by their real meanings; do not add fields merely to match the historical issue count.

Authorized by the approved UI Phase C request and the user's decision to adapt to live fields and preserve backend behavior. The exact #823 issue body is not available locally; `docs/forms/stepper-policy.md` and the current code are the verified local constraints. No backend, schema, or unrelated form changes are in scope.

## Constraints and delivery

- Branch/worktree: `feat/823-animal-create-wizard` in the sibling `823-animal-create-wizard` worktree, based on local `origin/main` at `2dc98dd`.
- TDD: on, from `docs/architecture/decisiones/d-33-tdd-estricto.md`. Observe RED, GREEN, REFACTOR. Runner: `pytest -W error::DeprecationWarning`; UI behavior also requires Playwright E2E.
- Review forecast: 350–500 authored changed lines, excluding generated files. Strategy: `ask-on-risk`, resolved to `stacked-to-main` by the user on 2026-09-25. T1 is the controller/testing slice; T2 is the dependent animal-form adoption slice. Each PR targets `main` when its predecessor has landed. Do not shrink tests or readable code to meet a number.
- Remote push, PR, and merge are outside this local implementation until their authorization and live gates are verified.

## Tasks

- [x] **T1 — Stepper validation contract.** Add regression tests for proactive Next state and final whole-form validation, observe RED, then harden the shared controller without changing other form behavior. Route: delegated direct; mapping and preparation span 4+ files and the implementation/test pair is non-trivial. Checks: three browser regressions observed RED→GREEN; focused suite 3 passed/5 skipped; `make verify` passed 4717/19 skipped/1 xfailed, 87.09% coverage; `node --check`, Ruff, and diff whitespace passed. Work-unit commit `0686cc5abfeab1082bb76ae78137d1bffb3c9812` (167 authored lines), rollback: JS controller and its component browser tests. RDD assessed medium, `under_budget`, so no native review due yet.
- [ ] **T2 — Animal create-only adoption.** Add browser tests for create wizard navigation, validation, successful submit, and edit-form parity; observe RED; then group the real controls and add responsive sidebar styling. Route: delegated direct; template, CSS, and E2E are non-trivial. Checks: focused Playwright desktop/mobile, axe-core on every step if available, relevant pytest suite, no payload/POST changes.

## Acceptance and progress

Acceptance: create uses a navigable, keyboard-usable stepper over the existing rendered controls; Next cannot skip required fields; final submit can surface errors in earlier steps; edit remains unchanged; server contract stays intact. Browser audit and accessibility checks must be reported honestly if unavailable.

Progress: T1 complete at `0686cc5`. Root checkout untouched. The focused command `PYTHONPATH=. /home/ubuntu/repos/apap-app/.venv/bin/python -m pytest -W error::DeprecationWarning tests/e2e/test_stepper_component.py -q` returned 3 passed, 5 skipped because `APAP_E2E_AUTH_SECRET` is unset. `make verify` passed: 4717 passed, 19 skipped, 1 xfailed, 1 warning, 87.09% coverage. Local `origin/main` advanced by two commits after branching; rebase/integration against fresh main and hosted CI remain pending. T2 not started.

Next: prepare the independent T1 main-targeted PR only when remote authorization/credentials and current-main CI gates are available. Implement T2 on a dependent local branch, then retarget its PR to `main` after T1 lands; keep the T2 PR unopened until its main-only diff is clean.
