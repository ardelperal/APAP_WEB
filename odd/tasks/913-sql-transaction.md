# 913 — SqlExecutor.transaction(): unit of work over a single connection

- Issue: #913 (finding A-01 of epic #911, audit 2026-09-24)
- Branch: `refactor/913-sql-transaction`
- Worktree: `../apap-app-worktrees/913-sql-transaction`
- Base: `origin/main` @ `b4f7246`

## Objective

Give the data layer a real transaction primitive. Today `LocalPostgresExecutor.execute_sql`
opens a fresh connection and commits per call (`app/core/local_backend/db.py`), so no
multi-statement write is atomic. Unblocks A-02 (#914), A-03 (#915), A-04 (#916).

## Design decisions

- New `TransactionalSqlExecutor(SqlExecutor)` Protocol in `app/core/data_access.py` with
  `transaction()` context manager. `SqlExecutor` stays unchanged so existing test fakes
  (implement only `execute_sql`) keep type-checking. Services needing atomicity depend on
  the new Protocol.
- `transaction()` yields a bound executor that satisfies `SqlExecutor` (existing helpers
  such as `record_event(client, ...)` work unchanged). COMMIT on clean exit, ROLLBACK on
  any exception, connection always closed.
- Nesting: calling `transaction()` on a bound executor raises explicitly (no savepoints).

## Scope

In: Protocol, `LocalPostgresExecutor` implementation, transactional test fake, integration
tests against real Postgres, docstrings. Out: migrating business flows (A-02..A-04),
connection pooling, `execute_sql` signature changes.

## TDD

- Mode: strict (source: user global config "Strict TDD Mode: enabled").
- Runner: `uv run pytest`; integration tests need `APAP_TEST_POSTGRES_DSN`.

## Tasks

- [x] T1 — Protocol + adapter + fake + integration tests (route: delegated writer; trigger:
      2+ non-trivial files). Checks: targeted tests, full `uv run pytest`, `mypy`, `ruff`,
      `check_rules.py`, size gates. Commits: `db059ce`, `23bc57e` (TRY300 ratchet fix after CI lint failure)
- [x] T2 — Open PR #925 (`Closes #913`, `Refs #911`, `Hallazgo: A-01`); size ≤400.

## Acceptance criteria

See #913.

## Progress / evidence

- T1 done (writer + parent correction). RED: ImportError NestedTransactionError, then AttributeError transaction; parent-added commit-failure test RED with raw UniqueViolation, GREEN after translating COMMIT errors.
- `pytest tests/integration/test_local_backend_transaction.py`: 7 passed. `mypy`: 0 errors (367 files). `ruff check/format`: pass. `check_rules.py`: pass. Size gates: OK.
- Full suite locally: 61-62 failed / 514 errors both on origin/main and branch (pre-existing env/test issues); `tests/integration/test_local_backend_db.py` 7 failures pre-existing on origin/main (calls nonexistent `.execute()`).
- Extra fix in scope: `pgcode`→`sqlstate` (psycopg3) in error translation; only affects unmounted `local_backend` API status mapping.
- RDD: on (global); assess risk=medium, review_due=false (`under_budget`).
- Diff vs origin/main: 3 files, +299/-23 = 322 lines.
- Engram mirror: PENDING (mem_save failed: multiple active runtime sessions).

## Next step

Done. #913 closed by PR #925 (merge b15004d) after PR #931 (merge e18f17d). Next: #914.

## Delivery strategy

- Strategy: `ask-on-risk` → user chose chain strategy `stacked-to-main` (2026-09-24) after the CRAP gate forced 411 lines of unit fakes (PR reached 762 lines).
- Slice A: `refactor/913-sql-executor-helpers` — helper extraction, sqlstate + COMMIT-error fixes, TRY300/CRAP baselines, unit tests for helpers/execute_sql. `Refs #913`.
- Slice B: `refactor/913-sql-transaction` (PR #925) — Protocol, NestedTransactionError, transaction(), bound executor, their unit tests, integration tests. `Closes #913`; base = slice A branch, retarget to main after A merges.
- Local safety branch: `backup/913-before-split` (d3210e8).
- CodeQL red on #925 = pre-existing alert #3 relocated (#118); user approved merging without dismissal.
- CI race found while doing this: #926.

## Chain status (2026-09-24)

- Slice A: PR #931 `refactor/913-sql-executor-helpers` @ 11be784 (commits 319f4ea, 11be784), 413 lines, `size:exception` approved by user (13 over; CRAP-required unit tests, see #929). Base: main @ cd62fa6.
- Slice B: PR #925 `refactor/913-sql-transaction` @ 4e6ccd3, 383 lines, base retargeted to slice A branch; retarget to main after #931 merges (ci.yml only runs for PRs into main/staging).
- execute_sql BASELINE_CRAP entry removed (grade A, CRAP 3.00).
- Code of the 4 code/test files is byte-identical to pre-split backup d3210e8.
- #926 race reproduced on #931 (ci cancelled by labeled events); rerun 36046072242.

## Closure (2026-09-24)

- PR #931 merged e18f17d (CodeQL review thread for pre-existing alert resolved with explanation; alert kept open, tracked in #934).
- PR #925 merged b15004d; #913 closed. Epic #911 A-01 ticked.
- Worktrees removed; remote branches kept (§15.2).
- Follow-ups created during this task: #926 (PR #936), #929, #932, #933, #934, #935 (CI epic), #937-#941.
