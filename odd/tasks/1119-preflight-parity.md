# #1119 — Canonical preflight command with local-CI parity

## Goal

Comando canónico local (`scripts/preflight.py`) que ejecuta EXACTAMENTE el job `lint` de `.github/workflows/ci.yml` con paridad verificada por test. Cierra la brecha Local-vs-CI (PR #1111, run 36592991754, TRY003 188>186 invisible con `ruff check` a solas).

## Acceptance criteria

1. `scripts/preflight.py` corre cada step con `run:` del job `lint` en orden, exit code agregado (0 verde, 1 rojo).
2. Salida `PASS <name>` o `FAIL <name>` con step ofensor.
3. `tests/test_preflight.py::test_preflight_runs_exactly_lint_job_run_steps` anti-drift: set preflight == set del job parseado independientemente.
4. Preflight en worktree limpio → exit 0.
5. Preflight en scratch con violación → exit !=0 y nombre del step.
6. `CONTRIBUTING.md` nombra `scripts/preflight.py` como validación pre-push.
7. `ruff check` + `mypy` limpios en archivos nuevos.

## Scope

`chore/1119-preflight-parity` desde `origin/main` (`cec3133`). Archivos: `scripts/preflight.py`, `tests/test_preflight.py`, `CONTRIBUTING.md`.

## Out of scope

No tocar rulesets/baselines, no editar `ci.yml`, no incluir `typecheck`/`test` (issue los deja fuera). `make verify` se conserva.

## Anti-drift design

`test_preflight_runs_exactly_lint_job_run_steps` parsea ci.yml dos veces (PyYAML directo vs `preflight.lint_steps_from_ci`) y exige `set_a == set_b` sobre `(name, run)` del job `lint`. Step nuevo en ci.yml → recogido; hardcode/drop en preflight.py → detectado.

## Plan de validación

1. RED: tests en test_preflight.py.
2. GREEN: scripts/preflight.py.
3. Verificar ruff + mypy.
4. Smoke worktree limpio + scratch con violación.
5. Self-review code-review-expert.

## Riesgos

- **R1**: glob `openspec/changes/*/specs/` — preflight usa `bash -c` idéntico al runner.
- **R2**: YAML malformado rompe preflight → fail-fast.
- **R3**: preflight corre 19 steps (vulture/jscpd lentos) — documentado en CONTRIBUTING.
- **R4**: drift CONTRIBUTING↔preflight — mitigado por test anti-drift sobre comportamiento.

Independiente.
## Resumption (2026-09-30) — adopted by the coordinating session
The work above was abandoned uncommitted at 17:10 on 2026-09-29 (no commits, no PR, no live process). Design adopted as is (read ci.yml at run time, run the `lint` job `run:` steps). Base was cec3133; origin/main is well ahead. Issue #1119 was reformatted (### headings + acceptance section) so `issue-spec` accepts the PR. Single PR, `Closes #1119`.

### Gaps found on review (to fix)
1. `raise SystemExit("message")` exits with code 1, but the documented contract is exit 2 for a missing/malformed workflow: make it real and test it.
2. Shell parity: GitHub runs a `run:` step with `bash -e {0}` (no `defaults.run.shell` in ci.yml); the script uses `bash -c`. Mirror `-e` so multi-line steps abort at the first failing command like CI.
3. The "anti-drift" test parses ci.yml twice from the same source, so it can never fail. Replace it with behaviour tests: a temp workflow gets an extra lint step and it IS executed; a failing step is named and the remaining steps still run; missing lint job / malformed YAML exit 2; steps containing `${{` expressions are refused loudly (bash cannot evaluate them).
4. CONTRIBUTING hardcodes "19 steps": remove the number (it drifts).
5. My own hand-made list of lint steps today had 16 of 19 (missing ruff, check_rules, docstring_balance): the real-world check must run the whole preflight.
6. Keep the ruff ratchet clean (TRY003 message in a variable, no new noqa if avoidable).

### Tasks
- [x] T1 commit the adopted work; merge origin/main.
- [x] T2 RED/GREEN for gaps 1-4 and 6.
- [x] T3 real-world: preflight on the clean tree (PASS, report duration) and with an induced violation (an upper-case word outside the acronym whitelist in a docs file must FAIL naming check_alantyle, exit 1).
- [x] T4 full suite; preflight itself is the lint run.
- [ ] T5 parent: review, push, PR.

### Evidence (2026-09-30, writer lane)
- Commits: 082c8ea adoption; 1ebdee4 merge of origin/main; 74ecc40 fixes.
- RED: 5 of 11 new tests failed before the fix (--list, exit 2 cases, bash -e, expression refusal); GREEN: 11 passed, 2 opt-in smokes skipped.
- Real world: clean tree PASSED 19/19 in 27 s, exit 0. Induced `BOTH` in docs/CODEBASE-GUIDE.md: FAIL alan-style step, 1/19 failed, 18 others still ran, exit 1 (file reverted). `--workflow /nonexistent.yml`: exit 2.
- Found by the full suite: tests/test_gate_output_encoding.py required the UTF-8 output pin; added `_pin_output_encoding`. Full suite: 5232 passed, 21 skipped.
- PR diff vs origin/main: 446 added lines over 3 files (above the 400 heuristic; the adopted work was ~370 and the behaviour tests replace a tautology).
- Pending T5 (parent): review, push, PR.

## Outcome (2026-09-30)
Merged as PR #1145 (merge commit 52fd1c5f); PR #1144 was closed and replaced by #1145 while trying to make GitHub register the closing link. Issue #1119 was closed by hand: GitHub never registered `Closes #1119` (closingIssuesReferences empty, willCloseTarget false) so the PR carried `chain:partial` as a declared exemption (friction B11 in epic #935). Native review approved after one correction (bash that cannot start now exits 2 instead of a traceback). Follow-ups left by the review: a lint job with zero steps prints PASSED (0/0 steps); steps with working-directory/env/shell/if are ignored silently; no per-step timeout; unnamed steps collide in the output; the real-tree smoke tests are opt-in. Canonical preflight from `main`: `uv run python scripts/preflight.py` (19/19 steps, ~30 s). The `PASSED (0/0 steps)` false-green is tracked as a known follow-up in the native-review followups issue (to be created).
