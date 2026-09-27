# Feature: UI-824 — stepper on /entradas/batch/new (live fixed-rows flow)

Issue: ardelperal/APAP_WEB#824 · Branch: `feat/824-stepper-batch-new`
Worktree: `/home/ubuntu/repos/apap-app-worktrees/824-stepper-batch` (from origin/main 1c916bb)

## Contracts (binding)

- Decision #4122 (Engram `ui/phase-c-spec-resolution`): adapt to the LIVE flow. The issue's "31 dynamic fields / 4 steps / dynamic rows / inline preview" language is historical. The live form has 5 FIXED rows × 6 fields (animal_id, fecha_entrada required; voluntario_entrada_id, origen, motivo, observaciones optional) and a separate stage → preview → commit flow. Do NOT add dynamic rows, do NOT move preview into the form.
- Live flow (app/modules/entradas/batch_routes.py): POST /entradas/batch stages and redirects to preview; BatchValidationError and empty-batch re-render batch_new.html with preserved rows + `error` context (422).
- Wizard gate: `{% if not error %}` — error rerenders keep today's flat layout (same contract as #823 / issue #974 rationale). This form has no edit variant.
- Stepper component state on main: form-stepper.js (validated, proactive Next-disable + whole-form recheck, #984), CSS layers (#821 + sidebar utilities #993). Reuse; do not rewrite.
- Rows share name/id attributes across rows (list-form fields). Step validation selectors must be scoped per panel: e.g. `[data-step-panel="1"] input[name="animal_id"]` (the JS validates ALL matches, not just the first).

## Step grouping (live fields, 3 steps)

1. **Identificación por fila** (required): animal_id, fecha_entrada × 5 rows
2. **Contexto por fila** (optional): voluntario_entrada_id, origen, motivo, observaciones × 5 rows
3. **Revisión y previsualización**: static summary + nav; submit keeps label "Previsualizar lote" and POST target /entradas/batch — the stage→preview→commit flow is untouched.

## Tasks

- [x] T1 (slice 1) Restructure `app/templates/entradas/batch_new.html`: wrap row fields into 3 `<fieldset data-step-panel>` groups (rows stay whole fieldsets per row inside each panel, columns per step), stepper list + nav, `data-stepper="true"`, `data-step-validate` with panel-scoped required selectors for step 1, script include with defer, gated on `{% if not error %}`; error branch renders today's flat markup byte-equivalent.
- [x] T2 (slice 1) E2E test `tests/e2e/test_entradas_batch_stepper.py`: render 3 steps (production-template render technique from test_animales_new_stepper.py), required gate blocks advance per row, data preserved across steps, submit POSTs to /entradas/batch with csrf + all row fields; error rerender has no stepper (if expressible without inventing routes — else covered by gate comment).
- [ ] T3 (slice 1) Work-unit commit + PR (template + tests, ≤400 lines or honest size:exception with reason). Diff is 904 lines (`822 insertions + 82 deletions` across 3 files — template +190 net, tests +599, doc +33) — pre-authorized `size:exception` per T3 plan ("≤400 lines or honest size:exception with reason"); reason: the wizard structurally multiplies the form (5 rows × 3 panels ≈ 3× the input markup) and the test suite covers 5 distinct contract pins (markup, error branch, required gate, data preservation, live POST) per project conventions (siblings `test_animales_new_stepper.py` is 483 lines for 9 tests, `test_entradas_batch.py` is 517 lines for 6 tests).
- [ ] T4 Post-merge: verify CI e2e green; update this doc; close loop in Engram.

## Evidence

- Empty-row decision (resolved from route evidence, NOT from issue wording): the route's `_form_data_to_params` + `if any(r.values())` filter (`batch_routes.py:124-126`) discards rows where ALL 6 fields are blank; `BatchValidationError` only fires for cross-batch `(animal_id, fecha_entrada)` duplicates (`batch_service._check_cross_batch_uniqueness:158-167`); per-record required-field failures are surfaced as `BatchRecord(status="invalid")` in the preview without aborting the batch (`batch_service.stage_batch:181-189`). The live HTML `required` attribute on `animal_id`/`fecha_entrada` therefore blocked "leave a row empty to discard" BEFORE the wizard — the wizard's `data-step-validate` selector `[data-step-panel='1'] input[name='animal_id'], [data-step-panel='1'] input[name='fecha_entrada']` mirrors that pre-existing HTML5 constraint. Closing the gap (allow empty rows through the wizard) was rejected as scope creep: it would change the create-form contract beyond the wizard's mandate.
- Render smoke (both branches reachable, Jinja parse OK): `tests/e2e/test_entradas_batch_stepper.py::test_render_three_steps` PASSED (create branch: 3 panels, row distribution per step, submit hidden with "Previsualizar lote" label, form-stepper.js loads); `test_error_branch_renders_flat` PASSED (422 branch: byte-equivalent flat form, no stepper markup, error banner with operator message).
- Error-branch byte-equivalence: form markup of the `{% else %}` branch matches the original flat layout character-for-character modulo indentation (verified by normalizing whitespace in the rendered HTML).
- Work-unit commit: appended when T3 closes.

## Non-goals

- No backend/route/schema changes; no dynamic rows; preview/commit/cancel pages untouched; #823 patterns reused as-is.
