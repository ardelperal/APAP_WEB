# #1193 → #1194 chain completion — issue #1160 second wave (2026-10-01)

## Anomaly handled

`allow_update_branch` enables but does not guarantee auto-update: #1193 had auto-merge
armed, all checks green on head `9fa14bd`, but `mergeStateStatus: BEHIND` — main had
drifted ×4 (#1202, #1200, #1197, #1162-docs) and GitHub did not update the branch on its
own. The actor triggered the update via the REST endpoint.

## Timeline

| Time (UTC) | Event |
|---|---|
| 22:0x | `PUT /pulls/1193/update-branch` → 202 "Updating pull request branch." |
| +~2 min | New head `60f3fc6`; CI re-run (Actions 36932014617 / 36932014619 / 36932014897). |
| 22:08 | All checks green: branch-name, pr-size, ui-detection, issue-spec, lint, security, typecheck, integration, test (8m40s), verify-fallback-ready, build, required, CodeQL, CodeQL (Python) 2m10s, GitGuardian. Skip states: `e2e`, `mutation`, `security-deep`. No red. |
| 22:09:00 | Auto-merge fired → **#1193 MERGED**, merge SHA `9b2f4778d22c3ade4054ad81c80a226960e7c31e`. |

## PR #1194 handoff

1. `PATCH /pulls/1194 -f base=main` — retarget from `fix/1160-e2e-client-semantics` (consumed by #1193's merge) to `main`. Clean, no conflicts.
2. `PUT /pulls/1194/update-branch` → 202; head advanced `d1c4b63` → `1c5e78c` (absorbs #1193's merge commit — expected drift during retarget, per plan).
3. `gh pr merge 1194 --auto --merge` — armed at 22:10:01Z (MERGE method, enabled by ardelperal).
4. Single CI poll: all checks pending (Actions 36933360944 / 36933360978 / 36933361330), GitGuardian pass, `mergeable: MERGEABLE`, `mergeStateStatus: BLOCKED` (only because checks are running). GitHub owns completion; no RED observed at poll time.

## Friction for the playbook (Regla 19/20 refinement)

Confirmed pattern, second wave in a row:

> **`allow_update_branch` enables but does not guarantee auto-update — the actor must
> trigger `update-branch` after each base drift during an armed wave.**

Notes:
- GitHub will happily hold an armed PR in `BEHIND` indefinitely; green-on-stale-base does
  not degrade or warn.
- After the actor-triggered update, the re-run of the identical content was fully green
  (matches previous wave run 36919393193), and auto-merge fired within ~1 min of green.
- Stacked PR retarget: after the parent merges, the child's base must be explicitly
  flipped (`PATCH base=main`) *before* `update-branch`, otherwise the update targets the
  stale parent branch and can no-op. The update then reports the merge-commit drift.
- Poll convention: one armed-state check after arming is enough — GitHub owns completion;
  do not babysit the child PR.

## Final confirmation (22:28 UTC, 2026-10-01)

Poll loop (5-min cadence, 45-min cap, stop-on-red): one red-free poll at 22:18 (all checks
still running, none failing), then **#1194 MERGED at 22:21:50Z** on the second poll.

| Item | Observed |
|---|---|
| #1194 state | `MERGED`, mergedAt `2026-10-01T22:21:50Z` |
| #1194 merge SHA | `20b6a3c7119df19e5294f90b14c1833777affb50` |
| #1160 state | `CLOSED`, closedAt `2026-10-01T22:21:51Z` (auto-closed 1s after merge, via Closes #1160) |
| Remote branch ♾️ | `refs/heads/fix/1160-e2e-auth-gate-suites` → `1c5e78c` present in `git ls-remote` (preserved, not deleted) |

**Second wave complete.** #1193 → #1194 chain merged; issue #1160 (segunda ola de suites
e2e impasables) closed. Checks at merge time: only `test` / `integration` had been
pending at 22:18; no check ever went RED — no intervention needed, GitHub-owned
completion confirmed.
