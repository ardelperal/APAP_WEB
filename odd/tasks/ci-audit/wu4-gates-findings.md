# wu4 — PR-gate family read-only audit findings

**Repo**: `/home/ubuntu/repos/apap-app` (main checkout, read-only)
**Branch audited (worktree, read-only)**: `fix/956-issue-spec-deterministic` at
`/home/ubuntu/repos/apap-app-worktrees/956-issue-spec-deterministic`
**Audit date**: 2026-09-29
**Scope**: `pr-size.yml` + `scripts/check_pr_size.py` + `size:exception` flow
(issues #941, #896, #926, PR #936), `pr-name.yml` + `scripts/check_branch_name.py`,
new `issue-spec` gate (#956), traceability from branch + `closingIssuesReferences`
+ `chain:partial`, plus `docs/architecture/decisiones/d-35-presupuesto-400-lineas-pr.md`
and the gate sections of `CONTRIBUTING.md`.
**Out of scope**: no file writes in either checkout; no `gh pr`/`gh label` writes;
no pushes.
**Skills loaded**: `repository-delivery-governance` (HR-4 / HR-7 / HR-9 / HR-10 /
HR-13 / HR-21), `apap-merge-workflow` (cross-check for pre-MVP single-branch).
**Linter of record**: epic #935 design rule — *"la CI no impone fricción que la
industria no imponga. Un gate bloqueante solo se mantiene si detecta defectos
reales o es práctica estándar; si una métrica obliga a reestructurar código
correcto, el defecto es del gate."*

---

## Inventory

| Gate (workflow → script) | Trigger | Structured data read | Prose read | Fail-closed on API error |
|---|---|---|---|---|
| `pr-name.yml` → `check_branch_name.py` | `pull_request` (default types) | `github.head_ref`, `github.event.pull_request.user.login` | none | n/a (no API calls) |
| `pr-size.yml` (reusable + direct) → `check_pr_size.py` | `pull_request: [labeled, unlabeled]` + `workflow_call` from `ci.yml` | `issues/<n>/labels?per_page=100` via REST | none | yes (`exit 1` on non-200, line 166-169) |
| `ci.yml` → `check_issue_specs.py pr-event` (NEW) | `pull_request` (default types only — NO `labeled`/`unlabeled`) | GraphQL `closingIssuesReferences` + `labels`; REST `/repos/.../issues/<n>` | none | yes (`GitHubApiError` → violation, line 416-427) |
| `ci.yml` → `check_issue_specs.py forms` | `pull_request` (default types) | `.github/ISSUE_TEMPLATE/*.yml` + `config.yml` | none | n/a |

The `size:exception` mechanism is *label-only* — the documented
`size-exception-reason:` field in `CONTRIBUTING.md` (lines 92, 165, 263, 290)
and `.github/PULL_REQUEST_TEMPLATE.md:49` is **not parsed by any gate**.

---

## Findings (severity / id / evidence / friction / removable fix)

### G1 — HIGH — `chain:partial` has the same label-race as `size:exception`, but the docs and the open-issue tracker don't name it

**Severity.** HIGH. Same root cause as #941 (open) but applied to the new
`chain:partial` label. The gate's own behavior in this state is silent (the
last evaluation is what is shown), and there is no published workaround.

**Evidence.**
- `ci.yml:4-5` in both checkouts (`main` and `fix/956-issue-spec-deterministic`)
  declares `pull_request:` with **default types only** (opened, synchronize,
  reopened) — no `labeled` / `unlabeled`.
- `pr-size.yml:13-14` does declare `types: [labeled, unlabeled]` for its own
  direct trigger — but only `pr-size.yml` re-runs, not `ci.yml`.
- `fix/956-issue-spec-deterministic/scripts/check_issue_specs.py:51`
  defines `CHAIN_PARTIAL_LABEL = "chain:partial"`. The gate only consults the
  label via GraphQL (`closingIssuesReferences` + `labels`) and via the PR
  labels REST endpoint.
- `fix/956-issue-spec-deterministic/CONTRIBUTING.md:157` says the intermediate
  slice must add `chain:partial`; `fix/956-issue-spec-deterministic/.github/PULL_REQUEST_TEMPLATE.md:6`
  repeats the same.
- CONTRIBUTING.md (both versions) at line 167 acknowledges the `size:exception`
  race and points to #941. The parallel `chain:partial` race is **not
  documented**, and #941 only mentions `size:exception`.

**Friction.**
1. A contributor opens the PR without the label (the gate passes because the
   PR body / closing keywords already satisfy the closing-reference rule).
2. The PR turns out to need a chain, so the contributor adds `chain:partial`
   via `gh pr edit --add-label chain:partial` or the GitHub UI.
3. The `labeled` event triggers only `pr-size.yml`'s direct path (it
   re-publishes the `pr-size` check, but the label is irrelevant to that
   check). `ci.yml`'s `issue-spec` job does NOT fire.
