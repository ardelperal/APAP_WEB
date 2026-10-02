# Audit Findings — wu3-deploy (release-evidence machinery)

**Goal (from brief).** Deep read-only audit of the release-evidence machinery
in `apap-app`: the `release-e2e-record`/`release-e2e-gate` pair,
`scripts/check_release_evidence.py`, the per-SHA evidence contract
(`release/e2e-production` on the deployed SHA), the rollback-by-digest path,
and the manual bootstrap gap on SHA `460c56f1`.

**Scope.** `.github/workflows/deploy.yml`,
`scripts/check_release_evidence.py` and its tests,
`docs/runbooks/e2e-production.md`, `docs/codebase/ci-cd.md`,
`tests/test_deploy_workflow.py`.

**Rules.** Evidence-grounded (`file:line`). No repository mutation.

---

## Scope disclosure — what was actually audited

The brief assumes the audited machinery lives on `main`. **It does not.**
Two distinct states are in play; this report covers both and flags where the
contract changes.

| State | HEAD | Files inspected |
|---|---|---|
| **`main`** (target of "main checkout") | `30f23cc76a83785ba885d620330a01736320353c` (merge of PR #1062) | `main/.github/workflows/deploy.yml`, `main/docs/runbooks/e2e-production.md`, `main/docs/codebase/ci-cd.md`, `main/tests/test_deploy_workflow.py` |
| **`chore/1082-release-e2e-gate-per-sha`** (the per-SHA design the brief describes) | `f2209a6958d80fa79974d8036a9107efaaca997f` (3 commits ahead of `main`, no PR open) | `1082/.github/workflows/deploy.yml`, `1082/scripts/check_release_evidence.py`, `1082/tests/test_check_release_evidence.py`, `1082/tests/test_deploy_workflow.py`, `1082/docs/runbooks/e2e-production.md`, `1082/docs/codebase/ci-cd.md` |

**On the brief's premise.** The brief mentions `scripts/check_release_evidence.py`,
`release-e2e-record`, per-SHA status `release/e2e-production`, and "PR #1110".
None of those exist on `main`:

- `grep -r "release-e2e-record\|check_release_evidence" --include='*.{yml,yaml,py,sh,md}'` over `main` returns zero hits.
- `release-e2e-record` job, `scripts/check_release_evidence.py`, and
  `tests/test_check_release_evidence.py` only exist on the worktree branch.
- `APAP_E2E_GATE_EVIDENCE` (the variable on `main`) does not exist on the branch;
  the branch asserts the opposite: `RETIRED_VARIABLE = "APAP_E2E_GATE_EVIDENCE"` and `assert RETIRED_VARIABLE not in workflow` in
  `tests/test_deploy_workflow.py:63`.
- SHA `460c56f1` does exist on `main` and is the merge commit for PR #1014
  (`docs/905-runbook-dryrun-fill`). It was the deploy that preceded the per-SHA
  design's introduction on `main` — not "the last deployed SHA" of a future
  design.
- PR #1110 does not exist in the git log (`git log --all --oneline | grep -i 1110`
  returns nothing). The only mention is `odd/tasks/ci-audit-friction-log.md:58`,
  which describes PR #1110 as unrelated work (the `size:exception` label
  ceremony, not a per-SHA gate).

The audit below treats the branch's design as the in-flight target. Findings
that only apply to one side are marked `main` or `branch`. Findings that apply
to both are unmarked.

---

## Findings

Severity scale: **BLOCKER** (release/merge blocking) · **CRITICAL** (silent
correctness or governance failure) · **WARNING** (operability debt or doc
drift) · **SUGGESTION** (improvement, not blocking). Cross-reference with
`repository-delivery-governance` HR catalogue where applicable.

---

### F-01 · Bootstrap gap on pre-existing revisions (epic #935 violation)

- **Severity:** WARNING
- **Evidence:** `1082/.github/workflows/deploy.yml:127-132` (the only
  "first deploy" branch) and `1082/docs/runbooks/e2e-production.md:342-345`
  (the explicit bootstrap paragraph). On `main` the gate is variable-based
  and does not have this gap; the gap is **introduced** by the per-SHA design.
