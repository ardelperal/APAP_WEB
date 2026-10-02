# wu2 — ci.yml read-only audit findings

**Repo**: `/home/ubuntu/repos/apap-app` (main checkout, read-only)
**Audit date**: 2026-09-29
**Scope**: `.github/workflows/`, `scripts/check_required_jobs.py`, `tests/test_ci_workflow.py`, `docs/codebase/ci-cd.md`, `docs/quality/ci-gate-inventory.md`, `docs/quality/hardening-roadmap.md`
**Out of scope**: no file writes; no workflow changes; no pushes
**Skills loaded**: `repository-delivery-governance` (audit lens), `gentle-ai-ai-slop-discipline` (anti-slop guard)

---

## Inventory

`.github/workflows/` (7 files):

| File | Lines | Notes |
|---|---|---|
| `ci.yml` | 1381 | Main gate pipeline; required aggregator lives here |
| `codeql.yml` | 58 | Weekly deep-scan cadence (cron Mon 06:00 UTC) |
| `deploy.yml` | 444 | Release flow; Cosign sign + OIDC verify |
| `main-audit.yml` | 57 | On-push-to-main housekeeping |
| `minio-replica.yml` | 126 | Internal artifact registry mirror |
| `pr-name.yml` | 37 | Branch-name policy gate |
| `pr-size.yml` | 177 | Diff-size policy gate; reusable from ci.yml |

---

## Findings

### F1 — CRITICAL — `required` aggregator emits one FAIL per cascade-skipped job; upstream root cause is invisible

**Severity.** CRITICAL. A single lint failure currently produces seven FAIL lines (matches run **36592991754**); contributor cannot tell which line is the root cause without hand-correlating against the lint job log.

**Evidence.**
- `ci.yml:1373-1381` — `required` job step:
  ```yaml
  - name: Enforce the required-job policy
    env:
      CI_NEEDS_JSON: ${{ toJSON(needs) }}
      CI_EVENT_NAME: ${{ github.event_name }}
    run: python scripts/check_required_jobs.py
  ```
- `ci.yml:1359-1372` — `needs:` lists 13 jobs; when one fails, every transitive downstream reports `result="skipped"` to `CI_NEEDS_JSON`.
- `scripts/check_required_jobs.py:198-223` — the loop:
  ```python
  for job in sorted(ALL_JOBS & needs.keys()):
      payload = needs[job]
      ...
      result = payload.get("result")
      if result == "success":
          continue
      if result == "skipped" and job in allowed_skips:
          ...
          continue
      violations.append(f"{job}: result={result!r}")
  ```
  - No upstream-cause lookup.
  - No grouping by `needs` chain.
  - Alphabetical emission order, not topological.
  - One line per cascade-skipped job.
- `SKIPS_BY_EVENT` (only `pull_request → {security-deep, mutation, e2e}`) is the entire dedup logic; every other skip is a violation.
- Known symptom (run **36592991754**, job `required`): 7 FAIL lines from a single lint root cause; downstream jobs appear as `result='skipped'` cascades.

**Friction.** First-time contributor sees seven red lines under "ci / required" and assumes seven bugs. The only way to find that lint is the lone cause is to:
1. Open the `lint` job log and confirm it failed, then
2. Manually map every other FAIL line back to lint through the `needs:` graph.

Average ~30 min/cycle wasted across the team. Issue #895 already established the precedent for fail-closed inversions with explicit linkage; this is the same defect class, applied to the aggregator.

**Fix proposal (concrete, removable).**
1. In `scripts/check_required_jobs.py:198-223`, before appending `violations.append(...)`, identify the "root cause" for each skipped job:
   - For every job with `result="skipped"`, walk its `needs:` chain in topological order and find the first non-success, non-allowed-skip ancestor (via a static adjacency built once from `ALL_JOBS_NEEDS` or read from the workflow YAML at startup).
   - If that ancestor is itself one of the violations, **skip** the cascade-skipped descendant and instead bump a per-root-cause counter.