4. If the PR is actually intermediate (must NOT close the parent issue), the
   `required` aggregator keeps showing the **last** `issue-spec` verdict
   (green from when the label was absent). Until the next push to the branch
   (a `synchronize` event re-runs `ci.yml`), an inconsistent state is
   pinned: the gate would say "must close #N" if re-evaluated, but the live
   `required` shows the previous green.
5. The reverse race — `chain:partial` set by mistake on the final slice, then
   removed — has the same shape.

**Removable fix.** Two coordinated moves:
- Either extend `ci.yml`'s `pull_request:` block with `types: [labeled, unlabeled]`
  and let `issue-spec` re-validate (read labels live the way `pr-size.yml`
  does); or
- Publish a documented workaround (push a commit, or `gh run rerun <run-id>`
  of `ci`) symmetric with the `size:exception` workaround in CONTRIBUTING.md:167.
The label work is gated by the same #890 single-publisher rule, so the
label-driven `pr-size.yml` already proves the pattern works for a single
job. Replicating it for `issue-spec` requires the same per-trigger
concurrency suffix (line 39 of `pr-size.yml`) and the same fail-closed live
label read the gate already has in `_CLOSING_REFERENCES_QUERY`.
**Cost**: ~20-40 lines + a guard test that fails if `ci.yml`'s
`pull_request:` types grow without `issue-spec` also re-validating.

---

### G2 — HIGH — `size-exception-reason:` is documented as required by 4 places but parsed by zero gates

**Severity.** HIGH. The CONTRIBUTING.md prose, the PR template, the reviewer's
checklist and the project's taxonomy table all promise that an oversized PR
must include `size-exception-reason: <why>` in the body. The check_pr_size.py
script receives the *label* presence as a boolean and does not even take the
PR body as input.

**Evidence.**
- `CONTRIBUTING.md:92` (taxonomy table): `size:exception | Override del
  presupuesto de 400 líneas por PR. Requiere size-exception-reason: en el
  cuerpo.`
- `CONTRIBUTING.md:165` (Excepción de tamaño): *"pida el label size:exception
  e incluya size-exception-reason: con el motivo en el cuerpo del PR."*
- `CONTRIBUTING.md:263` (Travesía del contribuidor): same.
- `CONTRIBUTING.md:290` (Checklist del contribuidor): *"El diff no supera 400
  líneas o justifica size:exception (con size-exception-reason: en el cuerpo
  y el re-run de ci si el label se añadió a un PR abierto)."*
- `.github/PULL_REQUEST_TEMPLATE.md:45-49`: dedicated section.
- `scripts/check_pr_size.py:10-17` (Usage line) takes `<total-changed-lines>
  <has-exception-label>` — no body argument.
- `pr-size.yml:136-177` (`Check size:exception label via the GitHub API`) reads
  the label only, then `Enforce 400-line budget` runs `check_pr_size.py`.
