# Mapping from `access-vba-tdd-fundamentos` to `web-tdd-philosophy`

This file is a bridge for agents who learned the Access/VBA TDD skill and want to apply the same principles to web projects. Each VBA concept maps to its web equivalent.

## Section-by-section mapping

| `access-vba-tdd-fundamentos` section | Web equivalent in `web-tdd-philosophy` |
|---|---|
| §0 TL;DR — 5 conditions | Hard Rules 1-5 (fixture gate, DI, cardinality, no humo, three paths) + Rules 6-10 (refactor-safety, single harness, no prod mutation, module structure, signature match) |
| §0.1 `Public Function Test_X() As String` returning JSON | `def test_x() -> None` raising `pytest.fail(...)` on assertion miss; `caplog` for logs; `assert` for values |
| §1.1 Runner contract (COM capture) | pytest's normal test runner captures raises/asserts directly; no JSON wrapper needed |
| §1.1.1 Convention Dysflow-friendly for discovery | pytest test discovery: file naming `test_*.py`, function naming `test_*` |
| §1.2 Fixture gate | Hard Rule 1 + `assets/fixture-patterns.md` |
| §1.3 Schema-first | `assets/fixture-patterns.md` "Database-backed tests (transaction rollback)" + reading the ORM model before INSERT |
| §1.4 DAO injection | Hard Rule 2 + `assets/dependency-injection.md` |
| §1.6 Naming convention (no module/function collision) | Hard Rule 9 (module structure: imports → constants → helpers → atoms); not relevant for Python since names live in different namespaces |
| §1.7 Inter-test isolation | `assets/fixture-patterns.md` "Two-layer fixtures" + per-test transaction rollback; pytest's `function`-scope fixtures by default |
| §1.8 Test module structure | Hard Rule 9 (top-down: imports → constants → helpers → atoms) |
| §1.9 Pre-compile audit (VBA landmines) | Hard Rule 4 (`pytest --collect-only` pre-merge); for Python: linter + type checker + import sanity |
| §1.10 Test atom signature MUST match helper signature | Hard Rule 10 — applies to ANY language; when service signature changes, all tests update atomically |
| §2 JSON contract | `assert` statements with explicit expected values; pytest's failure messages replace JSON contracts |
| §3 Testing mode + sandbox | `conftest.py` autouse fixtures; `monkeypatch`; `pytest --base-url=` for env-flag gating |
| §3.1 Singleton `getdb()` problem | Hard Rule 2 (DI) — solves the same problem at the language level: don't use singletons in production code, inject |
| §3.2 `m_TestingMode` global | pytest session-scoped fixtures + `pytest.ini` env vars |
| §3.3 `getdb()` interprets mode | The DI container's factory function interprets env (e.g. `if env == 'test': return FakeClient()`) |
| §3.4 `BeginTestSession` / `EndTestSession` | `conftest.py` autouse fixture with session scope for setup, function scope for teardown |
| §3.5 `Test_EVE(True/False)` | `conftest.py` fixture that runs once at session start + once at end |
| §3.6 Pre-check of production (UNC, fingerprint) | Env-var check in `conftest.py`; if `DATABASE_URL` starts with prod pattern, skip |
| §3.7 `ResetTestSession` cleanup | `try/finally` in `conftest.py` fixture; pytest's `autouse=True` with yield guarantees cleanup |
| §3.8 Cache invalidation | N/A in Python; or use `lru_cache` with explicit reset |
| §4 Quality — north star, no humo, coverage, assertions, cardinality, seams, smoke vs atomic, debt report | All covered in `assets/test-quality.md` + Hard Rules 4, 6, 8 |
| §4.1 Refactor-safety | Hard Rule 6 |
| §4.2 No humo | Hard Rule 4 |
| §4.3 Coverage 80% floor | `assets/test-quality.md` "Coverage as floor + diagnostic, never as goal" |
| §4.4 Strong assertions | Hard Rule 4 + `assets/test-quality.md` "Three paths per slice" |
| §4.5 Cardinality before/after | Hard Rule 3 |
| §4.6 Seams + interfaces | `assets/interface-seams.md` |
| §4.7 Smoke vs atomic separation | `assets/test-quality.md` "Smoke vs atomic — separation mandatory" |
| §4.8 Debt report | `assets/test-quality.md` "Debt report — when coverage is below floor" |
| §4.9 Single harness form | Hard Rule 7 |
| §4.10 Prohibited mutation of config | Hard Rule 8 |
| §5 Fixture patterns | `assets/fixture-patterns.md` |
| §5.1 Test ID ranges | `assets/fixture-patterns.md` "Database-backed tests" — UUIDv4 deterministic for tests, or transaction scope |
| §5.2 Two-layer fixtures | `assets/fixture-patterns.md` "Two-layer fixtures" |
| §5.3 Transaction vs DELETE/INSERT | `assets/fixture-patterns.md` "Database-backed tests (transaction rollback)" |
| §5.4 DB injection pattern | `assets/dependency-injection.md` |
| §5.5 Per-test temp `.accdb` | `assets/fixture-patterns.md` "In-memory DB" + per-test schema |
| §5.6 Anti-patterns | `assets/fixture-patterns.md` "Anti-patterns — REJECT in code review" + `assets/test-quality.md` "Anti-patterns — REJECT in code review" |
| §6 Performance telemetry | `assets/tdd-loop.md` "Time budget" |
| §7 Security of data (no prod mutation) | Hard Rule 8 |
| §8 TDD loop for IA | `assets/tdd-loop.md` (the same 8 steps, web-equivalent commands) |
| §8.1 COM AutoExec | N/A for web — `conftest.py` autouse fixtures replace AutoExec-style startup |
| §8.2 Timeouts MCP | CI logs + `pytest --tb=long` for failure trace; for Playwright: `--headed=false` + retries in config |

