# #902 — Restore Cosmic Ray baseline test collection

## Objective

Make the manual CI mutation job run a non-empty, passing baseline before executing mutants. Issue #902 has `status:approved` and `type:bug`.

## Problem and evidence

The manual `ci.yml` run [36028890804](https://github.com/ardelperal/APAP_WEB/actions/runs/36028890804) failed its unmutated Cosmic Ray baseline with `no tests ran in 0.67s`. `docs/quality/cosmic-ray.toml` names the deleted `tests/test_local_backend.py` and also targets the deleted `app/core/local_backend.py`; the latter is absent from `docs/quality/mutation-baseline.json`. Removing only the stale test argument locally produced 130 passing tests.

## Scope and constraints

- Remove stale configuration paths without adding mutation targets or weakening the fail-closed ratchet.
- Add a regression that detects missing configured target/test paths and empty test collection.
- Keep the fix within #902; security-deep findings belong to #903.
- Strict TDD, source: `docs/proceso.md` §4. Observe RED → GREEN → REFACTOR. Focused runner: `/home/ubuntu/repos/apap-app/.venv/bin/python -m pytest tests/test_ci_workflow.py -q`; full runner: `PYTHON=/home/ubuntu/repos/apap-app/.venv/bin/python make verify`.
- Branch `fix/902-cosmic-ray-baseline`, dedicated sibling worktree. No push, PR, or merge authorization for this branch has been confirmed.

## Acceptance criteria

1. Every configured `module-path` and explicitly named pytest test path exists and aligns with the retained baseline targets.
2. The unmutated command collects and passes more than zero tests on Linux with the pinned dependencies.
3. Empty collection or a failing baseline still fails the mutation job; the survivor ratchet is unchanged.

## Tasks

- [x] **WU-1 — Repair stale mutation configuration and guard it.** Route: delegated direct; mapping and write preparation required 4+ files, and the configuration plus regression test are non-trivial. RED: new config regression failed on the extra deleted target. GREEN: focused regression passed, `tests/test_ci_workflow.py` passed 81/81, and the configured unmutated command passed 130/130. Full `make verify`: 4619 passed, 19 skipped, 1 xfailed; 85.98% coverage; `check_crap: OK`. Work-unit commit `8ed0b4a`.

## Delivery and checks

- Forecast: approximately 100 authored changed lines; strategy `ask-on-risk`, below the 400-line review budget. Running total: 84 authored changed lines in WU-1.
- RDD mode is on (global). The committed work unit assessed high risk for its test subprocess boundary; the four-lens native review was approved and acknowledged under lineage `review-aec2f744fb94cc70`.
- Full hosted Cosmic Ray mutation execution may take several hours; if not run, report it as pending rather than implying a green manual workflow.

## Progress

- 2026-09-24: issue approved; read-only mapping reproduced deleted test path (`pytest` exit 4/no tests) and confirmed a stale mutation target. Regression was red before the config fix and green after it. The unmutated test command passed 130 tests. Full local checks passed as recorded above; the multi-hour mutation session has not been run.
- Engram mirror: current after read-back.

## Next step

Seek separate authorization to push this branch, create the #902 PR, and run hosted `ci.yml`. The multi-hour mutation session remains pending; do not claim a green manual workflow without its result.