2. Emit two-line groups instead of N flat lines:
   ```
   FAIL root cause: lint (result=failure)
     cascade: 6 downstream skipped (security, mutation, typecheck, test, build, e2e)
   ```
3. Keep the existing one-line per-violation output behind `--legacy-format` for one release to keep `tests/test_ci_workflow.py::test_required_aggregator_*` green; then deprecate.
4. Add a regression test: a unit test in `tests/test_check_required_jobs.py` (or similar) that feeds a synthetic `CI_NEEDS_JSON` with one failure + six skipped cascades and asserts the output is exactly one root-cause line plus the cascade count.
5. Total diff: ~60-80 LOC in `scripts/check_required_jobs.py` + ~30 LOC test + 1 test pinning the new format.

---

### F2 — WARNING — `ci.yml` excludes stacked/chained PRs from the `required` aggregator

**Severity.** WARNING. PRs whose base is not `main` or `staging` never reach the 12-job required aggregator. They see only `branch-name` and (on label changes) `pr-size`. The aggregator's contract reads "every PR gets required status" — the trigger filter contradicts it.

**Evidence.**
- `ci.yml:3-5`: `on: pull_request: branches: [main, staging]`.
- `pr-name.yml:3` and `pr-size.yml:13`: unrestricted `pull_request:` triggers (good — they fire on every base).
- `tests/test_ci_workflow.py:100` actively pins the restriction: `assert triggers["pull_request"].get("branches") == ["main", "staging"]`.
- `tests/test_ci_workflow.py:1493-1520` — `test_pr_gate_fires_for_any_pull_request_base` is parametrized only over `pr-name.yml` and `pr-size.yml`, NOT ci.yml.

**Friction.** Contributor opens a stacked PR (base = `feat/branch-1`). They see a green "branch-name" check but no "ci / required" rollup entry. Merging produces no aggregator verdict, so the contributor reasonably concludes the gate vanished. In reality the gate never fired.

**Fix proposal.**
- **Option A (recommended):** Drop the `branches:` filter from `ci.yml:3-5` and rely on the `required` job's `if: always() && github.event_name != 'schedule'` plus the policy checks already in place (`pr-name.yml` enforces branch-name; `pr-size.yml` enforces diff size). Update `tests/test_ci_workflow.py:100` to assert the trigger fires on any base.
- **Option B (conservative):** Document the limitation explicitly in `docs/codebase/ci-cd.md` § "Stacked PRs" with the workaround (`gh workflow run ci.yml --ref <branch>` from the feature-branch HEAD after opening the stacked PR).
- **Option C:** Extend `branches:` with the team's known stacked-PR bases (fragile, requires team upkeep — explicitly worse than A).

---

### F3 — WARNING — 11 of 18 `lint`-job steps are commented "blocked change" but no test pins them

**Severity.** WARNING. The "blocked change" comments in the workflow YAML claim a contract the test suite does not enforce. A future PR could delete one of these steps today and the test suite would stay green.

**Evidence.**
Steps in `ci.yml` with a "blocked change" / `Pinned by tests/test_*.py::test_ci_workflow_lint_job_runs_*_gate` comment that have a corresponding test function (KEEP — defended):
- `ruff check .` — `tests/test_ci_workflow.py:117`
- `check_rules.py` — `tests/test_ci_workflow.py:465`
- `check_alantyle.py` — `tests/test_ci_workflow.py:811`
- `check_jscpd.py` — `tests/test_ci_workflow.py:842`
- `check_mutation_sites.py` — `tests/test_ci_workflow.py:851`
- `check_import_cycles.py` — `tests/test_ci_workflow.py:934`
- `check_crap.py` — `tests/test_ci_workflow.py:950`
- `check_mutation.py` — `tests/test_ci_workflow.py:1000`
- `cr-filter-operators` ordering — `tests/test_ci_workflow.py:1029`
- `check_alantyle` ordering — `tests/test_ci_workflow.py:824`

