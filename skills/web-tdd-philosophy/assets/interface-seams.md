# Interface Seams — when to fake, when to hit real

The Hard Rule 2 (DI) and Hard Rule 8 (no prod mutation) imply a layered approach: fakes for fast layers, real implementations for slow / I/O layers.

## The seam pyramid

```
        ┌─────────────────────┐
        │  E2E (Playwright)   │  ← Real app, real backend, real browser
        ├─────────────────────┤
        │  HTTP handler tests  │  ← Real routing layer, fake service deps
        ├─────────────────────┤
        │  Service unit tests  │  ← FakeRepo, FakeClient, FakeClock
        ├─────────────────────┤
        │  Integration (SQL)   │  ← Real test-DB (or transaction), fake cache/notifier
        └─────────────────────┘
```

Each layer tests a different seam. Wrong choice of fake = wrong test layer = false confidence or false failure.

## Decision table

| Layer being tested | Speed | What it catches | What it can NOT catch | Use fakes or real? |
|---|---|---|---|---|
| Pure logic (validation, transformation) | Fast (μs) | Logic bugs | Wiring bugs | **Fake all deps** |
| Service (orchestration, side effects) | Fast (ms) | Wrong calls to deps, missed side effects | Real SQL behavior, real HTTP errors | **Fake all deps** |
| Repository / DAO / SQL | Medium (10-100ms) | Wrong queries, missing constraints, index issues | Logic bugs in callers | **Real test-DB**, fake cache/notifier |
| HTTP handler | Fast (ms) | Wrong status codes, wrong response shape, missing auth | UI bugs, JS errors | **Fake service deps**, real router |
| E2E (browser) | Slow (1-5s) | Wiring bugs (route → template → form), JS errors, real browser quirks | Unit-test-level bugs | **Real everything** |

## When to fake

**Always fake** for layers that have NO observability into real production state:

```python
# These are SAFE to fake — they have well-defined contracts and no surprises:
- HTTP clients to external services (Stripe, SendGrid, etc.) → use `responses`, `httpx.MockTransport`, `respx`
- Clock / time providers → use `freezegun`, `time-machine`
- UUID generators → use `pytest-uuid` or seed deterministically
- Email / SMS senders → use in-memory recorder
- File system → use `tmp_path` fixture, never touch the real FS
- Environment variables → use `monkeypatch.setenv`, never touch the real env

# These are SAFE to fake if they don't have production state semantics:
- Cache (Redis, Memcached) → use `fakeredis`
- Queue (SQS, RabbitMQ) → use in-memory recorder
- Search (Elasticsearch) → use in-memory or test container
```

**Never fake** the layer you're testing:

```python
# ❌ Don't do this
def test_repository_inserts_user():
    fake_db = FakeDB()
    repo = UserRepository(fake_db)
    repo.insert({"email": "alice@x.com"})
    assert fake_db.users[-1]["email"] == "alice@x.com"
# This proves NOTHING about whether the SQL is correct.

# ✅ Do this instead
def test_repository_inserts_user(test_db):
    repo = UserRepository(test_db)
    user_id = repo.insert({"email": "alice@x.com"})
    row = test_db.execute("SELECT * FROM users WHERE id = %s", [user_id]).fetchone()
    assert row["email"] == "alice@x.com"
# This proves the SQL is correct.
```

## When to hit real

**Always hit real** for layers whose production state has business semantics:

```python
# SQL constraints, triggers, indexes — use a real test-DB:
- PostgreSQL: `pytest-postgresql` or per-test schema with `CREATE SCHEMA test_N; SET search_path TO test_N;`
- MySQL: per-test schema or transaction rollback
- SQLite: in-memory is fine for most things; but foreign-key cascades may behave differently

# External API contracts — use a wiremock-style server:
- Stripe / Twilio / SendGrid: `responses`, `wiremock`, `mountebank`, or the SDK's own test mode
- Internal microservices: use their test-DB + seed; never their prod
- Webhooks: use a recorded fixture (Stripe CLI, etc.)
```

## Three-tier strategy for a typical web service

