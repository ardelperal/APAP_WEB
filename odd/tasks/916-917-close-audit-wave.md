# Feature: 916-917-close-audit-wave

Close wave 1 of audit epic #911: issues #916 (A-04 chip cascade) and #917 (A-05 magic-link session).

## Constraints (from handoff obs #4156 + issues)

- Strict TDD: RED observed before GREEN; DB flows tested vs REAL Postgres (LocalPostgresExecutor, container `apap-code-pg` port 55915, DSN `postgresql://postgres:postgres@localhost:55915/postgres`).
- Branch `<tipo>/<N>-<slug>`; worktree `/home/ubuntu/repos/apap-app-worktrees/<N>-<slug>`; `uv sync --frozen --extra dev`.
- `uv run python -m pytest` (repo plugin needs it); integration tests need `pytestmark = pytest.mark.integration`.
- PR <= 400 lines; body `Closes #<own issue>` + `Refs #911` + `Hallazgo: A-0X`; never close other issues in prose.
- Merge only with ci + CodeQL green, zero unresolved threads, branch not behind main (`gh pr merge --merge`; never delete remote branches).
- Code agent must NOT touch `.github/`, `scripts/check_*`, pyproject gate config, CI docs.
- CRAP counts unit-test coverage only: new functions grade A (CC<=5) with unit coverage; ratchet baselines shrink-only.
- judgment-day review mandatory for A-04 and A-05.
- After merge: tick #911 checkbox with PR number, fill PR column in `docs/audits/code-audit-2026-09-24.md` (follow-up PR or same PR if allowed).
- Engram mirror topic_key: `apap/close-audit-wave-911`.

## Tasks

- [x] #916 A-04: verify P2 how dependent tables reference animal (animal_id vs denormalized chip); decide cascade fate.
- [x] #916 RED: integration test vs real provisioned schema (UndefinedColumn today).
- [x] #916 GREEN: real `transaction()`; remove `BEGIN_TX_SQL`/`COMMIT_TX_SQL`/`ROLLBACK_TX_SQL` via `execute_sql`; remove/replace nonexistent `chip` column updates.
- [x] #916 gates (make test-ci, mypy, ratchets, judgment-day) + PR + merge + tick #911.
- [x] #917 RED: integration test magic-link login then POST with csrf_token (403 today).
- [x] #917 GREEN: session parity with OAuth (`issue_csrf_to_session`, `user_id`, `rol` from auth_users). DECISION (user 2026-09-26): NO flag — only fix the middleware.py comment; the Settings.auth_enable_magic_link flag is deferred to a future issue.
- [x] #917 gates + PR + merge + tick #911 + closeout summary.

## Outcome (2026-09-26)

- #916 (A-04) → PR #996 MERGED. Saga rewritten: no nonexistent `chip` columns, real `transaction()`, guarded UPDATE race guard, decision D-43 + ADR d-43, full P3 doc sync. size:exception (1028 lines; test rewrite mandated + judgment-day P3 doc drift).
- #917 (A-05) → PR #1001 MERGED. Session parity with OAuth (issue_csrf_to_session + user_id/rol), fail-closed, log_safe events, comment fix (no flag per user decision). size:exception (905 lines; 705 tests + coverage restoration). gitleaks repin required 2 fix commits.
- judgment-day dual review on both: 0 SEVERE. Follow-ups: #1002 (redirect propagation), #1003 (case-sensitive email lookup), #1004 (login CSRF verify), #1005 (magic-link flag).
- Epic #911 checklist: A-04 → PR #996, A-05 → PR #1001 (ticked). Ola 1 complete (A-01..A-05).
- Pending: PR column of docs/audits/code-audit-2026-09-24.md (#912 still open, report file not yet created).
