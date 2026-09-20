# Prompt Template — embed in any sdd-apply delegation

Verbatim block to copy into any sdd-apply subagent prompt for web projects. Replaces language-specific workarounds with project-agnostic principles.

## Verbatim block

```
Test discipline: read `~/.config/opencode/skills/web-tdd-philosophy/SKILL.md` and `assets/fixture-patterns.md`, `assets/dependency-injection.md`, `assets/interface-seams.md`, `assets/test-quality.md`, `assets/tdd-loop.md` first. The web-TDD philosophy applies 1:1 to this slice. Mandatory patterns:

1. Fixture gate: every test sets up its own data via fixtures (mocks / seeded transactions / in-memory DBs / FakeRepository implementations). NEVER depend on rows that exist before the test runs. A test green by luck-of-data is invalid even if it's green.

2. Dependency injection: services take their external dependencies (Client, Repo, Logger, Clock, Notifier) as constructor or method parameters. Production wires real implementations via the project's DI container / Depends() / middleware / factory. Tests pass `FakeClient`, `InMemoryRepo`, `FakeClock`, etc. NEVER let a service call a global getter (singleton, module-level, `getCurrent*()`) for a side effect that the test wants to assert.

3. Cardinality before/after: any test that mutates (INSERT/UPDATE/DELETE/POST/PUT/PATCH) MUST assert `countBefore == N`, perform the mutation, assert `countAfter == N+1` (or whatever). Without cardinality, "test passed because no exception" is humo.

4. No humo: assert concrete values, not "no exception" or "is not None". `assert result.email == "alice@x.com"` not `assert result is not None`. `assert body["id"] == 42` not `assert "id" in body`.

5. Three paths per slice: every slice ships ≥1 happy + ≥1 sad + ≥1 edge atom. Happy = valid input → expected outcome. Sad = rejected input → expected error. Edge = boundary (null, empty, max length, max int, special chars).

6. Refactor-safety: assert OUTCOME (returned value, persisted state, observable side effect), not IMPLEMENTATION (specific SQL query sequence, method call order, internal flag). A behavior-preserving refactor MUST NOT break the suite. If it does, the test is wrong, fix or delete it.

7. Single harness form per project: exactly one way to set up tests per project. Two mocking strategies = bug, not flexibility. Pick `FakeClient` (or project's canonical pattern) and use it EVERYWHERE.

8. No mutation of production state: tests MUST NOT write to the production backend, real database, live external service, or shared mutable env. Use a sandbox / test-DB / in-memory store / `monkeypatch.setenv`.

9. Test module structure: top-down. Imports → constants → helpers / fixtures → tests (atoms). NEVER interleave helpers and atoms.

10. Helper signature must match atom signature EXACTLY: when a service signature changes, EVERY atom calling it must update in the same commit.

Apply these patterns. Reject any atom that:
- Depends on prod data
- Asserts only "no exception" or "is not None"
- Has no cardinality for mutations
- Covers only the happy path
- Tests implementation, not outcome

After implementation:
- Run the project's full test suite locally
- Run the project's linter + type checker
- Run the project's coverage gate (per project threshold)
- Run `code-review-expert` (or project's review lens) on the diff
- Attach a debt report if coverage is below the project's threshold
```

## Per-stack notes

The prompt above is generic. For stack-specific details, append ONE of these blocks:

### Python (FastAPI / Flask / Django)

```
Stack-specific Python patterns:
- Use `pytest` with `pytest-asyncio` for async tests
- Use `httpx.AsyncClient` + `ASGITransport` for FastAPI app testing
- Use SQLAlchemy `session.begin()` for per-test transactions (rollback at teardown)
- Use `pytest-postgresql` or per-test schema for real test-DB
- Use `monkeypatch.setenv` for env vars; never touch the real env
- Use `freezegun` or inject a `Clock` for time-dependent code
- Use `respx` for httpx mocking; use `pytest-httpx` for FastAPI/Starlette testing
- Coverage: `pytest-cov`; project threshold typically 80% on `app/`
- Fixtures: `conftest.py` for shared; per-test for isolated; default scope `function`
```

### Node / TypeScript (Jest / Vitest)

```
Stack-specific Node patterns:
- Use `jest` or `vitest` as test runner
- Use `@nestjs/testing` for NestJS apps; `supertest` for Express
- Use `nock` or `msw` for HTTP mocking
- Use `testcontainers` for real Postgres/Redis in CI
- Use `jest.useFakeTimers()` for time-dependent code
- Coverage: `jest --coverage`; project threshold typically 80% on `src/`
- Fixtures: `globalSetup` for once-per-suite, `beforeEach` for per-test
```

### Go

```
Stack-specific Go patterns:
- Use `testing` package + `testify` for assertions
- Use `gomock` or `mockery` for interface mocks
- Use `sqlx` with transaction rollback per test for real test-DB
- Use `httptest` for HTTP handler testing
- Coverage: `go test -cover`; project threshold typically 70% on `internal/`
- Fixtures: package-level `setupTestDB(t)` helper; use `t.Cleanup` for teardown
```

### Ruby (Rails / RSpec)

```
Stack-specific Ruby patterns:
- Use `rspec-rails` + factory_bot for Rails
- Use `database_cleaner-active_record` for per-test transaction rollback
- Use `webmock` or `vcr` for HTTP mocking
- Use `timecop` for time-dependent code
- Coverage: `simplecov`; project threshold typically 80% on `app/`
- Fixtures: factories in `spec/factories/`; traits for variants
```

### Java

```
Stack-specific Java patterns:
- Use JUnit 5 + Mockito for tests
- Use `@SpringBootTest` for integration tests; `@WebMvcTest` for controller tests
- Use Testcontainers for real DB / Redis in CI
- Use `WireMock` for HTTP mocking
- Use `java.time.Clock` injection for time-dependent code
- Coverage: `JaCoCo`; project threshold typically 80% on `src/main/`
- Fixtures: `@BeforeEach` for setup; `@AfterEach` for teardown
```

## Customization

For project-specific conventions, append ONE more block:

```
Project-specific conventions:
- [Project's mocking library]: e.g. `unittest.mock`, `gomock`, `jest.mock`, `rspec-mocks`
- [Project's test-DB URL pattern]: e.g. `postgresql://test:test@localhost:5432/test_db`
- [Project's coverage threshold]: e.g. "80% on `app/`, 60% on `tests/`"
- [Project's commit message convention]: e.g. "Conventional Commits" or "Trunk-Based Development"
- [Project's branch naming]: e.g. `feat/<issue-id>-<slug>`, `fix/<scope>`, `refactor/<scope>`
- [Project's review lens]: e.g. `code-review-expert`, `judgment-day`, `senior-reviewer`

If you find a tension between the project's convention and the principles above, the principles win (fixture gate, DI, cardinality, no humo, three paths, refactor-safety, single harness, no prod mutation, module structure, signature match).
```