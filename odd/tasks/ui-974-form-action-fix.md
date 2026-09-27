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

## Delivery mechanics (round 1, BLOCKED)

- Step 1: `git fetch origin main fix/974-form-action-error-rerender` — ok.
- Step 2 (preflight): `gh pr view 1021 ... --jq .mergeStateStatus` →
  `BEHIND`. Branch tip `1054446` was 3 commits behind `origin/main`.
- Step 3: detached-HEAD merge of `origin/main` into the PR branch →
  new merge commit `77d7fe4`; `git push origin HEAD:fix/974-form-action-error-rerender`
  → `1054446..77d7fe4`. No conflicts. Back on the local branch.
- Step 4: poll → `lint` job **fails** (`required` cascades to fail
  because lint is the gate job; the other `skipped` jobs are the
  normal cascade from lint failing, not a separate problem).
- Lint job log evidence
  (`actions/runs/36304667519/job/108578850115`):
  - `ruff check .` → `All checks passed!` — PLR0913 is fixed, the
    previous blocker is genuinely resolved.
  - `python scripts/check_module_size.py` → `check_module_size: OK`.
  - `python scripts/check_route_size.py` → **FAILS**:
    `FAIL app/modules/animals/routes.py::create_animal_view: 54 lines,
    exceeds the 50-line budget (AGENTS.md rule 28) — move
    HTTP-unrelated logic to the service layer; do NOT add it to BASELINE`.
- `required` job evidence
  (`actions/runs/36304667519/job/108578941284`):
  - `FAIL required jobs: lint: result='failure'` (root cause).
  - `build / integration / security / test / verify-fallback-ready:
    result='skipped'` (cascade from lint failure, not new blockers).
- This is a NEW failing check relative to the previous attempt. The
  PLR0913 fix (commit `1054446`) inlined the UniqueViolationError
  branch into `create_animal_view`, growing that handler from 41 → 54
  lines and tripping the AGENTS.md rule 28 route-handler size ratchet.
  The parent's "expected now: checks green" prediction did not include
  this rule — it only listed PLR0913 (now fixed) and `issue-spec`
  (also fixed).
- Per the hard rule "if a NEW failing job appears after your
  integration, STOP immediately and report — no fixes", delivery stops
  here. No further integration or merge attempted.
- Round landed: **1 of 4**, outcome: **blocked by a real lint
  failure** (route-handler size ratchet, not the expected PLR0913).
- Branch state on `origin`: tip `77d7fe4` (the BEHIND-resolution merge
  commit) is in place; the PR is `BLOCKED`.

## Ratchet refactor (round 2)