- **Friction:** The `release-e2e-gate` job only short-circuits on **no previous
  successful deploy at all** (line 130: `if [ -z "$prev_sha" ]; then ...; exit 0`).
  Once **any** successful deploy exists on `main`, the gate queries that SHA's
  status. If the SHA predates the gate's introduction, its
  `release/e2e-production` status is `absent` → `check_release_evidence.py:94-98`
  returns verdict `ok=False, code="absent"` → gate fails closed → `deploy` is
  blocked. Epic #935's design rule: *"every new gate ships an automatic
  bootstrap or explicit degradation"* — the design ships a **manual** bootstrap
  documented in the runbook (operator must run `gh api .../statuses/${SHA}` with
  state `success` or `skipped:<reason>`). This is not "automatic bootstrap"
  and is not "explicit degradation in code" — it is a manual recovery step
  documented in prose. The deploy's failure message at runtime is
  `absent — no release/e2e-production status recorded for 460c56f1...`; the
  message names the SHA but does not point to the runbook section that
  explains the bootstrap. Operator must cross-reference.
- **Removable fix:**
  1. **Pre-merge**: before the per-SHA gate lands, run a one-shot
     bootstrap script (operationally, or as a job in the merge PR) that records
     `success` (or `skipped:bootstrap-before-1082-gate`) on `460c56f1...`.
     This is the cheapest path and turns the gap into a no-op at merge time.
  2. **In-code degradation**: in `release-e2e-gate`, when `prev_sha` resolves
     and the status is `absent`, compare `prev_sha`'s committer date against
     a sentinel commit (the merge of PR that introduces the gate). If the SHA
     predates the sentinel, exit 0 with a notice naming the bootstrap window.
     This satisfies #935's "explicit degradation" branch and removes the
     need for the runbook paragraph.
  3. **Hybrid**: ship the in-code degradation (option 2) **and** have the
     merge PR script register the bypass on `460c56f1...` (option 1) so the
     first deploy after merge succeeds without operator intervention.

---

### F-02 · Re-run of `deploy.yml` overwrites operator-recorded verdicts (silent evidence destruction)

- **Severity:** CRITICAL
- **Evidence:** `1082/.github/workflows/deploy.yml:479-517` (`release-e2e-record`
  body). The job unconditionally POSTs `state: "pending"` to
  `/repos/${GITHUB_REPOSITORY}/statuses/${GITHUB_SHA}` regardless of the current
  status of the same `release/e2e-production` context on the same SHA.
- **Friction:** Operator workflow for a release after a successful deploy:
  1. Deploy succeeds → `release-e2e-record` posts `pending` on SHA-A.
  2. Operator runs the runbook, then records `success` on SHA-A with the run URL.
  3. Operator (or anyone with `workflow: dispatch`) re-runs `deploy.yml` on
     the same SHA-A (e.g. flaky Trivy, scanner transient error, smoke-test
     flake during Step "Smoke-test the exact image digest" — common in the
     current `deploy` job, see `1082/.github/workflows/deploy.yml:385-423`).
  4. `release-e2e-record` runs again, posts `pending`, **overwriting the
     operator's `success`**.
  5. The next real deploy's `release-e2e-gate` queries SHA-A's status, sees
     `pending`, and blocks the new deploy with `pending — release/e2e-production
     on ${prev_sha} is still pending`.
  Result: the operator must re-record `success` on every SHA that had a
  successful deploy re-run. There is no test, doc note, or job guard against
  this. Test `test_release_e2e_record_sets_pending_status_on_the_deployed_sha`
  in `1082/tests/test_deploy_workflow.py:109-116` only pins the unconditional
  POST shape; it does not pin the "do not overwrite" contract.
