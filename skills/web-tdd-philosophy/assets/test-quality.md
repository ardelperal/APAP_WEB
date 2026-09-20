# Test Quality — coverage, smoke vs atomic, debt report

## Coverage as floor + diagnostic, never as goal

Coverage is a **signal that something is missing**, not a target to chase. The Hard Rule: 80% of business-logic lines covered (not all lines).

| Layer | Coverage target | Why |
|---|---|---|
| Business logic (service, domain) | 80%+ | High value, low cost |
| Repository / DAO | 80%+ | Catches SQL bugs |
| HTTP handler | 60-80% | Mostly wiring, low cost to skip |
| UI / template | 0-30% | Smoke / E2E covers the wiring |
| Framework boilerplate | 0% | Not your code |

**Prohibited**: chasing 100% by adding acoplated tests that mock internals just to bump the number.

## Smoke vs atomic — separation mandatory

Atomic tests: one assertion per test, fast, run on every commit.
Smoke tests: end-to-end happy paths, slow, run on deploy.

NEVER mix atomic and smoke in the same suite. Mixing causes:
- Duplicate fixture setup (atomic + smoke both load the test-DB)
- Test runner timeouts when the suite grows
- Confusing failure attribution (which test failed?)

```python
# tests/test_user_create.py — atomic, fast, no I/O
def test_create_user_persists_row(fake_repo): ...

def test_create_user_rejects_empty_email(fake_repo): ...

def test_create_user_rejects_256_char_email(fake_repo): ...
```

```python
# tests/smoke/test_user_flow.py — smoke, slow, requires running app
@pytest.mark.smoke
def test_signup_to_login_to_logout(e2e_app, page):
    # Full browser flow
    ...
```

```yaml
# ci.yml
- run: pytest tests/ --ignore=tests/e2e --ignore=tests/smoke -W error::DeprecationWarning
- run: pytest tests/smoke/ --base-url=${{ secrets.STAGING_URL }}  # only on deploy
- run: pytest tests/e2e/  # only if APAP_E2E_BASE_URL set
```

## The "is this a good test" checklist

Before merging a test atom, ask:

1. **Does it assert concrete values?** `assert result.email == "alice@x.com"` not `assert result is not None`.
2. **Does it assert cardinality for mutations?** `assert len(repo.inserted) == 1`.
3. **Does it cover a path, not just a code path?** Happy + sad + edge.
4. **Does it survive a behavior-preserving refactor?** If you rename the method or extract a helper, does the test still pass?
5. **Does it fail for the right reason?** If the production code is broken, does this test catch it? If the production code is correct, does this test pass?
6. **Is the assertion at the right layer?** Don't test SQL semantics in a unit test of a service. Don't test business logic in an E2E test.
7. **Is the fake's contract honored?** Does the fake implement the same interface the production code uses?

If any answer is "no", the test needs work before merge.

## Debt report — when coverage is below floor

If your project lands a slice with coverage < 80% on business logic, you MUST attach a debt report to the PR:

```markdown
## Test debt report — SliceName

### Coverage
- Business logic: X% (target: 80%)
- Repositories: Y%
- HTTP handlers: Z%

### Methods covered
| Method | Type | Test atom |
|---|---|---|
| UserService.create | Service | test_create_user_persists_row |
| UserService.list | Service | test_list_users_returns_seeded |

### Methods testable but uncovered (debt)
| Method | Reason uncovered | Refactor suggested |
|---|---|---|
| UserService.export_csv | Not prioritized this sprint | Add next slice |

### Methods untestable due to coupling (debt)
| Method | Coupling issue | Refactor suggested |
|---|---|---|
| UserService.send_welcome_email | Calls EmailService.send() singleton | Inject EmailService dependency |
| UserController.create | Reads request.body directly | Pass parsed DTO instead |
```

The IA agent CANNOT declare a slice "complete" if coverage is below floor without this report.

## Anti-patterns — REJECT in code review

| Anti-pattern | Smell | Replace with |
|---|---|---|
| `assertTrue(result)` / `assertIsNotNone(result)` | Humo | `assertEqual(result.field, "expected_value")` |
| `mock.patch("module.global")` | Brittle, doesn't test injection | Inject a protocol-implementing fake |
| `assert_called_once_with(...)` as the entire test | Tests plumbing, not behavior | Assert on the OBSERVABLE outcome, then assert the call as a sanity check |
| Test name: `test_user_service` (no behavior) | Tells you nothing | `test_create_user_persists_row_with_normalized_email` |
| Skipping sad path because "obvious" | Sad path has its own bugs | Write the sad path atom |
| Reusing setup from another test | Coupling, fragile | Each test sets up its own data |
| Asserting on `repr()` or `str()` | Implementation-coupled | Assert on the structured field |
| `assert len(rows) > 0` | Weak | `assert len(rows) == 3` (specific number) |

## Three-tier test ratio

For a 1000-LOC service:

| Tier | Target | Actual (good) |
|---|---|---|
| Unit (with fakes) | 60-70% | 650 atoms |
| Integration (real test-DB) | 20-30% | 250 atoms |
| E2E (browser) | 5-10% | 100 atoms |

Ratio is `6:2.5:1` (unit:integration:E2E). If your E2E suite is bigger than unit, you're testing the wrong layer.

## Time budget

| Tier | Per-test budget | Suite total |
|---|---|---|
| Unit | < 50ms | < 5s for 100 atoms |
| Integration | < 500ms | < 50s for 100 atoms |
| E2E | < 5s | < 5min for 60 atoms |

If you exceed these, the test is doing too much. Split it.

## Test maintainability — when to delete

A test should be deleted when:
1. It tests behavior that no longer exists (feature removed)
2. It tests implementation details that changed
3. It duplicates another test (assertion redundancy)
4. It has flaky behavior that can't be fixed in 30 min
5. It has accumulated mocking layers until the test is more setup than assertion

When deleting, prefer to delete the atom AND the corresponding production code together, in the same commit. Otherwise the production code loses coverage silently.

## Hard Rule 7 — Single harness form

One way to set up tests per project. No variants.

```python
# ✅ This project uses FakeRepo + queue_response + client fixture
# All tests in the project follow this pattern.

# ❌ Some tests use FakeRepo + queue_response
# ❌ Other tests use MagicMock + assert_called_once
# ❌ Other tests use a global monkey-patched singleton
# This is INCONSISTENT. Pick one.
```

When reviewing a PR, reject any atom that uses a different mocking strategy than the rest of the project.

## Code review checklist

When reviewing a PR's tests:

- [ ] Each test sets up its own data (no shared mutable state)
- [ ] Each test asserts concrete values, not absence of error
- [ ] Each mutation test asserts cardinality
- [ ] Three paths per slice (happy + sad + edge)
- [ ] Coverage gate satisfied (or debt report attached)
- [ ] No mocking of the system under test
- [ ] No `assertTrue(result)` / `assertIsNotNone(result)` humo
- [ ] One mocking strategy for the whole project
- [ ] Test names describe behavior, not implementation
- [ ] Tests pass when run in isolation AND in suite
- [ ] Tests pass when run in any order
- [ ] Refactor-safety: a behavior-preserving refactor doesn't break tests

If any item fails, request changes.