- [x] **T5 — extract the inlined 409 block into `_render_animal_conflict`.**
  Inlined branch (~15 lines) lived in `create_animal_view` after T4
  folded 422 into `_render_animal_form_error`; that pushed the handler
  to 54 lines and tripped AGENTS.md rule 28 (route-handler size
  ratchet) even though PLR0913 was back to 47. Round 2 extraction:
  new module-level sibling `_render_animal_conflict(request, user,
  form_data, _error) -> Response:` placed right after
  `_render_animal_form_error` (file organization preserved), body is
  the exact inlined `_templates.TemplateResponse(...)` with hardcoded
  `status.HTTP_409_CONFLICT` and `form_action="/animales"` plus the
  operator-facing NCHIP message; `create_animal_view`'s
  `UniqueViolationError` branch becomes a one-line call passing
  `str(exc)`. `_render_animal_form_error` is untouched at 5 params
  (422 hardcoded, keyword-only `form_action`) per the parent spec.
  Helper signature mirrors the sibling for symmetry; the 4th parameter
  is renamed `_error` (leading underscore = intentionally unused)
  instead of `error` to keep ARG001 at 31 — ruff's convention for
  this exact pattern. PLR0913 measured = 47 = baseline; ARG001 = 31
  = baseline; `create_animal_view` 42 ≤ 50 budget. Behavior
  preserved end-to-end: same template, same context shape, same
  hardcoded message, same 409 status. Pinned test
  `test_create_animal_view_translates_unique_violation_to_409`
  unchanged and green. Work-unit commit:
  `refactor(animals): extract conflict rerender into _render_animal_conflict`
  (body satisfies both ratchets without baseline changes, refs #974).

## Delivery mechanics (round 2 of integration loop)

- Step 1: `git fetch origin main fix/974-form-action-error-rerender` — ok
  (no new remote refs reported by `git fetch`; both refs already
  tracking).
- Step 2 (preflight): `gh pr view 1021 ... --jq .mergeStateStatus` →
  `BLOCKED` (not `BEHIND`, not `CLEAN`).
- `gh pr checks 1021 --repo ardelperal/APAP_WEB` snapshot at start of
  round 2 polling:
  - `lint` — pending (run 36305073374 / job 108580021919).
  - `issue-spec` — pass (run 36305073374 / job 108580021958).
  - `typecheck` — pass (run 36305073374 / job 108580021930).
  - `mutation` — skipping (run 36305073374 / job 108580022970).
  - `security-deep` — skipping (run 36305073374 / job 108580022945).
  - `GitGuardian Security Checks` — pass (dashboard).
  - `pr-size / pr-size` — pass (run 36305073374 / job 108579969837).
  - `CodeQL analysis (Python)` — pending (run 36305073269 / job
    108579969399).
  - `branch-name` — pass (run 36305073255 / job 108579969229).
- Loop step 3 (BEHIND branch) does not apply: `mergeStateStatus` is
  `BLOCKED`, not `BEHIND`. The PR branch tip `d18d6f7` already
  contains the round-1 BEHIND-resolution merge commit `77d7fe4`.
- Proceeding to loop step 4: poll every 60 s, up to 12 min, until
  `lint` and `CodeQL` settle and `mergeStateStatus` flips to `CLEAN`,
  or any non-skipping check fails (STOP then).

## Delivery mechanics (round 2 — STOP, blocker)

- Polling timeline (from round-2 polling start, run 36305073374):
  - +60 s: `mergeStateStatus=BLOCKED`. `lint` PASSED (46 s); `CodeQL
    analysis (Python)` PASSED (1 m 40 s). Pending: `test`,
    `integration`, `verify-fallback-ready`. Skippeados: `mutation`,
    `security-deep`.
  - +120 s: `integration` PASSED (1 m 11 s). Pending: `test`,
    `verify-fallback-ready`.
  - +180 s: `verify-fallback-ready` PASSED (48 s). Pending: `test`
    only.
  - +240 s: still pending on `test`.
  - +360 s: still pending on `test`.
  - +480 s: `mergeStateStatus=UNKNOWN`. **`test` FAILED** (7 m 44 s)
    and `required` FAILED (cascade). Per loop step 4 + hard rule
    "If any check FAILS (not skipping): ... STOP and report — do not
    retry" and "NEW failing job after your integration → STOP
    immediately, report, no fixes": STOP. No further integration
    attempted.
- Failing job evidence (`test`, run 36305073374 / job 108580147689,
  `actions/runs/36305073374/job/108580147689`):
  - 4 885 passed, 16 skipped, **1 failed**, coverage 88.70 % OK.
  - The single failing test is
    `tests/test_check_mutation_sites.py::test_baseline_matches_current_tree_offenders`:
    ```
    FAILED tests/test_check_mutation_sites.py::test_baseline_matches_current_tree_offenders - AssertionError: assert {'app/modules...py': 466, ...} == {'app/modules...py': 466, ...}
    Omitting 23 identical items, use -vv to show
    Differing items:
    {'app/modules/animals/routes.py': 446} != {'app/modules/animals/routes.py': 462}
    ```
  - Root cause: the embedded mutation-sites baseline JSON in
    `tests/test_check_mutation_sites.py` records
    `app/modules/animals/routes.py = 462`, but T5
    (`refactor(animals): extract conflict rerender into _render_animal_conflict`)
    extracted ~15 lines of inlined `UniqueViolationError` rendering
    into a module-level sibling helper, shrinking the metric the
    baseline script counts from 462 → 446. Behavior is preserved
    end-to-end (same template, same context shape, same status, same
    message; pinned tests `test_create_animal_view_translates_unique_violation_to_409`,
    `test_create_error_rerender_keeps_create_action`,
    `test_update_error_rerender_keeps_update_action` all green) but
    the test compares current-tree offenders against the stored
    baseline JSON, so the ratchet bump was missed when the file shrank.
- Failing job evidence (`required`, run 36305073374 / job
  108581334130):
  - Root cause reported by the gate:
    `FAIL required jobs: test: result='failure'`.
  - `FAIL required jobs: build: result='skipped'` is **cascade** from
    `test` failure (the `build` job in `.github/workflows/ci.yml` has
    `needs: [pr-size, test, integration, verify-fallback-ready]` and
    therefore skips once any of those fails). `e2e` skips on PR by
    design (`if: github.event_name == 'workflow_dispatch' ||
    startsWith(github.ref, 'refs/tags/')`).
- Comparison with round 1:
  - Round 1 failure was `lint` (`create_animal_view` 54 lines, AGENTS.md
    rule 28 route-handler size ratchet) — a ratchet too. Round 1 was
    resolved by T5 (extract conflict), and the parent's prediction was
    "lint green". The PLR0913 ratchet and the route-handler ratchet
    were both fixed by T5, but the *third* ratchet the script
    `check_mutation_sites` enforces was missed — the mutation-site
    baseline JSON was not updated to reflect the new line count.
  - Net pattern: the ratchet gauntlet has more than two ratchets. T5
    satisfied PLR0913 + AGENTS.md rule 28 but the `mutation-sites`
    ratchet is a separate baseline JSON that needs a corresponding
    bump from 462 → 446 in
    `tests/test_check_mutation_sites.py::test_baseline_matches_current_tree_offenders`
    baseline JSON.
- Round landed: **2 of 3 of the integration loop**, outcome:
  **blocked by a real, NEW failing job (`test`) on a missed ratchet
  baseline bump** (mutation-sites baseline JSON for
  `app/modules/animals/routes.py`).
- Branch state on `origin`: tip `d18d6f7` (the `docs(odd)` work-unit
  identity commit on top of T5) is in place; the PR is `UNKNOWN` with
  the gate `required` failing because of `test`.
- The fix (a one-line baseline update from 462 → 446 in
  `tests/test_check_mutation_sites.py`) is a source change, not a
  delivery-mechanics mutation. It is **outside the allowed edit
  surfaces** for this delivery round (`odd/tasks/ui-974-form-action-fix.md`
  only) and the task explicitly states "Code is frozen — pure
  integration + merge mechanics". Per the hard rule, STOP and report
  to the parent; do NOT push a baseline bump.

## Delivery mechanics (round 3 — Phase A: authorized upward baseline bump)

- Measured sequence (AST mutation-site count for
  `app/modules/animals/routes.py`, direct `ast.parse` + `ast.walk`
  applying the same `_DIRECT_SITE_NODES` + `Call`/`Constant` rules as
  `scripts/check_mutation_sites.py::count_sites`):
  - `origin/main` = 446 (matches the embedded baseline entry).
  - `e85aa1a` (pre-T-commits on this branch, post-#991 merge into main)
    = 446.
  - `1054446` (T4 = `refactor(animals): fold 422 status into
    _render_animal_form_error`) = 454 (+8 vs main).
  - `56c9e39` (T5 = `refactor(animals): extract conflict rerender into
    _render_animal_conflict`) = 462 (+8 vs T4; T4+T5 together = +16 vs
    main).
  - `d18d6f7` (current branch tip) = 462.
- Phase A authorized edit: change the
  `app/modules/animals/routes.py` entry in
  `scripts/check_mutation_sites.py` from 446 → 462 with a per-entry
  rationale comment. No other entry changed
  (`git diff --stat scripts/check_mutation_sites.py` is a single
  inserted line).
- Verification gates observed (all green; exact exit codes noted):
  - `pytest tests/test_check_mutation_sites.py -q` → 9 passed, exit 0
    (was 1 failed before the bump; the
    `test_baseline_matches_current_tree_offenders` assertion now
    matches: baseline 462 == offenders 462 for `routes.py`).
  - `pytest tests/test_animals_routes.py -q` → 25 passed, exit 0.
  - `ruff check app/modules/animals/routes.py` → "All checks passed!",
    exit 0.
  - `scripts/check_route_size.py` → "check_route_size: OK", exit 0.
  - `scripts/check_ruff_ratchet.py` → "check_ruff_ratchet: OK
    (436 finding(s), all within baseline)", exit 0.
  - `scripts/check_mutation_sites.py` → "check_mutation_sites: OK"
    (no NOTE; the previous "grew beyond its baseline of 446" NOTE is
    gone because the baseline now matches the measured 462).
- Follow-up policy question (logged here, not addressed in this PR):
  `scripts/check_mutation_sites.py` is informational since #968 (every
  finding is a NOTE; `main()` never exits non-zero on findings), but
  `tests/test_check_mutation_sites.py::test_baseline_matches_current_tree_offenders`
  asserts EXACT equality between `BASELINE_MUTATION_SITES` and the
  computed offenders dict. That hard assertion is what failed here: a
  real-world refactor (T4+T5) grew `routes.py` by 16 AST mutation
  sites, the lint script shrugged, but the equality test blocked the
  PR. The mismatch between "the gate is informational" (CI script) and
  "the gate must be exact-equal" (CI test) belongs to the #968 policy
  conversation, not to #974. Tracking as a separate question.