```python
# tests/conftest.py — three layers, three fixtures, one pattern

@pytest.fixture
def fake_client():
    """Tier 1: in-memory fake. Use for unit tests."""
    return FakeClient()

@pytest.fixture
def real_test_db():
    """Tier 2: real PostgreSQL test instance, transaction per test."""
    db = PostgresTestDB()
    db.migrate()
    yield db
    db.drop()

@pytest.fixture
def e2e_app():
    """Tier 3: real running app on a random port. Use for E2E."""
    app = start_app(test_db="...")
    yield app
    app.stop()

@pytest.fixture
def client(fake_client):
    """Default `client` fixture: fake. Override per-test for real."""
    return fake_client
```

Test routing:

```python
# tests/test_user_service_unit.py — uses `client` (fake)
def test_create_sends_notification(client):
    # service logic only
    ...

# tests/test_user_repo_integration.py — uses `real_test_db`
@pytest.mark.integration
def test_unique_email_constraint(real_test_db):
    # SQL semantics
    ...

# tests/e2e/test_signup_e2e.py — uses `e2e_app`
@pytest.mark.e2e
def test_signup_form_e2e(e2e_app, page):
    # browser-driven flow
    ...
```

## Common mistake: mocking the system under test

```python
# ❌ Don't do this — the test cannot fail for the right reason
def test_user_service_creates_user(mocker):
    mocker.patch("app.users.service.UserRepo")  # mock the class
    fake_repo = mocker.MagicMock()
    fake_repo.insert.return_value = User(id=1, email="alice@x.com")
    
    svc = UserService()
    user = svc.create(email="alice@x.com")
    
    fake_repo.insert.assert_called_once_with(email="alice@x.com")
    # ^^^ This proves the service CALLED insert, not that the
    # service USED the inserted result correctly.
```

The fix: inject the fake via constructor, don't mock-patch:

```python
# ✅ Do this
def test_user_service_creates_user(fake_repo):
    svc = UserService(repo=fake_repo)
    user = svc.create(email="alice@x.com")
    assert user.email == "alice@x.com"
    assert len(fake_repo.inserted) == 1
    assert fake_repo.inserted[0].email == "alice@x.com"
```

## When mocking IS appropriate

Mocking is appropriate when:
1. The thing being mocked is a 3rd party SDK you can't fake cleanly (e.g. `boto3`, `stripe`).
2. The thing being mocked has time/network/state externalities you can't reproduce (e.g. `datetime.now()`, `uuid.uuid4()`, `os.environ`).
3. The thing being mocked is a global side effect (logger, metrics, telemetry).

Even in these cases, prefer narrow interfaces you control (a `Clock` protocol instead of `datetime.now()`; a `UserRepo` protocol instead of a global `UserRepo` class).

## Anti-patterns — REJECT

| Anti-pattern | Why bad | Replace with |
|---|---|---|
| `mocker.patch("module.global_function")` | Tests don't survive refactors of internal call paths | Inject a `Clock` or `Notifier` interface |
| Mocking the class under test | Test proves nothing | Test the public method, observe behavior |
| Mocking 5+ layers in one test | Setup is more code than the test | Use the lowest possible mock depth |
| Skipping the test-DB "because mocks are faster" | Lose SQL constraint coverage | Use the tiered approach: unit for logic, integration for SQL |
| Real production DB in CI | Pollutes prod | Test-DB only, env-flag gated |

## CI gates

```yaml
# .github/workflows/ci.yml
- name: Run unit + integration tests
  run: pytest tests/ --ignore=tests/e2e -W error::DeprecationWarning

- name: Run E2E (only on main + when test-DB available)
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  env:
    APAP_E2E_BASE_URL: ${{ secrets.TEST_DB_URL }}
  run: pytest tests/e2e/

- name: Smoke (after deploy, against staging)
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  run: pytest tests/smoke/ --base-url=${{ secrets.STAGING_URL }}
```

The tiered CI matches the tiered test pyramid: fast unit/integration on every PR, slow E2E only on main merge, smoke only on deploy.