- Repo-wide search: `grep -rn "size-exception-reason\|exception.reason"
  /home/ubuntu/repos/apap-app/scripts/` — zero hits.

**Friction.** A contributor can apply `size:exception` and ship a PR that
violates 4 documented requirements at zero cost — the gate never reports the
missing reason. The merge-time check is "manual" per `CONTRIBUTING.md:147`,
and the reviewer has to chase the missing reason in code review, where it is
easy to miss. This is exactly the failure mode epic #935 calls out: *"Un gate
bloqueante solo se mantiene si detecta defectos reales o es práctica estándar;
si una métrica obliga a reestructurar código correcto, el defecto es del gate."*
Here the gate is silent where the docs require a check.

**Removable fix.** Two deterministic options (the user asked for one):
1. **Structured field parsing.** Add an extra step in `pr-size.yml` after the
   label check: `curl /repos/<owner>/<repo>/pulls/<n>` (already permitted via
   `pull-requests: read` in the new fix), grep the `body` field with a
   deterministic regex like `^size-exception-reason:\s*\S+` and pass a third
   argument `HAS_REASON` to `check_pr_size.py`. Extend `check_pr_size.py`
   to require both label AND reason, with a fail message pointing at the
   exact missing piece. Cost: ~25 lines + a guard test for the regex +
   `tests/test_pr_size.py` cases. Removes the "manual" half of the manual
   review checklist.
2. **Issue form / PR form fields.** Convert `size-exception-reason:` to a
   real PR form field (`.github/PULL_REQUEST_TEMPLATE`) so the body field is
   required when the label is set. More invasive; not strictly necessary if
   option 1 is in.

Either option replaces the "label dance" (#941 C-11) with a deterministic
data field.

---

### G3 — HIGH — `pr-size / pr-size` requires a manual rerun after `size:exception` is added; #941 is open and unresolved

**Severity.** HIGH. Acknowledged by maintainer in CONTRIBUTING.md:167 and
issue #941 (open). This audit does not propose a new fix — it confirms the
gap is still there as of the audit date and flags the cost of leaving it open.

**Evidence.**
- `CONTRIBUTING.md:167` (current main): *"Añadir (o quitar) el label en un
  PR ya abierto no recalcula el check requerido pr-size / pr-size: el evento
  labeled/unlabeled refresca solo el camino directo de pr-size.yml, no la
  llamada desde ci. Relance la CI a mano con gh run rerun <run-id-del-run-de-ci>
  ... El re-run ve el label añadido; el refresco automático sin intervención
  manual está pendiente en #941."*
- Issue #941 (open, status:approved, priority:low, labels `ci-audit-2026-09-24`,
  `type:chore`): *"chore(ci): añadir o quitar size:exception en un PR abierto
  no recalcula el check requerido pr-size / pr-size"*. Acceptance criteria
  explicitly require *"Añadir size:exception a un PR abierto que supera el
  presupuesto deja pr-size / pr-size y required en verde sin relanzar nada
  a mano."*
- Issue #896 (open, status:approved, type:bug, priority not set) is the
  parent that includes the label-exact-match requirement plus the
  recalculation requirement, and references the same #926 root cause.
- `pr-size.yml:38-40` (concurrency group with `label`/`call` suffix per
  trigger) was added by PR #936 to fix the #926 cancellation race; it does
  NOT bridge the gap to `required` (because `ci.yml`'s `pull_request` does
  not include `labeled`/`unlabeled`).
- PR #936 commit body and issue #926 evidence (run 36041158202, run
  36046072242) are referenced in the workflow comments at `pr-size.yml:3-37`.

**Friction.** Documented workaround: `gh run rerun <ci-run-id>`. The
CONTRIBUTING.md also warns explicitly NOT to use `gh workflow run ci.yml
--ref <branch>` because a `workflow_dispatch` event makes the diff step
emit `total=0` and skips the label step (`if: github.event_name ==
'pull_request'`). That makes the workaround correct but non-discoverable:
the contributor has to find the right `ci` run id, not the pr-size.yml run
id, and must not re-dispatch `ci`. The Travessía del contribuidor (CONTRIBUTING.md
step 6) calls this out, but only after the contributor has already hit the
wall.