- **Removable fix:** In `release-e2e-record`, before the POST, GET the current
  combined-status of the SHA (same API call shape `release-e2e-gate` already
  uses). If the latest `release/e2e-production` is already `success` or
  `failure`, log a notice and exit 0. The contract becomes: "the record job
  opens the validation window only if it is currently closed"; closing and
  reopening is the operator's deliberate decision via the API. Add a test
  `test_release_e2e_record_does_not_overwrite_existing_verdict` to lock the
  contract.

---

### F-03 · `_latest_status` claims `created_at` breaks ties, but `max()` does not

- **Severity:** WARNING
- **Evidence:** `1082/scripts/check_release_evidence.py:60-73`. The function's
  docstring states *"The GitHub API lists newest first; `created_at` breaks
  ties explicitly so the decision does not depend on the ordering of the
  payload."* The implementation is
  `return max(matching, key=lambda item: str(item.get("created_at", "")))`.
- **Friction:** Python's `max()` with a key returns the **first element
  encountered** when keys tie (CPython semantics, stable). For two statuses
  on the same SHA with the same `created_at` (sub-second precision from the
  GitHub API for very fast successive POSTs, or any clock-skewed re-POST),
  the verdict depends on the payload order. The docstring's promise — "does
  not depend on the ordering of the payload" — is false for the tie case.
  Test `test_latest_status_wins_over_older_ones` in
  `1082/tests/test_check_release_evidence.py:122-128` only covers different
  timestamps; there is no test for same-second ties. The most likely real-world
  trigger: operator re-runs `gh api .../statuses/${SHA}` after a transient
  error, producing two statuses with identical or sub-second `created_at`.
- **Removable fix:** Replace `max()` with an explicit total-order pick. The
  GitHub statuses payload carries `id` (an integer that is strictly increasing
  for statuses on the same repo). Use `id` as the primary key and `created_at`
  as a secondary tiebreaker:
  ```python
  return max(matching, key=lambda item: (str(item.get("created_at", "")), int(item.get("id", 0))))
  ```
  Or sort with a stable key and pick the first:
  ```python
  return sorted(matching, key=lambda item: (str(item.get("created_at", "")), int(item.get("id", 0))), reverse=True)[0]
  ```
  Add `test_latest_status_is_stable_on_same_created_at` that injects two
  statuses with identical `created_at` and distinct `id`, and asserts the
  higher-`id` (newer) one wins regardless of payload order.

---

### F-04 · Pagination absent on `release/e2e-production` lookup

- **Severity:** WARNING
- **Evidence:** `1082/.github/workflows/deploy.yml:139` calls
  `${api}/commits/${prev_sha}/status` with no query parameters. The endpoint
  returns the latest statuses for a commit, capped at the per-context limit
  (GitHub default: 100 statuses per context per commit for newer endpoints;
  the unadorned `/status` endpoint is bounded similarly). The script
  `1082/scripts/check_release_evidence.py` reads `payload["statuses"]` and
  selects by `context == "release/e2e-production"`; if the relevant status
  is beyond the response's first page, the verdict becomes `absent` and the
  gate fails closed.
- **Friction:** In this repo, `release/e2e-production` is only ever set by
  the deploy workflow and re-set by operator (or re-set by the overwrite
  hazard in F-02). The realistic accumulation rate is low, so the practical
  risk for this repo today is small. However, the same `check_release_evidence.py`
  is documented as a "pure decision over a statuses payload so any audit
  job or operator can reuse it" (lines 10-12). If reused elsewhere with
  contexts that accumulate faster, the gap is real. There is also no test
  asserting that `evaluate()` survives a truncated statuses list where the
  `release/e2e-production` entry is not in the first page.
- **Removable fix:** Either (a) paginate the fetch in
  `release-e2e-gate` until the `release/e2e-production` entry is found or
  the response confirms exhaustion, or (b) use the `/commits/${sha}/status`
  response's `state` aggregate as a fast-path and only descend into the
  `/statuses` endpoint when the aggregated state is ambiguous. Add a test
  with a `statuses` list truncated before the `release/e2e-production`
  entry, asserting the verdict stays fail-closed (`absent`) and the error
  message names pagination.

---

### F-05 · API error semantics: HTTP 200 with malformed body produces exit 2, not exit 1

