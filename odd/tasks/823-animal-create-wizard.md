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

- [ ] **T1 — Stepper validation contract.** Add regression tests for proactive Next state and final whole-form validation, observe RED, then harden the shared controller without changing other form behavior. Route: delegated direct; mapping and preparation span 4+ files and the implementation/test pair is non-trivial. Checks: focused stepper tests, exact RED/GREEN evidence, existing stepper behavior preserved.
- [ ] **T2 — Animal create-only adoption.** Add browser tests for create wizard navigation, validation, successful submit, and edit-form parity; observe RED; then group the real controls and add responsive sidebar styling. Route: delegated direct; template, CSS, and E2E are non-trivial. Checks: focused Playwright desktop/mobile, axe-core on every step if available, relevant pytest suite, no payload/POST changes.

## Acceptance and progress

Acceptance: create uses a navigable, keyboard-usable stepper over the existing rendered controls; Next cannot skip required fields; final submit can surface errors in earlier steps; edit remains unchanged; server contract stays intact. Browser audit and accessibility checks must be reported honestly if unavailable.

Progress: exploration complete. Fresh-runtime sibling write probe passed. Root checkout was not changed. T1 test-first work has three observed browser RED→GREEN regressions: proactive Next state, hidden earlier-step error focus, and preservation of native constraints for controls absent from custom rules. The focused command `PYTHONPATH=. /home/ubuntu/repos/apap-app/.venv/bin/python -m pytest -W error::DeprecationWarning tests/e2e/test_stepper_component.py -q` returned 3 passed, 5 skipped; the skips require `APAP_E2E_AUTH_SECRET`. `node --check`, Ruff, and `git diff --check` passed. T1 remains open until its work-unit commit. Prospective RDD mode is on; assessment of the untracked task document alone was passive, not an assessment of the implementation. No commit or full-suite check yet.

Next: commit T1 and run the committed-only RDD assessment. Proceed to T2 after T1 is closed, keeping its PR independent against `main` after the T1 slice lands.