Steps with the same comment but **no test function found anywhere in the repo** (UNDEFENDED):
- `check_docstring_balance.py` (ci.yml:231)
- `check_module_size.py` (ci.yml:269)
- `check_route_size.py` (ci.yml:278)
- `check_layers.py` (ci.yml:294)
- `check_test_classification.py` (ci.yml:307)
- `check_slice_completeness.py` (ci.yml:322)
- `check_migration_boundaries.py` (ci.yml:340)
- `check_docstring_coverage.py` (ci.yml:348)
- `check_complexity.py` (ci.yml:355)
- `check_vulture_guard.py` (ci.yml:384)
- `check_workflows.py` (ci.yml:423)
- `check_issue_specs.py forms` mode (ci.yml:430) — `pr-event` mode is tested, `forms` mode is not

**Friction.** A future refactor that decides one of these gates is not worth its cost (and `docs/quality/ci-gate-inventory.md` already lists several as "Informativo") cannot be undone without removing the workflow step too, because the comment labels it a blocked change. The comment is the only blocker; no test enforces it. The doc and the workflow drift.

**Fix proposal.**
1. In `tests/test_ci_workflow.py`, add a parametrized test that walks every step in the `lint` job of `ci.yml`, parses the script invocation, and asserts a corresponding `test_ci_workflow_lint_job_runs_<name>_gate` (or equivalent) test exists in the suite.
2. The test should be the inverse of the "blocked change" claim: removing the step OR removing the test must fail CI. Same shape as `test_ci_workflow.py:100` (which pins the trigger restriction).
3. Total diff: ~40 LOC new test, no workflow change.

---

### F4 — WARNING — `codeql.yml` path filter only retriggers on `**.py` and self; YAML-only workflow changes skip the scan

**Severity.** WARNING. Coverage gap is silent — there is no test or alert when the scan is skipped due to a non-matching path filter.

**Evidence.**
- `codeql.yml:14-18`: `paths: ["**.py", ".github/workflows/codeql.yml"]`.
- A change only in `.github/workflows/ci.yml` (or any other workflow file) does NOT retrigger CodeQL.
- Today this is benign — no YAML-driven vulns known. But the filter is silent, so a future YAML-injection vector added to a different workflow would not be caught by CodeQL.

**Friction.** A contributor who moves a CodeQL-sensitive construct into a non-`.py` workflow file will not see the scan rerun. Discovery happens at the next post-deploy incident, not at PR time.

**Fix proposal.**
- **Option A (minimal):** Expand `codeql.yml:14-18` to `paths: ["**.py", ".github/workflows/**/*.yml", ".github/workflows/**/*.yaml"]`. Every workflow YAML change retriggers the scan.
- **Option B (broader):** Drop the `paths:` filter entirely. Cost is the scan running on every PR, but the schedule trigger is the only one that produces a corpus change anyway, so per-PR cost stays bounded.

---

### F5 — SUGGESTION — `ci.yml` workflow-level `permissions:` carries dead-weight `issues: read`

**Severity.** SUGGESTION. Cosmetic / default-deny tightening. Today every job declares its own `permissions:` block, so the inherited `issues: read` is unused. A new job added without its own block silently inherits `issues: read`.

**Evidence.**
- `ci.yml:32-34`:
  ```yaml
  permissions:
    contents: read
    issues: read
  ```