- **Severity:** WARNING
- **Evidence:** `1082/scripts/check_release_evidence.py:138-158` (CLI entry).
  The script returns `EXIT_USAGE_ERROR = 2` for `JSONDecodeError` and for
  argparse failures, and `EXIT_REFUSED = 1` for verdict refusals. The
  `release-e2e-gate` job at `1082/.github/workflows/deploy.yml:144` invokes
  `python scripts/check_release_evidence.py --sha "$prev_sha" < "$status"`.
  The job has no `set -o pipefail` mitigation and does not check the script's
  exit code for `2` separately. The deploy job at
  `1082/.github/workflows/deploy.yml:285` only declares
  `needs: [evidence, release-e2e-gate, ui-e2e-gate]`; any non-zero exit
  blocks the deploy — which is correct (fail-closed) — but the operator
  message will be one of:
  - `::error::statuses input is not valid JSON: ...` (exit 2), or
  - `::error::... refusal ...` (exit 1).
  Both fail the gate. The failure mode is uniform but the operator-visible
  signal differs by exit code and message prefix, which complicates triage.
- **Friction:** Operators reading the gate log after a red gate may infer
  different root causes from `2` (tool/JSON) vs `1` (verdict), and the runbook
  does not enumerate the exit codes or their meaning. The variable-based
  `main` gate at `main/.github/workflows/deploy.yml:84-111` returns one
  uniform `::error::` and one uniform `exit 1`, so the per-SHA design is
  already inconsistent with the simpler pattern it replaced.
- **Removable fix:** Collapse to a single refusal path: if the input is
  unreadable JSON, return `Verdict(ok=False, code="malformed", ...)` and
  exit `1`. Reserve `2` for CLI usage errors only (no `SHA` arg). This makes
  the operator's triage uniform: every red gate means the same family of
  causes (verdict refusal), and CLI misuse (forgotten `--sha`) is the only
  path that returns `2`. Add a test
  `test_cli_malformed_json_returns_one_with_malformed_code` to pin the
  contract.

---

### F-06 · Hidden failure of `release-e2e-record` after a successful deploy