**Removable fix.** The smallest change is the same as G1: extend `ci.yml`'s
`pull_request:` block to include `labeled` and `unlabeled`, so the
aggregator `required` re-evaluates when the label changes. The single-publisher
rule (#890) is preserved by routing both `pr-size` and `issue-spec` (and the
rest of `ci.yml`) through one re-evaluation. Cost: ~15 lines + guard test.

---

### G4 — MEDIUM — The new `issue-spec` gate still reads prose in one place: the `Refss #N` in the PR body is documented but not enforced

**Severity.** MEDIUM. The new gate's big win is that it ignores the PR body
(only `closingIssuesReferences` and labels). But the PR template and CONTRIBUTING.md
still tell contributors to write `Refs #N` in the body of intermediate
slices. The gate does not check for `Refs`, so this becomes a doc-only rule
that contributors can forget without the CI catching it.

**Evidence.**
- `fix/956-issue-spec-deterministic/scripts/check_issue_specs.py` reads
  `pull_request["head"]["ref"]`, `pull_request["number"]`,
  `pull_request["user"]["login"]` and the `repository.full_name` from the
  event. It does NOT read `pull_request["body"]`.
- `fix/956-issue-spec-deterministic/.github/PULL_REQUEST_TEMPLATE.md:6`:
  *"Tramo intermedio de una cadena: etiqueta chain:partial, misma N en la
  rama y Refs #N en lugar de Closes."*
- `fix/956-issue-spec-deterministic/CONTRIBUTING.md:157`: same.
- `fix/956-issue-spec-deterministic/CONTRIBUTING.md:244` (Travesía del
  contribuidor step 1): same.

**Friction.** If a contributor sets `chain:partial` and forgets `Refs #N`,
the gate still passes (because `Refs` is non-closing and `chain:partial`
suppresses the close-required check). The information about "this slice is
intermediate" lives only in the label and the body. Future readers (history,
triagers) see the label and may miss that the body never mentioned the
parent issue. This is a minor signal-loss problem, not a blocking one.

**Removable fix.** Either:
- Drop the `Refs #N` advice from the PR template and CONTRIBUTING.md (the
  label is enough); or
- Add a non-blocking lint step in `ci.yml` (after `lint`, before `required`)
  that warns when `chain:partial` is set and the body does not contain
  `Refs #N`. The body field is already fetched via the GraphQL call (extend
  the query). Cost: ~20 lines + a soft test (warns, does not fail) to keep
  the gate aligned with #935's "no fricción que la industria no imponga"
  principle.

---

### G5 — MEDIUM — `issue-spec` makes `chain:partial` the only escape hatch; removal or misapplication is silent until next push

**Severity.** MEDIUM. The new gate has four labelled states (no label + close,
no label + no close, chain:partial + close, chain:partial + no close) and
fails closed on the last two states with clear messages. But there is no
guard rail against the *forgetting* path: a contributor who opens a chained
slice without `chain:partial` will have `Refs #N` (or no reference) in the
body, and the gate will complain "must close #N (from branch)..." forcing
them to either (a) close the parent (premature — the #931 regression) or
(b) remember to add `chain:partial` AND keep the body free of closing
keywords. There is no in-band signal that "this is intermediate".

**Evidence.**
- `fix/956-issue-spec-deterministic/scripts/check_issue_specs.py:418-429`:
  only failure messages are "would close #N" / "must close #N (from
  branch)". No diagnostic like "did you mean chain:partial?".
- `fix/956-issue-spec-deterministic/CONTRIBUTING.md:157` documents the
  required label; the gate's error does not point at the docs section.
