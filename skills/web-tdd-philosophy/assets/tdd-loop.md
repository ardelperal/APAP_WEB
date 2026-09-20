# TDD Loop for IA — 8 steps

When implementing a feature, bugfix, or refactor, follow this exact 8-step loop. Skip a step = skipped rigor.

## Step 1 — Red test commit

Write the test FIRST. The test MUST fail before the implementation exists, for the right reason.

```python
# tests/test_create_user.py
def test_create_user_persists_with_normalized_email(fake_repo):
    svc = UserService(repo=fake_repo)
    user = svc.create(email="  ALICE@x.com  ")  # whitespace + uppercase
    assert user.email == "alice@x.com"
    assert len(fake_repo.inserted) == 1
```

Run:
```bash
pytest tests/test_create_user.py -W error::DeprecationWarning
```

Expected: RED. Failure reason should be "AttributeError: 'NoneType' object has no attribute 'email'" (because `create` doesn't exist yet) or similar.

If the test FAILS for the WRONG reason (import error, syntax error), fix the test first.

## Step 2 — Manifest

If the test is E2E (Playwright/Selenium), update the runner config:
- Add to `playwright.config.ts`'s `testMatch` or `testDir`
- Add to the project's e2e manifest if there's one
- Update CI workflow to include the new e2e test (env-flag gated)

If the test is unit or integration, no manifest update needed — pytest discovery handles it.

## Step 3 — Production commit

Implement the MINIMUM to make the test pass. Nothing more. No speculative abstractions, no "while I'm here" refactors, no "fix this other thing".

```python
# app/users/service.py
class UserService:
    def __init__(self, repo):
        self.repo = repo

    def create(self, email: str) -> User:
        normalized = email.strip().lower()
        return self.repo.insert(email=normalized)
```

Run the test again. Expected: GREEN.

If the test goes from RED to GREEN, this is the minimum. Stop.

## Step 4 — Audit

Pre-merge gates. Run all of these locally:

```bash
# Linter
ruff check app/ tests/

# Type checker (Python)
mypy app/

# Type checker (TypeScript)
tsc --noEmit

# Test discovery
pytest tests/<changed_file> --collect-only

# Test run
pytest tests/<changed_file> -W error::DeprecationWarning

# Coverage
pytest tests/<changed_file> --cov=app/<module> --cov-report=term-missing
```

For Go:

```bash
go vet ./...
go test ./internal/<module> -v
go test -cover ./...
```

For Ruby:

```bash
rubocop app/ spec/
rspec spec/<file>
```

For Java:

```bash
mvn -B verify
```

Each gate MUST pass. If any fails, fix the underlying issue (not the test).

## Step 5 — Push + PR

Single atomic commit pair (or merge into one commit if the project's convention is single commits). Branch name follows project convention (`feat/...`, `fix/...`, `refactor/...`).

PR body MUST include:
- Traceable test-implementation pairing (which test atom proves the implementation works)
- Coverage delta (before / after)
- Self-review verdict (which review lens, what was approved)
- Risk assessment (any backward-incompat, any required follow-up)

## Step 6 — CI green

Wait for all CI jobs to pass:
- Lint
- Type check
- Unit tests
- Integration tests
- Coverage gate

If any job fails, fix the underlying issue (not by re-running or skipping). Don't merge with red.

## Step 7 — Self-review

Run the project's review lens on the diff:

- For Python: `code-review-expert` (or equivalent)
- For TypeScript: ESLint + tsc + a senior reviewer lens
- For Go: `golangci-lint` + a senior reviewer lens
- For any stack: any "is this code good?" lens

Address every BLOCKER and CRITICAL finding. CRITICAL findings must be addressed OR explicitly waived by the user. WARNING and SUGGESTION are tracked but don't block.

## Step 8 — User merges

Per the project's merge policy:
- Some projects: orchestrator can merge after gates pass
- Some projects: user must approve before merge
- Pre-MVP single-branch: typically orchestrator merges after gates
- Post-MVP / staging-required: user must approve

Respect the project's policy. NEVER `--force` push.

## Refactor cycle — after green

Once tests are green, you may refactor. Constraints:
- Tests must stay green after each refactor step
- Run the full suite after each step
- If a refactor breaks a test, the test was wrong (per Hard Rule 6). Fix or delete.

```bash
# Refactor loop
git commit -m "refactor(user): extract normalize_email helper"
pytest tests/test_user_service.py -W error::DeprecationWarning
# ↑ must stay green
git commit -m "refactor(user): inline trivial helper"
pytest tests/ -W error::DeprecationWarning
# ↑ must stay green
```

## Three paths per slice — explicit checklist

For EVERY slice, ship:
- [ ] ≥1 happy path atom (valid input → expected outcome)
- [ ] ≥1 sad path atom (rejected input → expected error)
- [ ] ≥1 edge path atom (boundary: null, empty, max length, max int, special chars)

Example for a "create user" slice:

```python
def test_create_user_persists_with_normalized_email(fake_repo): ...  # happy
def test_create_user_rejects_empty_email(fake_repo): ...                # sad
def test_create_user_rejects_256_char_email(fake_repo): ...            # edge
```

If your slice ships only happy atoms, it's incomplete. Sad + edge must be present in the same PR.

## When the loop gets stuck

| Symptom | Likely cause | Fix |
|---|---|---|
| Test stays RED after multiple implementation attempts | The contract is unclear | Re-read the spec, ask the user, or simplify the slice |
| Test passes in isolation but fails in suite | Test pollution (shared state) | Use `beforeEach` setup + per-test transaction |
| Test passes but production code is broken | Test asserts the wrong thing | Re-read the implementation, assert the OUTCOME |
| Coverage drops after a refactor | Refactor removed a critical helper | Add a coverage gate in CI |
| Test timeouts | Too much I/O in unit tests | Move to integration; keep unit pure |
| Tests are flaky (pass/fail randomly) | Time, ordering, or shared state | Inject `Clock`, use deterministic IDs, isolate per-test |

## Lint + format check before commit

Per project:
- Python: `ruff check . && ruff format --check .`
- TypeScript: `eslint . && prettier --check .`
- Go: `gofmt -l . && golangci-lint run`
- Ruby: `rubocop`
- Java: `mvn -B checkstyle:check`

These are gatekeepers. Don't bypass.

## Commit message conventions (per language)

Python (Conventional Commits):
```
feat(user): add create method with email normalization

- Normalize email to lowercase + trimmed before insert
- TDD: test_create_user_persists_with_normalized_email passes
- Coverage: UserService.create at 100%
```

TypeScript:
```
feat(user): add create method with email normalization

- normalize email (lowercase + trim) before insert
- TDD: test_create_user_persists_with_normalized_email
- Coverage: UserService.create 100%
```

Go:
```
feat(user): add create with email normalization

- lowercase + trim email before insert
- TDD: TestCreate_PersistsWithNormalizedEmail
```

Ruby:
```
feat(user): add create with email normalization

- lowercase + trim email before insert
- TDD: user_creator_spec.rb
```

Match the project's commit message convention. If unsure, ask the user or read recent commits.