- **Severity:** WARNING
- **Evidence:** `1082/.github/workflows/deploy.yml:479-517`. The job's `if:
  needs.deploy.result == 'success'` is correct, but its failure is **not
  surfaced** to the deploy job's summary (the deploy job's `if:
  needs.evidence.outputs.verified == 'true'` only checks `evidence`, not the
  record job). A failed `release-e2e-record` does not roll back the deploy
  — the new revision stays live, the operator does not get a notification
  framed around "the validation window did not open", and the next deploy's
  `release-e2e-gate` later fails with `absent` referencing a SHA that has
  been running in production for hours or days.
- **Friction:** The operator sees a green `deploy` job, a red
  `release-e2e-record` job, and may not connect the two until the next
  deploy fails. The `odd/tasks/909-e2e-release-gate.md` log already
  documents the post-#908 onboarding pattern of having to discover and
  manually register evidence for the first deploy. With F-02 and F-06
  together, the failure path is doubly invisible.
- **Removable fix:** Two complementary changes:
  1. Make `release-e2e-record` failure a release blocker for the
     **next** deploy by encoding its outcome into a marker the gate can
     read — the simplest is to also write `release/e2e-production=error`
     on the SHA when the POST itself fails. The operator sees a red status
     row pointing at the deploy run.
  2. Surface the failure in the deploy run summary via a GitHub Actions
     `::error::` notice from `deploy` if `needs.release-e2e-record.result != 'success'`
     (deploy job already knows the record job's result via `needs`).

---

### F-07 · Hard-coded `branch=main` in `release-e2e-gate`

- **Severity:** SUGGESTION
- **Evidence:** `1082/.github/workflows/deploy.yml:122`
  (`actions/workflows/deploy.yml/runs?branch=main&status=success`). The
  query hard-codes `main`. AGENTS.md operational premise P4 declares
  *"Pre-MVP single-branch. Todo el trabajo aterriza en `main` directamente;
  `staging` se reactiva solo por declaración explícita del usuario."*
- **Friction:** If `staging` is ever reactivated, the gate still queries
  `main` only. Deploys to `staging` would never see the gate's evidence
  because the per-SHA record is on `main` SHAs only. The current `main`-only
  workflow is consistent with P4 today; the latent gap is the assumption that
  P4 never flips.
- **Removable fix:** Replace `branch=main` with
  `branch=${GITHUB_REF#refs/heads/}` or read it from `github.event.repository.default_branch`.
  No urgency today; revisit when `staging` is reactivated.

---

### F-08 · `BYPASS_PREFIX` test covers trailing whitespace but not leading

- **Severity:** SUGGESTION
- **Evidence:** `1082/scripts/check_release_evidence.py:116-125` strips the
  reason after the prefix. Test
  `1082/tests/test_check_release_evidence.py:109-114` covers
  `description="skipped:   "` (trailing whitespace). It does not cover
  `description=":   skipped: reason"` (a leading colon, if some operator
  copy-pastes a prefix from a different status context) or
  `description="skipped:  reason  "` (extra internal whitespace).
- **Friction:** Not a real risk today; the prefix match is exact. Listed for
  completeness so the test coverage map matches the code surface.
- **Removable fix:** Add a parametrised test for `description` variants:
  empty after prefix, internal whitespace, leading colon, mixed case
  (`Skipped:` should not match — current code is case-sensitive and that is
  correct). Lock the surface.

---

### F-09 · `main` gate does not enforce per-release freshness of evidence

- **Severity:** WARNING (governance gap, accepted operability debt)
- **Evidence:** `main/.github/workflows/deploy.yml:84-111`
  (`release-e2e-gate` reads `vars.APAP_E2E_GATE_EVIDENCE`); and
  `main/docs/codebase/ci-cd.md:131-134` documents the trade-off explicitly:
  *"el gate garantiza que la evidencia quedó registrada, no su frescura por
  release"*. The variable persists between releases; an operator who records
  evidence ONCE leaves it set for every subsequent deploy.
- **Friction:** Today's gate blocks any release while the variable is empty,
  but once filled (and not cleared), every later deploy reads the same stale
  value. An operator forgetting to update it between releases is a silent
  correctness drift: the deploy proceeds with an "evidence was recorded once"
  baseline that may no longer match the deployed revision.
- **Removable fix:** This is the **exact** problem the per-SHA design in the
  branch solves. The branch's design supersedes the variable-based gate;
  the variable-based gate should be retired on the same PR that introduces
  the per-SHA contract, not coexist. The branch's design does this via
  `RETIRED_VARIABLE = "APAP_E2E_GATE_EVIDENCE"` plus the
  `assert RETIRED_VARIABLE not in workflow` test
  (`1082/tests/test_deploy_workflow.py:63`).

---

### F-10 · Main gate's `timeout-minutes: 5` is fine for the variable check, but the branch's gate adds two sequential 30s API calls

- **Severity:** SUGGESTION
- **Evidence:** `main/.github/workflows/deploy.yml:87` (`timeout-minutes: 5`)
  vs `1082/.github/workflows/deploy.yml:87` (same `timeout-minutes: 5`)
  with two `--max-time 30` curl calls back-to-back (lines 118 and 135 of the
  branch deploy.yml). Plus Python interpreter startup and `pip`/action
  setup.
- **Friction:** A single 30 s timeout on each curl is generous; two in series
  plus Python startup can approach the 5-minute budget if the GitHub API is
  degraded. The gate currently has no `set -o pipefail` between curl and
  Python either, so a slow curl + truncated body → `python` reads EOF →
  `JSONDecodeError` → exit 2.
- **Removable fix:** Raise the gate's `timeout-minutes` to `8` (small buffer
  over `5`), and add a `set -o pipefail` near `set -euo pipefail` (it is
  already there in the deploy.yml — verify by re-reading
  `1082/.github/workflows/deploy.yml:115`; the `set -euo pipefail` line is
  present at the top of the script, so this is mitigated; downgrade this
  finding to "verified fine, listed for completeness"). **Update**: F-10 is
  not a real finding; the deploy.yml already uses `set -euo pipefail`. Marked
  SUGGESTION only to record the verification.