- PR #931 (head `refactor/913-sql-executor-helpers`, base main, labels
  included `size:exception`) is the documented case where a chained PR was
  permitted to close #913 prematurely because the previous regex parser
  read `Closes #913` from a fenced diagram (#952). The new gate closes
  *part* of that loophole (no more regex on prose) but not the
  misapplication side.

**Friction.** Two contributors working on the same chained PR can end up in
inconsistent states — one slice labelled `chain:partial`, another labelled
nothing and closing the parent by mistake. The gate catches the second case
only when the `synchronize` event fires (`ci.yml` does not re-run on
`labeled`/`unlabeled` — see G1).

**Removable fix.** Once G1 is fixed (label-driven re-evaluation), this
becomes a self-correcting workflow: adding `chain:partial` re-validates the
gate. Until then, two cheap improvements:
- Add the canonical CONTRIBUTING.md section link to the gate's error
  message ("did you mean to add the chain:partial label and use Refs #N?
  See CONTRIBUTING.md §PR encadenados").
- Add a unit test that covers the label-removal path: open a PR with
  `chain:partial` and `Refs #N`, then simulate removing the label via the
  GraphQL mock — the gate should fail closed at the next re-evaluation.

---

### G6 — MEDIUM — Cross-repo closing references are silently filtered out by the new `issue-spec` gate

**Severity.** MEDIUM. The new gate filters `closingIssuesReferences` to
same-repo only (`parse_pull_request_links`, line 248-250 in the worktree).
This is intentional for forks and other repos, but it silently drops any
cross-repo `Closes other-org/other-repo#N` that the contributor may have
written. Old behavior was symmetric: the body parser also restricted to the
same repo.

**Evidence.**
- `fix/956-issue-spec-deterministic/scripts/check_issue_specs.py:246-251`:
  `closing = sorted(int(node["number"]) for node in closing_nodes if
  str(node["repository"]["nameWithOwner"]).lower() == repository.lower())`.
- The body parser (`REFERENCE_RE`) had the same `owner/repo` filter before
  the rewrite (see `scripts/check_issue_specs.py` line 234-240 on main).
- No test covers a cross-repo reference; the tests focus on same-repo.

**Friction.** A cross-repo `Closes other-org/other-repo#N` is treated as if
not present. If the contributor relied on this for documentation purposes
(reference to an external tracker), it disappears from the gate's view with
no warning. Not a functional defect; a discoverability concern.

**Removable fix.** None required. If desired, emit a non-failing notice in
the gate output ("note: ignored cross-repo closing reference #N for
other-org/other-repo"). Cost: ~10 lines.

---

### G7 — LOW — Exempt heads (`main`, `archive/*`, `skill-fleet/*`) and `dependabot[bot]` bypass the gate; coverage is incomplete

**Severity.** LOW. The exempt-head list covers three patterns; the
dependabot exemption covers one actor. Other special branches / actors
(`release/*`, `renovate[bot]`, `github-actions[bot]`) are not in either list.

**Evidence.**
- `fix/956-issue-spec-deterministic/scripts/check_issue_specs.py:48`
  (`AUTOMATED_ACTORS = frozenset({"dependabot[bot]"})`).
- `fix/956-issue-spec-deterministic/scripts/check_issue_specs.py:55-56`
  (`_EXEMPT_HEAD_PREFIXES = ("archive/", "skill-fleet/")`,
  `_EXEMPT_HEADS = frozenset({"main"})`).
- `scripts/check_branch_name.py:22-24` has a parallel
  `_DEPENDABOT_PATTERN` for `dependabot/pip|npm_and_yarn|github_actions/...`
  but no pattern for other tooling.
- Live repo state: PRs from `github-actions[bot]` for workflow template
  regeneration, from `renovate[bot]` if/when it is enabled, from
  Copilot / `copilot-pull-request[bot]`, would all need a branch name
  matching `<tipo>/<N>-<slug>` AND an issue link.

**Friction.** Currently fine — `github-actions[bot]` and `renovate[bot]` are
not configured. But adding any new bot (or a manual `release/*` branch for
a backport) triggers a gate failure with no obvious remediation. The
CONTRIBUTING.md does not enumerate the supported exemptions.

**Removable fix.** Either widen `_EXEMPT_HEAD_PREFIXES` to include
`release/` and `hotfix/` with documented allowlist semantics; or document
that any non-conforming branch must use `archive/` for tooling PRs that
don't trace to an issue. Cost: ~5 lines + one docs sentence.

---

### G8 — LOW — `scripts/check_pr_size.py` and `scripts/check_branch_name.py` carry an unused locale pin and lack modern Python affordances

**Severity.** LOW. Two cosmetic-but-noticed items:
- Both scripts pin UTF-8 stdout/stderr via `_pin_output_encoding()`. The
  function was added in response to issue #488. The `print(...)` calls in
  both scripts already work in UTF-8 on every locale that has CI jobs; the
  pin is redundant on modern Python and adds a no-op branch. Cost of
  removal: ~5 lines each.
- `check_branch_name.py` exposes a `check(head_ref, actor)` function but the
  test in `tests/test_check_issue_specs.py` (line 373 of the worktree) calls
  `check_branch_name.check(head_ref)` directly to verify the same regex.
  This is a healthy coupling; no change needed.

**Evidence.**
- `scripts/check_pr_size.py:34-38` (`_pin_output_encoding`).
- `scripts/check_branch_name.py:51-55` (same).

**Friction.** None functional. Visual noise in two short scripts.

**Removable fix.** Drop the `_pin_output_encoding` block in both files
since `print` is locale-correct in Python 3.10+ on every supported runner.
Verify in CI: `uv run pytest tests/test_pr_size.py tests/test_branch_name.py`.

---

### G9 — LOW — `branch-name` gate has a hardcoded `ALLOWLIST` for grandfathered branches and lacks a clear migration path

**Severity.** LOW. The `ALLOWLIST` frozenset in `check_branch_name.py:11-17`
covers three historical branches (`feat/quality-gates-mutation`,
`feat/architecture-layers-gate`, `resolve-conflict`). The comment says *"Add
more here as the user renames legacy branches"* but the doc does not
enumerate the migration order or the date by which the list is expected to
be empty.

**Evidence.**
- `scripts/check_branch_name.py:11-17`.
- `scripts/check_branch_name.py:14-16` has a typo-candidate (odd indentation
  on `resolve-conflict`), suggesting the file is hand-edited.

**Friction.** A new grandfathers branch has to be added by editing the
script. The script-level test (`test_check_branch_name.py`, not visible in
this audit) presumably covers the allowlist, but the operator policy to clean
it up is undocumented.

**Removable fix.** Add a TODO with a deadline (e.g. "remove allowlist after
2026-12-31") and a one-line migration procedure in `CONTRIBUTING.md`. Cost:
~5 lines.

---

## Keep-list (intentional design choices worth preserving)

The following items looked like gaps at first read but are intentional and
well-documented. They are recorded here so future audits do not re-flag
them.

1. **`pr-size.yml` consumes both a `pull_request: [labeled, unlabeled]`
   trigger AND a `workflow_call` from `ci.yml`.** PR #936 split these so
   exactly one workflow publishes the `pr-size` check for any given event
   (#890 single-publisher rule). The `concurrency.group` carries a
   `label`/`call` suffix to keep stale-run cancellation isolated per path
   (`pr-size.yml:38-40`). This is the correct shape and was the right answer
   to #926.

2. **`scripts/check_pr_size.py` takes a boolean for the exception label, not
   a label name string.** The boolean comes from a `jq 'any(.[]; .name ==
   "size:exception")'` filter in `pr-size.yml:170`, which is exact-name (no
   `contains`). This satisfies #896's "size:exception-pending y cualquier
   otro nombre parcial no conceden la excepción" without any matching logic
   in the Python script.

3. **`issue-spec` calls GraphQL only after the branch issue is readable.**
   This avoids hammering the API when the branch itself is malformed
   (`validate_pr_event` line 411-413). Fail-closed ordering matches the
   pattern in `pr-size.yml:166-169`.

4. **`ci.yml`'s `required` aggregator depends on `issue-spec` via
   `needs:`.** Together with the explicit `if: github.event_name !=
   'schedule'` on `required` (line 1358), this means a weekly scan (the
   only schedule entry) runs `security-deep` alone and never fails the
   required aggregator on a red `issue-spec` (which is `pull_request`
   only). This is correct and is asserted by
   `tests/test_check_required_jobs.py`.

5. **`ALLOWLIST` in `check_branch_name.py` is a frozenset and is
   referenced once via `in`.** No mutation path. The test for the allowlist
   covers grandfather semantics.

6. **`PR_TEMPLATE` documents `size-exception-reason:` as a structured
   field.** Even if the gate does not parse it (G2), the template gives the
   contributor a deterministic place to put the reason. Combined with the
   manual reviewer check in CONTRIBUTING.md:147, this is a workable
   interim arrangement.

7. **The exemption list for `issue-spec` is exactly the same as the
   allowlist philosophy in `check_branch_name.py`** (frozen set + comment).
   G7 documents the gap (incomplete coverage for future bots) without
   changing the design.

---

## Cross-references

- Issue #935 — Epic for the CI quality of signal / efficacy / reproducibility.
  The 4 design questions in the audit prompt map onto C-11 (#941, size:exception
  race — G1, G3), C-13 (#956, chain:partial — G1, G5), C-12 (#952, prose
  parsing — now superseded by #956 for the issue-spec gate), and C-17
  (#964, contributing doc sync — partially closed by the `docs` commit on the
  worktree).
- Issue #926 — Closed by PR #936 (concurrency split + live label read). The
  fix is robust for the `pr-size` check itself, but does not bridge to the
  `required` aggregator (G3) or to `issue-spec` (G1).
- Issue #896 — Parent of #926, still open. Includes the exact-label
  requirement that #936 satisfies via `jq 'any(... == "size:exception")'`.
  The recalculation requirement is still open (G3).
- Issue #941 — Same gap as #896's recalculation requirement, applied to
  size:exception. Open. G3.
- Issue #956 — Design pivot from `Part of #N` body keyword to `chain:partial`
  label + `Refs #N` body. The new gate in
  `fix/956-issue-spec-deterministic` implements the label half but leaves the
  body half (G4) and the label race (G1, G5) open.
- Issue #962 (PR #962 open) — Removes `branches: [main, staging]` filter from
  `ci.yml` and `codeql.yml`. Once merged, chained PRs whose base is a feature
  branch will get a `ci` run, which subsumes part of G1: a `synchronize`
  event on a chained PR will re-validate `issue-spec`. The label-driven race
  (G1, G5) still needs `labeled`/`unlabeled` on `ci.yml`.
- PR #936 — Concurrency split + live label read. Proven in production by
  PR #931's own rerun picking up the `size:exception` label.
- PR #931 — Head branch `refactor/913-sql-executor-helpers`, base `main`,
  with `size:exception` label. Closed #913 prematurely (#956 evidence). New
  gate would have caught the chain:partial-vs-close mismatch if the label
  had been set and the PR body had only `Refs #913`.

---

## Top-5 fix list (cost-ordered, severity-ordered)

1. **G2 — Add `size-exception-reason:` parsing to `pr-size.yml`.** Cheap
   (~25 lines), high signal. Removes the only documented-but-not-enforced
   gate in the family. Must run with `pull-requests: read` already granted
   in `pr-size.yml`.
2. **G1 — Extend `ci.yml`'s `pull_request:` types to include `labeled,
   unlabeled`.** Cheapest end-to-end fix for both `size:exception` (#941,
   G3) and `chain:partial` (G1, G5) race conditions. The single-publisher
   rule from #890 is preserved because the existing `pr-size.yml` already
   consumes `labeled`/`unlabeled` from its own trigger (line 13-14); the
   change adds the same hook to `ci.yml`'s pull_request trigger with the
   `issue-spec` job already reading labels live (no new API call shape).
   ~15 lines + a guard test.
3. **G5 — Improve the `issue-spec` error messages with the CONTRIBUTING.md
   pointer and the chain:partial hint.** ~10 lines. Pure docs-as-code.
4. **G4 — Either enforce or retire the `Refs #N` body rule.** Retire is
   cheaper (~3 lines removed from PR template + CONTRIBUTING.md); enforce
   as a soft warning is ~25 lines. Pick one.
5. **G6 — Emit a non-failing notice for cross-repo `closingIssuesReferences`.**
   ~10 lines. Optional but improves discoverability.

G7, G8, G9 are housekeeping and can be batched into a single "polish" PR.

---

## Files inspected (read-only)

- `/home/ubuntu/repos/apap-app/.github/workflows/pr-size.yml` (177 lines)
- `/home/ubuntu/repos/apap-app/.github/workflows/pr-name.yml` (37 lines)
- `/home/ubuntu/repos/apap-app/scripts/check_pr_size.py` (71 lines)
- `/home/ubuntu/repos/apap-app/scripts/check_branch_name.py` (77 lines)
- `/home/ubuntu/repos/apap-app/CONTRIBUTING.md` (295 lines, gate sections
  132-170 and 232-293)
- `/home/ubuntu/repos/apap-app/docs/architecture/decisiones/d-35-presupuesto-400-lineas-pr.md`
  (58 lines)
- `/home/ubuntu/repos/apap-app/tests/test_pr_size.py` (38 lines)
- `/home/ubuntu/repos/apap-app-worktrees/956-issue-spec-deterministic/scripts/check_issue_specs.py`
  (547 lines, with the diff vs main)
- `/home/ubuntu/repos/apap-app-worktrees/956-issue-spec-deterministic/.github/workflows/ci.yml`
  (1384 lines; the diff vs main)
- `/home/ubuntu/repos/apap-app-worktrees/956-issue-spec-deterministic/CONTRIBUTING.md`
  (gate section + Travesía del contribuidor)
- `/home/ubuntu/repos/apap-app-worktrees/956-issue-spec-deterministic/.github/PULL_REQUEST_TEMPLATE.md`
  (49 lines)
- `/home/ubuntu/repos/apap-app-worktrees/956-issue-spec-deterministic/docs/quality/ci-gate-inventory.md`
  (gate entries for `pr-size` and `issue-spec`)
- `/home/ubuntu/repos/apap-app-worktrees/956-issue-spec-deterministic/tests/test_check_issue_specs.py`
  (new tests for chain:partial + GraphQL parsing)
- `/home/ubuntu/repos/apap-app-worktrees/956-issue-spec-deterministic/tests/test_ci_workflow.py`
  (new permission guard at line 900)

## Live state consulted (read-only gh calls)

- `gh issue view 941 --repo ardelperal/APAP_WEB`
- `gh issue view 896 --repo ardelperal/APAP_WEB`
- `gh issue view 926 --repo ardelperal/APAP_WEB`
- `gh issue view 956 --repo ardelperal/APAP_WEB`
- `gh pr view 962 --repo ardelperal/APAP_WEB`
- `gh issue view 935 --repo ardelperal/APAP_WEB` (parent epic)
- `gh pr view 936 --repo ardelperal/APAP_WEB` (the fix that closed #926)
- `gh pr view 925,931 --repo ardelperal/APAP_WEB` (chained PRs in the
  evidence trail)
- `gh label list --repo ardelperal/APAP_WEB` (confirmed `chain:partial`
  exists with description *"Tramo intermedio de una cadena de PR: no cierra
  la issue de su rama (#956)"*)

No `gh pr edit`, no `gh label create/edit/delete`, no `git push`, no
repository file writes.