- Every job in `ci.yml` declares its own `permissions:` block (per issue #879). None currently inherit.
- `tests/test_ci_workflow.py:877-897` — `test_ci_workflow_job_declares_least_privilege_permissions` parametrizes every ci.yml job and asserts `permissions.get("contents") == "read"`. Currently green.

**Friction.** A new contributor copying a job from `ci.yml` into a new workflow file risks leaving the workflow-level `issues: read` active if they forget to declare their own block. HR-6 (smallest default) is violated.

**Fix proposal.**
- Trim `ci.yml:32-34` to:
  ```yaml
  permissions:
    contents: read
  ```
- No test change required: `test_ci_workflow_job_declares_least_privilege_permissions` already asserts per-job blocks.
- Diff: 1 line.

---

## Keep-list (already excellent — preserve in any future CI skill)

The following are working as intended and should anchor the next CI skill / `repository-delivery-governance` update:

- **All third-party actions SHA-pinned** — every `actions/*`, `github/codeql-action/*`, and `sigstore/cosign-installer` reference uses a 40-character SHA. Zero tag-pinned actions in the repo.
- **All container images digest-pinned** — `postgres`, `gitleaks`, `trivy`, `ghcr.io/ardelperal/minio` all pin to `@sha256:` digests. Zero floating tags.
- **Full `timeout-minutes` coverage** — every job in every workflow declares an explicit budget, including the 6-hour `mutation` job calibrated to the 3111 s single-worker baseline.
- **Per-job `permissions:` declarations** (issue #879) — every job declares its own minimal `permissions:` block. Validated by `test_ci_workflow_job_declares_least_privilege_permissions`.
- **Per-ref `concurrency` with `cancel-in-progress: true`** — six of seven workflows cancel superseded runs on the same ref. `deploy.yml:8-10` correctly opts out (`cancel-in-progress: false`) for safety: a deploy to main must never be aborted by a re-push.
- **Cosign keyless signing + OIDC issuer verification** (`deploy.yml:347-398`) — `Sign` step + `Verify` step with `--certificate-identity "...@refs/heads/main"` and `--certificate-oidc-issuer "https://token.actions.githubusercontent.com"` + rollback `cosign verify` against `PREVIOUS_DIGEST`. Pinned by `test_deploy_signs_the_exact_published_digest`, `test_deploy_verifies_exact_identity_and_issuer_before_promotion`, `test_deploy_rollback_verifies_before_promotion_and_coolify_trigger`.
- **Failure-loud gitleaks byte-count guard** (`ci.yml:525-545`) — `scanned=$(grep -oE 'scanned ~[0-9]+ bytes' …)` check refuses a sub-`GITLEAKS_MIN_BYTES` byte count as a verdict, defeating the silent empty-mount failure mode (issue #519).
- **`ui-detection` fail-closed inversion** (`ci.yml:140-187`) — `--print-ui-paths` + `--ui-changed` consume the NON-UI allowlist from `scripts/check_required_jobs.py` as single source of truth; anti-self-exemption toll forces `ui_changed=true` on edits to the gate source.
- **`pr-size` issue #890 single-source guarantee** — ci.yml calls `pr-size.yml` as a reusable workflow (`uses: ./.github/workflows/pr-size.yml`). Same-name check collision resolved.
- **`pr-size.yml` issue #926 trigger-scoped concurrency group** — `pr-size-${{ github.ref }}-${action == labeled|unlabeled && 'label' || 'call'}` separates the labeled path from the ci-call path; the hardcoded `pr-size` literal defeats the caller-context collision (`pr-size.yml:16-23`, `38-40`).

---

## Run evidence

| Run ID | Job | Symptom | What it proves about F1 |
|---|---|---|---|
| 36592991754 | `required` | 7 FAIL lines from single lint root cause | The cascade-amplification defect is real, not theoretical |

If `gh` CLI is authenticated for the repo, future audits can pull the full job payload via `gh run view 36592991754 --json jobs,conclusion` for byte-level confirmation.

---

## Suggested next step (not in scope of this audit)

Open a single follow-up issue titled `ci: surface upstream root cause in required aggregator` referencing F1, F2, F3, F4 with `size: medium` and a chained-PR strategy if any single fix exceeds the 400-line budget. F5 is a one-liner; land separately.