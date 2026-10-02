# fix-1038-tareas-codeql-triage

Issue: #1038 — triage of the 5 CodeQL alerts on `app/modules/tasks/routes.py`
(2 reflected-XSS high, URL-redirection medium series). Refs #911, #1034, #934.

## Context

- Redirect handlers (`asignar_tarea`, `cerrar_tarea`) interpolate the raw
  `tarea_id` path param into `RedirectResponse(url=f"/tareas/{tarea_id}")`.
  `tarea_id` is a Postgres UUID semantically; an unvalidated string with `?`
  or `#` builds a manipulable redirect target.
- XSS alerts flow `filter_estado` / `tarea` fields into `TemplateResponse`.
  Starlette `Jinja2Templates` enables autoescape by default — expected false
  positive, but the issue demands a pinned, documented disposition.

## Tasks

1. [x] Explore issue + CodeQL alerts + routes/service/queries + templates.
2. [x] Worktree `apap-app-worktrees/1038-tareas-codeql` + branch
       `fix/1038-tareas-codeql-triage` off current `main`.
3. [x] TDD RED: tests pinning (a) non-UUID `tarea_id` in POST redirect routes
       redirects to `/tareas` (never interpolates), (b) valid UUID redirects to
       `/tareas/<uuid>`, (c) the tareas `_templates` env has autoescape enabled.
4. [x] TDD GREEN: UUID validation guard for redirect targets in routes.py.
5. [x] Disposition doc: per-alert fix/FP justification (docs per repo audit
       convention; check_where #934 precedent lives).
6. [x] Local gates: ruff, mypy, check_rules, module/route size, pytest focused
       + full suite (minus Postgres-only deselects).
7. [x] Work-unit commit(s), push, PR with `Closes #1038` (no merge).

## Constraints

- Strict TDD (RED → GREEN → REFACTOR). English technical artifacts.
- No AGENTS.md edits. Budget ~80-150 lines per issue estimate.
- Branch protection rejects direct main pushes; everything via PR.
- Conventional commits, no AI attribution.

## Evidence log

- (append commit SHAs + gate results here as tasks close)

## Evidence (closed 2026-09-27)

- Commits: 92ca08b (fix + tests), 7f478be (docs) on fix/1038-tareas-codeql-triage
- PR: https://github.com/ardelperal/APAP_WEB/pull/1050 (Closes #1038) — open, NOT merged
- Gates: ruff PASS, mypy PASS (314 files), check_rules PASS, module/route size PASS,
  pr_size 258<=400, full suite 4947 passed / 19 skipped, coverage 89.60%
- Delegation: gentle-ai-worker (TDD RED->GREEN) + gentle-ai-verify (independent gates)
