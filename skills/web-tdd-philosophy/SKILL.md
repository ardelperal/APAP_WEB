---
name: web-tdd-philosophy
description: Trigger: TDD, fixture-first, refactor-safety, dependency injection, no humo, cardinality, Playwright E2E, harden a test suite. Apply web-TDD discipline to any web project (Python, Node, Go, Ruby, etc.) without VBA noise.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 1.0
  last_verified: 2026-09-05
  scope: ['web', 'runtime']
  auto_invoke: ['running TDD on a web component']
  tiers: ['web', 'runtime']
---



# web-tdd-philosophy

> Hard-edged TDD discipline for any web project. Generic across Python (pytest), Node (Jest/Vitest/Mocha), Go (testing/std/testify), Ruby (RSpec/Minitest), Java (JUnit), etc. Project-agnostic.

## Activation Contract

Invoke when:
- Writing a new test slice for any feature/bugfix/refactor
- Auditing or hardening an existing test suite
- Deciding unit vs integration vs E2E coverage
- A test passes by luck (depends on prod data, environment, or shared mutable state)
- Reviewing a PR's tests for refactor-safety

Do NOT invoke for: trivial getters/setters, framework boilerplate tests, performance benchmarks.

## Hard Rules

1. **Fixture gate (HARD)** — every test sets up its OWN data via fixtures (in-memory DB, mocked client, seeded transaction, FakeRepository). NEVER depend on rows that exist before the test runs. A test green by luck-of-data is invalid even if it's green.

2. **Dependency injection (HARD)** — services take their external dependencies (`Client`, `Repo`, `Logger`, `Clock`, `Notifier`) as constructor or method parameters. Production wires real implementations via the project's DI container / `Depends()` / middleware / factory. Tests pass `FakeClient`, `InMemoryRepo`, `FakeClock`. NEVER let a service call a global getter (singleton, module-level, `getCurrent*()`) for a side-effect the test wants to assert.

3. **Cardinality before/after (HARD)** — any test that mutates (INSERT/UPDATE/DELETE/POST/PUT/DELETE/PATCH) MUST assert `countBefore == N`, perform the mutation, assert `countAfter == N+1` (or whatever). Without cardinality, a "test passed because no exception" is humo, not evidence.

4. **No humo (HARD)** — assert the concrete outcome value, not absence of error. `assert result.email == "alice@x"` not `assert result is not None`. `assert body["id"] == 42` not `assert "id" in body`.

5. **Three paths per slice (HARD)** — each slice ships: ≥1 happy path, ≥1 sad path (rejected input), ≥1 edge path (boundary: null, empty, max length, max int, etc.). No "happy-only" coverage.

6. **Refactor-safety (HARD)** — tests assert OUTCOME (returned value, persisted state, observable side effect), not IMPLEMENTATION (specific SQL query sequence, method call order, internal flag). A behavior-preserving refactor MUST NOT break the suite. If it does, the test is wrong, fix or delete it.

7. **Single harness form per project (HARD)** — exactly one way to set up the test environment per project. Two `conftest.py` files using different mocking strategies = bug, not flexibility. No project variants: `FakeClient` is THE pattern, not `MockClient` + `StubClient` + `FakeClient`.

8. **No mutation of production state (HARD)** — tests MUST NOT write to the production backend, real database, live external service, or shared mutable env. Use a sandbox / test-DB / in-memory store / `monkeypatch.setenv`. CI gates must skip E2E if no sandbox is available (env-flag-gated).

9. **Test module structure (HARD)** — top-down: imports → constants → helpers / fixtures → tests (atoms). Bottom-up: actual `def test_*` atoms at the end. NEVER interleave helpers and atoms — both humans and IA lose the structure.

10. **Helper signature must match atom signature EXACTLY (HARD)** — when a service signature changes, EVERY atom calling it must update in the same commit. Drift = type mismatch at runtime + assertion misses that compile but don't fail.

## Decision Gates

| Scenario | Pattern |
|---|---|
| Pure logic (validation, transformation, orchestration) | **Unit** — fake/in-memory dependency, no I/O |
| Repository / DAO / SQL-touching code | **Integration** — real test-DB (or transaction-rolled-back) |
| HTTP / UI / business-flow end-to-end | **E2E** — Playwright / Selenium / Cypress against a running app |
| Smoke (sanity, "did the app boot?") | **Separate suite** — NOT mixed with atomic |

Three-test-paths-per-slice rule applies to every layer above.

## Execution Steps (TDD loop for IA)

1. **Red test commit** — write the test FIRST. Run it. Confirm it fails for the right reason (the missing capability, not import error).
2. **Manifest** — if E2E, update the E2E runner manifest / Playwright config / `conftest.py`.
3. **Production commit** — implement the minimum to make the test pass. Nothing more. No speculative abstractions.
4. **Audit** — pre-merge gates: linter + type checker + `pytest --collect-only` + critical-helpers coverage check.
5. **Push + PR** — single atomic commit pair (test + implementation). PR body includes: traceable evidence the test was red before the implementation.
6. **CI green** — all gates pass. Don't merge with red.
7. **Self-review** — run the project's review lens (e.g. `code-review-expert` or equivalent) on the diff.
8. **User merges** — orchestrator does NOT merge without user OK on operational docs / security-sensitive diffs.

Refactor cycle:
- After green, refactor ONLY with tests still green.
- After refactor, run the full suite again.
- If a refactor breaks a test, the test was wrong (per Rule 6). Fix or delete.

## Output Contract

A "tested slice" PR ships:
- Test commit(s) with concrete assertions, not humo.
- Implementation commit(s) with minimal diff.
- Three paths per slice covered: happy + sad + edge.
- Coverage gate satisfied (per project's threshold; usually 80% of business logic, 100% of critical helpers).
- Pre-merge audit green (linter + type checker + test discovery).
- Single harness form honored (no project-variant mocks).
- Refactor-safe: survives a behavior-preserving refactor.
- PR body: traceable test-implementation pairing, no merge with red.

## References

- `assets/fixture-patterns.md` — concrete fixture recipes by stack
- `assets/dependency-injection.md` — DI patterns for tests
- `assets/interface-seams.md` — when to fake, when to hit real
- `assets/test-quality.md` — coverage, smoke vs atomic, debt report
- `assets/tdd-loop.md` — 8-step loop in detail with command examples
- `assets/mapping-from-vba.md` — for agents cross-referencing from `access-vba-tdd-fundamentos`
- `assets/prompt-template.md` — verbatim block to embed in any sdd-apply delegation

---
changelog: v1.0 (2026-07-05) — initial release, ported from `access-vba-tdd-fundamentos` v2.6.1 with all VBA-specific patterns stripped and web-agnostic primitives.