## Principles that translate 1:1 (no language-specifics)

These Hard Rules apply regardless of language:

- **Fixture gate** (test data independence) — Hard Rule 1
- **Dependency injection** — Hard Rule 2
- **Cardinality before/after** — Hard Rule 3
- **No humo** (assert concrete values) — Hard Rule 4
- **Three paths per slice** — Hard Rule 5
- **Refactor-safety** (assert outcome not implementation) — Hard Rule 6
- **Single harness form per project** — Hard Rule 7
- **No prod mutation** — Hard Rule 8
- **Test module structure** (top-down) — Hard Rule 9
- **Signature match between helper and atom** — Hard Rule 10

## VBA-specific concepts that DON'T translate (skipped intentionally)

These VBA mechanics have no web equivalent and were stripped from `web-tdd-philosophy`:

- `Public Function` returning JSON for COM capture (Python returns None or raises)
- `m_TestingMode` global flag (Python uses pytest fixtures)
- `DAO.Database` injection (Python uses `Client`/`Repo`/`Clock` interfaces)
- `Application.Run` for test discovery (Python uses pytest's auto-discovery)
- VBA line-continuation landmines (`, _` with comment)
- `DbEngine.OpenDatabase` (Python uses SQLAlchemy / Knex / pgx / database/sql)
- `Dysflow` import cycles (Python uses pytest directly)
- `MsgBox` blocking COM (Python uses pytest's `caplog` / `capsys`)
- `BuildJsonOk` / `BuildJsonFail` helpers (Python uses `assert` directly)

## Cross-reference for cross-trained agents

If you learned `access-vba-tdd-fundamentos` first and are now applying `web-tdd-philosophy`:

1. **Same rigor**: both skills enforce Hard Rule 1-10 with no weasel language.
2. **Different primitives**: web stacks have better primitives (pytest fixtures, DI containers, async, in-memory DBs) that make some VBA workarounds obsolete.
3. **Same shape**: 3-path coverage per slice + DI + cardinality + no humo + refactor-safety + single harness.
4. **Different ops**: web projects run in containers / CI; VBA projects run on Windows + Access. Web testing is faster (μs vs ms) and more parallelizable.

When in doubt about a web-specific test, default to the principle from `access-vba-tdd-fundamentos` and find the web equivalent. Don't invent a new rule.

## For projects that span both (Access legacy + new web)

Some projects (like APAP_WEB) have an Access legacy AND a new web rewrite. Both skills apply, in different layers:

- **Access legacy code**: `access-vba-tdd-fundamentos` (no change)
- **New web code**: `web-tdd-philosophy`
- **Migration tests** (legacy data → new schema): `web-tdd-philosophy` for the new schema's tests, plus the migration engine's own contract

The two skills complement each other; they're not alternatives. A project with both Access and web code uses both, scoped to the right layer.