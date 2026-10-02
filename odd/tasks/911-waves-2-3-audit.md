# Feature: 911-waves-2-3-audit

Close olas 0/2/3 of audit epic #911 (code wave). #918 left to the CI-epic agent (user decision 2026-09-26: pyproject/.github is CI-agent territory).

## Queue

- [ ] #912 (D-00): docs/audits/code-audit-2026-09-24.md report with hallazgo -> issue -> PR traceability; fill PR columns (A-01 #925/#931, A-02 #975, A-03 #983, A-04 #996, A-05 #1001, A-12 #946, A-13 #946/#950/#951/#961/#965, A-14 #948; A-06 #918 pending CI agent).
- [ ] #919 (A-07): IDOR materiales de estancia + urlencode redirects. Parallel with #920 (disjoint files). judgment-day mandatory.
- [ ] #920 (A-08): schema identifier SQL Identifier, trust_xff trusted_proxies, X-Request-ID validation + runbook. Parallel with #919. judgment-day mandatory. If >400 lines: chained PR splitting X-Request-ID.
- [ ] #921 (A-09): AFTER #920 merges (both touch app/core/schema_provisioning.py). Move catalog DDL out of tests import, drop _case_variants, replace assert guard.
- [ ] #922 (A-10): remove xfail (fixture-restored seam), rate-limit concurrency test, tasks retries tests, update test-audit.md.
- [ ] #923 (A-11): needs product decision -> ask user before implementing.

## Standing constraints

Same as handoff #4156: strict TDD RED->GREEN, real Postgres (apap-code-pg:55915), worktree per issue, uv sync --frozen, PR Closes #own + Refs #911 + Hallazgo: A-0X, judgment-day dual review, merge only CI+CodeQL green + not behind (merge-forward accepted), tick #911 checkbox after merge, never delete remote branches, no AI attribution.
