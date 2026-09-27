# Form action on validation-error rerender (#974)

## Objective and boundary

Make `_render_animal_form_error` preserve the originating flow's
`form_action` so the rerendered form posts back to the handler that
produced the error. Without this, a corrected resubmit after an edit
validation failure posts to the create endpoint and can duplicate the
animal. Approved issue: https://github.com/ardelperal/APAP_WEB/issues/974.
Do not change the template wizard gate, the `AnimalForm` contract, or
the route signatures.

## Evidence and approach

- `app/modules/animals/routes.py` — `_render_animal_form_error` hardcoded
  `form_action = "/animales"` for both flows; the GET edit route already
  used `f"/animales/{animal_id}/update"`, so only the error rerender lost
  the value. Three call sites: `create_animal_view` × 2 (ValueError,
  UniqueViolationError) and `update_animal_view` × 1 (ValueError).
- Smallest reversible change: add a keyword-only `form_action: str = "/animales"`
  parameter to the helper. Default preserves the legacy create-branch
  behavior so the two create call sites stay untouched. The update call
  site MUST pass `f"/animales/{animal_id}/update"`.
- The wizard gate in `app/templates/animales/form.html`
  (`form_action == '/animales' and not error`) stays as-is. After the
  fix the edit-error rerender keeps `form_action != '/animales'` AND
  `error` truthy, so the gate stays false and the wizard stays off.

## Work unit

- [x] **T1 — RED: two route tests pin the rerender contract.**
  `test_create_error_rerender_keeps_create_action` and
  `test_update_error_rerender_keeps_update_action`. The second one is
  the regression test for the duplicate-animal bug; it captured
  `form_action == "/animales"` on the buggy code (matches the reported
  symptom).
- [x] **T2 — GREEN: keyword-only `form_action` parameter on the helper
  with default `"/animales"`; update call site passes the explicit
  `/animales/{animal_id}/update`.**
- [x] **T3 — TRIANGULATE: reran the full animals routes suite, the
  redirects suite, all `tests/test_animals_*.py`, the XSS audit, and
  the sibling route suites that exercise `form_action` handling
  (`test_acogidas_routes`, `test_foster_routes`,
  `test_materiales_routes`). 1,018 tests green; no regressions.**

## Acceptance and checks

- Create-error rerender keeps `action="/animales"`. ✓ (pinned by
  `test_create_error_rerender_keeps_create_action`).
- Edit-error rerender keeps `action="/animales/{animal_id}/update"` with
  the same `animal_id` from the request. ✓ (pinned by
  `test_update_error_rerender_keeps_update_action`).
- Resubmitting after an edit validation failure updates the existing
  animal; no duplicates. ✓ (same test confirms the rerender posts back
  to `/animales/abc-123/update`, which the existing update route
  delegates to the port).
- Test that asserts the `action` of the rerendered form on both error
  flows. ✓ (the two new route tests above).

TDD: **on**, source `docs/proceso.md` §4, runner
`/home/ubuntu/repos/apap-app/.venv/bin/python -m pytest` from the
dedicated worktree. Test type: route integration in-process
(`httpx.ASGITransport` + `_templates.TemplateResponse` capture) per
the apap-testing-strategy §3 table — no FK or trigger surface in this
fix, so no `tests/integration/` companion is required. No UI scope.

## What

- `app/modules/animals/routes.py`: added keyword-only `form_action`
  parameter to `_render_animal_form_error` (default `"/animales"`,
  preserves legacy create-branch behavior); the update call site
  passes `f"/animales/{animal_id}/update"`. Expanded the helper
  docstring to cite #974 and explain the default.
- `tests/test_animals_routes.py`: two new route tests pin the rerender
  contract for both flows.

## Evidence

- RED: before the fix, `test_update_error_rerender_keeps_update_action`
  captured `form_action == "/animales"` (the bug); the create test
  passed because the helper's hardcoded value happens to be the
  correct create branch value (coincidental correctness is still a
  pinned contract after the fix).
- GREEN: both tests pass after the fix; full `tests/test_animals_routes.py`
  (25 passed), full `tests/test_animals_routes_redirects.py` plus the
  rest of the animals test tree plus the XSS audit and the sibling
  route suites (1,018 passed in 23 s).
- `git diff --stat origin/main`: `+139 / -3` across 2 files, well
  under the 400-line budget.
- Work-unit commit: `db3f36afa717b25f996dba0501335e5b5b933120`
  (`fix(animals): keep edit form action on validation-error rerender`).
  Author: `el-Gentleman <alan@apap.local>` per the repo convention for
  scripted work-unit commits on a feature branch.

## Learned

- Adding a keyword-only parameter with a sensible default is the
  smallest reversible change that keeps both create call sites
  untouched. The default encodes "no flow specified → assume create",
  matching the legacy hardcoded value, so any future caller that
  forgets to pass `form_action` defaults to the create endpoint
  rather than silently failing.
- The route monkeypatch pattern (`monkeypatch.setattr(animals_routes._templates,
  "TemplateResponse", render)`) preserves the existing helper signature
  but does NOT preserve the `status_code` kwarg unless the stub
  forwards it. Capturing both `context` and `status_code` is the
  minimum needed to assert the 422 contract without losing fidelity.
- The XSS allow-list in `tests/test_xss_audit.py` already names
  `("animales/form.html", "form_action")` and explicitly documents
  that the value is server-generated (either `/animales` or
  `/animales/{id}/update`); the fix brings the runtime behaviour in
  line with that allow-list's stated contract.

Rollback boundary: the two changed files only. RDD mode is on (global
preference); the work-unit commit is the native review candidate.

## Ratchet refactor (follow-up micro-task on PR #1021)

- [x] **T4 — fold 422 status into the helper.** The #974 fix left
  `_render_animal_form_error` with 6 parameters; PLR0913 went 47→48
  on `app/`, tripping the ratchet in `scripts/check_ruff_ratchet.py`.
  Refactor (not a baseline bump): drop the `status_code` parameter
  from the helper, render with `status.HTTP_422_UNPROCESSABLE_CONTENT`
  internally, and inline the UniqueViolationError branch in
  `create_animal_view` with a direct `_templates.TemplateResponse`
  call (`status_code=409`, same context shape). The helper is now
  422-only with a 5-param signature `(request, user, form_data,
  error, *, form_action="/animales")`; PLR0913 measured = 47 = baseline.
  The 409 pinned test (`test_create_animal_view_translates_unique_violation_to_409`)
  and the two #974 regression tests are unchanged and still green.
  Work-unit commit: `refactor(animals): fold 422 status into
  _render_animal_form_error` (one-line body, refs #974). Behavior
  preserved end-to-end; no template, message, or response-shape change.