---

### F-11 · `release-e2e-gate` job name reused across two contracts

- **Severity:** WARNING
- **Evidence:** `main/.github/workflows/deploy.yml:84` and
  `1082/.github/workflows/deploy.yml:84`. Both files declare a job named
  `release-e2e-gate`. On `main` it reads `vars.APAP_E2E_GATE_EVIDENCE`; on
  the branch it reads `release/e2e-production` on the previous SHA. The name
  is identical but the contract is different.
- **Friction:** Anyone reading the workflow history (the deploy.yml of last
  month and this month) sees the same job name and assumes the contract is
  unchanged. The branch's `release-e2e-record` job is new and the runbook
  cross-references have changed. There is no risk of misconfiguration in
  practice (only one deploy.yml is live at a time), but the `release-e2e-gate`
  name now means "gate the previous deploy's verdict" instead of "gate the
  next release's evidence" — a semantic flip without a rename. This is also
  the kind of drift that breaks `repository-delivery-governance` HR-21
  (stable required-check names) when a consumer depends on the name in
  branch protection or required checks.
- **Removable fix:** Acceptable as-is for the in-flight change, but record
  in the merge PR's notes that the semantic of `release-e2e-gate` flipped
  from "evidence-was-recorded" to "previous-deploy-was-validated". A future
  rename to `release-e2e-prev-verdict` would make the new contract explicit
  at the call sites; defer until at least one more deploy cycle confirms the
  new semantics.

---

### F-12 · Coolify webhook secret travels through env to Python helper (verified safe, listed for completeness)

- **Severity:** SUGGESTION (verified)
- **Evidence:** `1082/.github/workflows/deploy.yml:441-447` and
  `main/.github/workflows/deploy.yml:408-414`. Both pass
  `COOLIFY_WEBHOOK_SECRET` via `env:` to `python scripts/coolify_webhook.py`.
  The secret is never `echo`ed, never appears in `set -x` style traces
  (the script uses `set -euo pipefail` without `-x`), and is not part of
  `target_url` or any log line.
- **Friction:** None observed. Listed only because the brief asks about
  secrets exposure in deploy logs.
- **Removable fix:** None. **Keep.** See Keep-list K-03.

---

### F-13 · Runbook consistency with workflow — partial coverage

- **Severity:** WARNING
- **Evidence:** `1082/docs/runbooks/e2e-production.md` references
  `docs/runbooks/deploy-rollback.md` at lines 246, 329, and inside the
  record-evidence step at line 322 (`gh api` failure path). The rollback
  workflow lives in `1082/.github/workflows/deploy.yml:454-477`. The
  runbook text says "roll back the digest through `deploy-rollback.md`"
  when the verdict is `failure`. The actual rollback lives **inside the
  same `deploy.yml` job** as an `if: failure()` step (lines 454-477), not in
  a separate document or operator procedure. So `deploy-rollback.md` is a
  separate runbook for **manual** rollback (likely out of band), while the
  automated rollback is the `if: failure()` step. The runbook does not
  distinguish automated vs manual rollback paths.
- **Friction:** Operator reading the runbook after a verdict=`failure` may
  run manual rollback steps that conflict with the automated rollback path.
  The automated rollback also verifies `--revision "$PREVIOUS_REVISION"` via
  `scripts/verify_deployment.py`, which expects `/healthz` to return the old
  SHA. If the old SHA is `460c56f1` (and the bootstrap gate from F-01 has not
  been satisfied), the rollback succeeds mechanically but the gate on the
  next deploy still fails.
