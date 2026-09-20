# Fixture Patterns — by stack

Generic recipes for the fixture gate (Hard Rule 1). Each pattern sets up the test's own data; never depends on existing rows.

## Python (pytest)

```python
# tests/conftest.py — canonical mock for a service client
import pytest
from app.core.client import Client  # production interface
from tests.fakes import FakeClient    # test double

@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()

@pytest.fixture
def client(fake_client: FakeClient) -> Client:
    """Production interface typed; tests inject the fake."""
    return fake_client
```

```python
# tests/test_create_user.py — happy + sad + edge in one file
from tests.fakes import FakeClient

def test_create_user_happy_path(fake_client: FakeClient) -> None:
    fake_client.queue_response(
        method="insert_user",
        return_value={"id": 1, "email": "alice@x.com"},
    )
    result = service.create_user(fake_client, email="alice@x.com")
    assert result.email == "alice@x.com"
    assert len(fake_client.calls) == 1
    # Cardinality:
    assert len(fake_client.log["inserts"]) == 1

def test_create_user_with_empty_email_raises(fake_client: FakeClient) -> None:
    fake_client.queue_response(method="insert_user", raise_value=ValueError("email required"))
    with pytest.raises(ValueError, match="email required"):
        service.create_user(fake_client, email="")

def test_create_user_with_256_char_email_is_rejected_at_validation(
    fake_client: FakeClient,
) -> None:
    long = "a" * 256
    fake_client.queue_response(method="insert_user", raise_value=ValueError("email too long"))
    with pytest.raises(ValueError, match="too long"):
        service.create_user(fake_client, email=f"{long}@x.com")
```

Anti-patterns to REJECT:
- `client.list_users()` then assert on the result — depends on prod state
- `SELECT * FROM users` via real backend — needs backend, slow, depends on data
- Reusing fixtures from another test file — fragile coupling

## Node / TypeScript (Jest)

```typescript
// tests/fakes/FakeUserRepo.ts
export class FakeUserRepo implements UserRepo {
  users: User[] = [];
  insertCalls: InsertCall[] = [];

  async insert(input: NewUser): Promise<User> {
    this.insertCalls.push(input);
    const user = { id: this.users.length + 1, ...input };
    this.users.push(user);
    return user;
  }

  async list(): Promise<User[]> {
    return [...this.users];
  }
}

// tests/createUser.test.ts
import { FakeUserRepo } from "./fakes/FakeUserRepo";

describe("createUser", () => {
  let repo: FakeUserRepo;

  beforeEach(() => {
    repo = new FakeUserRepo();
  });

  it("happy path persists the user", async () => {
    const result = await service.createUser(repo, { email: "alice@x.com" });
    expect(result.email).toBe("alice@x.com");
    expect(repo.users.length).toBe(1);
    expect(repo.insertCalls.length).toBe(1);
  });

  it("rejects empty email", async () => {
    await expect(service.createUser(repo, { email: "" }))
      .rejects.toThrow("email required");
  });

  it("rejects 256-char email", async () => {
    await expect(
      service.createUser(repo, { email: "a".repeat(256) + "@x.com" })
    ).rejects.toThrow("email too long");
  });
});
```

## Go (testing + testify)

```go
// internal/user/fakes_test.go
type fakeUserRepo struct {
    users    []User
    inserted []User
}

func (f *fakeUserRepo) Insert(ctx context.Context, u NewUser) (User, error) {
    if u.Email == "" {
        return User{}, errors.New("email required")
    }
    if len(u.Email) > 255 {
        return User{}, errors.New("email too long")
    }
    user := User{ID: len(f.users) + 1, Email: u.Email}
    f.users = append(f.users, user)
    f.inserted = append(f.inserted, user)
    return user, nil
}

func (f *fakeUserRepo) List(ctx context.Context) ([]User, error) {
    return f.users, nil
}

// internal/user/service_test.go
func TestCreateUser_HappyPath(t *testing.T) {
    repo := &fakeUserRepo{}
    svc := NewService(repo)

    user, err := svc.Create(context.Background(), NewUser{Email: "alice@x.com"})

    require.NoError(t, err)
    assert.Equal(t, "alice@x.com", user.Email)
    assert.Len(t, repo.inserted, 1)
    assert.Len(t, repo.users, 1) // cardinality after
}

func TestCreateUser_RejectsEmpty(t *testing.T) {
    repo := &fakeUserRepo{}
    svc := NewService(repo)

    _, err := svc.Create(context.Background(), NewUser{Email: ""})

    assert.Error(t, err)
}

func TestCreateUser_RejectsTooLong(t *testing.T) {
    repo := &fakeUserRepo{}
    svc := NewService(repo)

    long := strings.Repeat("a", 256)
    _, err := svc.Create(context.Background(), NewUser{Email: long + "@x.com"})

    assert.Error(t, err)
}
```

