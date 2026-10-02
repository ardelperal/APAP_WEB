# Feature: audit-followups-mini-wave

Drain the 5 remaining audit-2026-09-24 approved follow-ups in 3 conflict-free lanes (background workers; parent stays free to attend the user).

## Lanes

- [ ] Lane A: #1004 login CSRF on /auth/magic/verify → then #1005 Settings.auth_enable_magic_link flag (same territory, sequential).
- [ ] Lane B: #1002 disabled-user redirect propagation + guardian → then #1019 require_authorized_user routes without role check (same territory, sequential).
- [ ] Lane C: #1008 GET /acogidas/new consumes (or drops) the asignar redirect contract.

## Standing constraints

Handoff #4156 rules: strict TDD RED→GREEN, real Postgres (apap-code-pg:55915), worktree per issue, branch <tipo>/<N>-<slug>, PR Closes #own + Refs #911, judgment-day where issue mandates, merge only CI+CodeQL green + not behind (merge-forward accepted; NEVER tick epic/report rows before merge actually succeeds), size:exception documented if >400, never delete remote branches, no AI attribution. Background workers report via handoff; parent commits and opens PRs.