- **Removable fix:** In the runbook's failure path, distinguish:
  1. **Automated rollback** (in `deploy.yml`, only fires when
     `steps.promote.outcome == 'success'` and `previous_digest != ''`).
  2. **Manual rollback** (when automated did not engage; an outage already
     in flight; the operator uses `deploy-rollback.md` to redeploy an older
     digest manually).
  Add a sentence to the runbook at line 329: *"The automated rollback in
  `deploy.yml` only engages when the `promote` step succeeded and a previous
  digest exists. For any other failure shape, follow `deploy-rollback.md`."*

---

## Keep-list — patterns that are already excellent

These should be preserved when the per-SHA design lands, and are worth
citing in the future "perfect CI" skill (epic #935, per
`odd/tasks/ci-audit-friction-log.md`).

- **K-01 · Pure-decision module for evidence evaluation.**
  `1082/scripts/check_release_evidence.py:76-128` (`evaluate(payload, sha)`)
  is a pure function over a statuses payload. It is independently usable by
  any audit job, the deploy gate, or a CLI replay (`1082/scripts/check_release_evidence.py:138-158`).
  The verdict is a frozen `dataclass` (line 47) with stable codes (`absent`,
  `pending`, `failure`, `bypass`, `wrong-sha`, `malformed`,
  `bypass-without-reason`, `success`). Audit log lines name the SHA. This is
  the kind of seam that makes fail-closed gates testable in isolation
  (`1082/tests/test_check_release_evidence.py`). The GitHub API call is
  pushed to the calling workflow; the module does no I/O. **Keep.**

- **K-02 · SHA binding in evidence evaluation.**
  `1082/scripts/check_release_evidence.py:80-87` rejects evidence bound to
  any SHA other than the requested one with verdict `wrong-sha`. The test
  `test_evidence_for_another_sha_never_approves` in
  `1082/tests/test_check_release_evidence.py:50-56` locks this. Evidence
  for one revision never approves another. **Keep.**

- **K-03 · Coolify webhook secret never appears in deploy logs.**
  `1082/.github/workflows/deploy.yml:407-447` and `main/.github/workflows/deploy.yml:406-414`
  pass `COOLIFY_WEBHOOK_SECRET` only via `env:` to the Python helper; no
  `set -x`, no `echo "$COOLIFY_WEBHOOK_SECRET"`, no inclusion in
  `target_url` or `commit_message` bodies. **Keep.**

- **K-04 · Fail-closed aggregation in `release-e2e-gate`.**
  Both versions fail closed on any API error: `1082/.github/workflows/deploy.yml:123-126`
  for the previous-deploy query, `:140-143` for the verdict query; the
  branch's `tests/test_deploy_workflow.py:77-82` pins this with
  `section.count('!= "200"') >= 2`. **Keep.**