## Ruby (RSpec)

```ruby
# spec/fakes/fake_user_repo.rb
class FakeUserRepo
  attr_reader :inserted, :users

  def initialize
    @users = []
    @inserted = []
  end

  def insert(attrs)
    raise "email required" if attrs[:email].to_s.empty?
    raise "email too long" if attrs[:email].to_s.length > 255
    user = User.new(id: @users.length + 1, **attrs)
    @users << user
    @inserted << user
    user
  end

  def list
    @users.dup
  end
end

# spec/services/user_creator_spec.rb
require "rails_helper"

RSpec.describe UserCreator do
  let(:repo) { FakeUserRepo.new }
  let(:service) { described_class.new(repo) }

  describe "#call" do
    it "persists the user with happy path" do
      result = service.call(email: "alice@x.com")
      expect(result.email).to eq("alice@x.com")
      expect(repo.inserted.length).to eq(1)
      expect(repo.users.length).to eq(1)
    end

    it "rejects empty email" do
      expect { service.call(email: "") }.to raise_error("email required")
    end

    it "rejects 256-char email" do
      long = "a" * 256
      expect { service.call(email: "#{long}@x.com") }.to raise_error("email too long")
    end
  end
end
```

## Database-backed tests (transaction rollback)

When you need real SQL behavior (e.g. trigger, constraint, index) but production data must stay clean:

### Python (pytest + SQLAlchemy)
```python
@pytest.fixture
def db_session():
    """Each test gets a fresh transaction that's rolled back at teardown."""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()  # undo all writes
    connection.close()
```

### Node (Jest + Knex / Prisma)
```typescript
beforeEach(async () => {
  await knex.migrate.rollback();
  await knex.migrate.latest();
  await db.raw("BEGIN");
});

afterEach(async () => {
  await db.raw("ROLLBACK");
});
```

### Go (sqlx)
```go
func setupTestDB(t *testing.T) *sqlx.DB {
    db := sqlx.MustConnect("postgres", "test_db_url")
    t.Cleanup(func() { db.Close() })
    return db
}

func TestWithTransaction(t *testing.T) {
    db := setupTestDB(t)
    tx, err := db.Beginx()
    require.NoError(t, err)
    t.Cleanup(func() { tx.Rollback() }) // undo all writes
    // ... use tx for all queries in this test
}
```

## Anti-patterns — REJECT in code review

| Anti-pattern | Why bad | Replace with |
|---|---|---|
| `client.execute_sql("SELECT * FROM users LIMIT 1")` then assert | Depends on prod state, flaky | Inject a fake that returns seeded rows |
| `client.list_users()` then assert on whatever's there | Coupling to other tests | Test sets up its own rows via `fake_client.queue_response(...)` |
| Reusing the same `db_session` fixture across 10 tests | Shared mutable state, race conditions | `scope="function"` (default) + per-test setup |
| `beforeAll` setting up data for multiple `it`s | Same fixture runs once; if a test mutates, others see mutation | `beforeEach` for per-test setup; `beforeAll` only for read-only reference data |
| `assert result is not None` | Humo | `assert result.email == "alice@x.com"` |
| Skipping cardinality on INSERT/UPDATE/DELETE | "Test passed" but no evidence the row was actually written | `assert len(repo.inserted) == 1` |
| Asserting on a private internal field | Couples to implementation, breaks on refactor | Assert on the public observable contract |

## Three-layer coverage per slice

For every feature/bugfix slice:

| Layer | Pattern | When |
|---|---|---|
| Unit | Service + `FakeRepo` | Pure logic, validation, transformation |
| Integration | Real test-DB + transaction rollback | Repository, SQL constraints, triggers |
| E2E (Playwright/Selenium) | Real running app + seeded fixtures | UI flows, RBAC, CSRF, happy/sad/edge through the browser |

For a slice that touches all three layers (e.g. a new form), ship:
- N unit atoms (service logic)
- M integration atoms (repo / SQL behavior)
- 3 E2E atoms (happy / sad / edge through the browser)

E2E is NOT a replacement for unit. E2E catches wiring bugs (route + template + form binding); unit catches business logic bugs. Both layers required.