- **K-05 · Anti-self-exemption toll in `ui-e2e-gate` (issue #895).**
  `1082/.github/workflows/deploy.yml:210-222` forces `ui_changed=true`
  whenever any of the gate's own source files changes. Pinned by
  `1082/tests/test_deploy_workflow.py:171-184`. The toll prevents
  accidental self-exemption; the design comment at
  `1082/.github/workflows/deploy.yml:176-179` notes adversarial
  self-exemption is out of the threat model (single shared admin
  credential). **Keep.**

- **K-06 · Action pinning by SHA, not by tag.**
  `1082/.github/workflows/deploy.yml:33,103,107,138,171,268,301` and
  throughout: every `uses:` references an action by full commit SHA
  (`@3d3c42e5aac5ba805825da76410c181273ba90b1` etc.). Pinned by
  `1082/tests/test_deploy_workflow.py:95-96,137-138` (`re.search(r"@[0-9a-f]{40}$", ...)`).
  Consistent with `repository-delivery-governance` HR-11. **Keep.**

- **K-07 · Explicit degradation path for "first deploy" (the only
  exception in the per-SHA design).**
  `1082/.github/workflows/deploy.yml:127-132` short-circuits the gate when
  there is **no** previous successful deploy, exiting 0 with a notice. This
  is the only place the per-SHA design degrades open. The design is
  consistent except for the pre-existing-revisions gap (F-01). **Keep the
  pattern**, extend it per F-01.

- **K-08 · Bypass must record a reason.**
  `1082/scripts/check_release_evidence.py:116-125` refuses
  `success` with description `skipped:` (no reason after the colon) and
  returns verdict `bypass-without-reason`. Pinned by
  `1082/tests/test_check_release_evidence.py:109-114`. **Keep.**

- **K-09 · UTF-8 output pin.**
  `1082/scripts/check_release_evidence.py:131-135` pins `stdout`/`stderr`
  to UTF-8. Comment cites issue #488. Independent of the audit; a small,
  principled guard that prevents locale-dependent verdict messages. **Keep.**

- **K-10 · Permission least-privilege in gate jobs.**
  `1082/.github/workflows/deploy.yml:97-100` (`release-e2e-gate` has only
  `contents: read`, `actions: read`, `statuses: read`); `:494-496`
  (`release-e2e-record` has `contents: read`, `statuses: write`). Pinned
  by `1082/tests/test_deploy_workflow.py:84-96` and
  `:118-131`. **Keep.**

---

## Summary table

| ID | Severity | Area | One-line |
|---|---|---|---|
| F-01 | WARNING | epic #935 bootstrap | Per-SHA gate has a manual bootstrap for `460c56f1`; not automatic, not coded degradation |
| F-02 | CRITICAL | evidence overwrite | `release-e2e-record` overwrites any prior verdict on re-run; no test, no guard |
| F-03 | WARNING | tie-breaking | `_latest_status` claims `created_at` breaks ties; `max()` does not |
| F-04 | WARNING | pagination | `/commits/${sha}/status` not paginated; truncation → false `absent` |
| F-05 | WARNING | exit codes | `JSONDecodeError` returns `2` (USAGE_ERROR), inconsistent with `1` (REFUSED) |
| F-06 | WARNING | hidden failure | `release-e2e-record` failure not surfaced to deploy run summary |
| F-07 | SUGGESTION | branch scope | `branch=main` hard-coded; latent gap if `staging` reactivates |
| F-08 | SUGGESTION | test coverage | bypass-reason test surface incomplete |
| F-09 | WARNING | main only | variable-based gate has no per-release freshness; the per-SHA design supersedes it |
| F-10 | SUGGESTION | (verified) | `set -euo pipefail` already present; not a finding |
| F-11 | WARNING | naming | `release-e2e-gate` semantic flipped without rename |
| F-12 | SUGGESTION | (verified) | Coolify webhook secret travels via env only, not logged; not a finding |
| F-13 | WARNING | runbook | automated vs manual rollback path not distinguished in the runbook |

## Files inspected

- `main/.github/workflows/deploy.yml` (444 lines)
- `main/docs/runbooks/e2e-production.md` (381 lines)
- `main/docs/codebase/ci-cd.md` (200 lines)
- `main/tests/test_deploy_workflow.py` (209 lines)
- `1082/.github/workflows/deploy.yml` (517 lines)
- `1082/scripts/check_release_evidence.py` (162 lines)
- `1082/tests/test_check_release_evidence.py` (163 lines)
- `1082/tests/test_deploy_workflow.py` (215 lines)
- `1082/docs/runbooks/e2e-production.md` (447 lines)
- `1082/docs/codebase/ci-cd.md` (218 lines)

## Verification commands run (read-only)

- `git log --oneline -20` on `main`
- `git cat-file -t 460c56f1` (returns `commit`)
- `git merge-base --is-ancestor 460c56f1 HEAD` (true)
- `grep -r "release-e2e-record\|check_release_evidence\|release/e2e-production"` (only branch matches)
- `grep -r "APAP_E2E_GATE_EVIDENCE"` across `main` (workflow + 3 docs)
- `git log --all --oneline | grep -i "1110"` (no matches)
- `git worktree list` (confirms `1082-release-e2e-gate` worktree at `/home/ubuntu/repos/apap-app-worktrees/1082-release-e2e-gate`)
- `git log --oneline main..chore/1082-release-e2e-gate-per-sha` (3 commits ahead)
- `git diff --stat main..chore/1082-release-e2e-gate-per-sha` (8 files, 601+/113-)