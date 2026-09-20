# Dependency Injection for Tests

The Hard Rule 2 principle: services take their dependencies as parameters. Tests pass fakes. Production wires real implementations via the project's DI container.

## Why this matters

A test that doesn't inject its dependencies can only verify "the service called getSomething()". It CANNOT verify "the service used the thing I passed in". These are different:

```python
# ❌ BAD — tests the singleton getter, not the injected dep
def test_user_creator_persists():
    UserRepo.create(email="alice@x.com")  # calls module-level singleton
    assert UserRepo.list() == [...]        # reads module-level state

# ✅ GOOD — tests the injected dep
def test_user_creator_persists(fake_repo):
    repo = fake_repo
    svc = UserCreator(repo)
    user = svc.create(email="alice@x.com")
    assert user.email == "alice@x.com"
    assert len(repo.inserted) == 1  # proves svc actually called repo.insert
```

The BAD test passes even if `UserCreator` calls a different singleton internally — the test cannot distinguish. The GOOD test would fail if `UserCreator` ignored its `repo` parameter and called `UserRepo.create()` directly.

## Patterns by stack

### Python (FastAPI / Flask / Django)

```python
# app/users/service.py
class UserService:
    def __init__(self, repo: UserRepo, notifier: Notifier, clock: Clock) -> None:
        self.repo = repo
        self.notifier = notifier
        self.clock = clock

    def create(self, email: str) -> User:
        user = self.repo.insert(email=email)
        self.notifier.send("user.created", user_id=user.id)
        return user

# app/main.py — production wires real impls via Depends
def get_user_service(
    repo: UserRepo = Depends(get_user_repo),
    notifier: Notifier = Depends(get_email_notifier),
    clock: Clock = Depends(get_system_clock),
) -> UserService:
    return UserService(repo, notifier, clock)

# tests/test_user_service.py — tests inject fakes
def test_create_sends_notification(fake_repo, fake_notifier, fake_clock):
    svc = UserService(fake_repo, fake_notifier, fake_clock)
    svc.create("alice@x.com")
    assert len(fake_notifier.sent) == 1
    assert fake_notifier.sent[0]["event"] == "user.created"
```

### Node / TypeScript (NestJS / Express)

```typescript
// src/users/user.service.ts
@Injectable()
export class UserService {
  constructor(
    private readonly repo: UserRepo,
    private readonly notifier: Notifier,
    private readonly clock: Clock,
  ) {}

  async create(email: string): Promise<User> {
    const user = await this.repo.insert({ email });
    await this.notifier.send('user.created', { userId: user.id });
    return user;
  }
}

// tests/user.service.spec.ts
describe('UserService', () => {
  let repo: FakeUserRepo;
  let notifier: FakeNotifier;
  let clock: FakeClock;

  beforeEach(() => {
    repo = new FakeUserRepo();
    notifier = new FakeNotifier();
    clock = new FakeClock();
  });

  it('sends notification on create', async () => {
    const svc = new UserService(repo, notifier, clock);
    await svc.create('alice@x.com');
    expect(notifier.sent).toHaveLength(1);
    expect(notifier.sent[0].event).toBe('user.created');
  });
});
```

### Go (manual DI or wire)

```go
// internal/user/service.go
type Service struct {
    Repo     UserRepo
    Notifier Notifier
    Clock    Clock
}

func NewService(repo UserRepo, notifier Notifier, clock Clock) *Service {
    return &Service{Repo: repo, Notifier: notifier, Clock: clock}
}

func (s *Service) Create(ctx context.Context, email string) (User, error) {
    user, err := s.Repo.Insert(ctx, email)
    if err != nil {
        return User{}, err
    }
    _ = s.Notifier.Send(ctx, "user.created", user.ID)
    return user, nil
}

// internal/user/service_test.go
func TestCreateSendsNotification(t *testing.T) {
    repo := &fakeUserRepo{}
    notifier := &fakeNotifier{}
    clock := &fakeClock{}
    svc := NewService(repo, notifier, clock)

    _, err := svc.Create(context.Background(), "alice@x.com")
    require.NoError(t, err)
    assert.Len(t, notifier.sent, 1)
    assert.Equal(t, "user.created", notifier.sent[0].Event)
}
```

### Ruby (Rails / dry-system / manual)

```ruby
# app/services/user_creator.rb
class UserCreator
  def initialize(repo: UserRepo.new, notifier: UserNotifier.new, clock: SystemClock.new)
    @repo = repo
    @notifier = notifier
    @clock = clock
  end

  def call(email:)
    user = @repo.insert(email: email)
    @notifier.send("user.created", user_id: user.id)
    user
  end
end

# spec/services/user_creator_spec.rb
RSpec.describe UserCreator do
  it "sends notification" do
    repo = FakeUserRepo.new
    notifier = FakeNotifier.new
    clock = FakeClock.new
    svc = described_class.new(repo: repo, notifier: notifier, clock: clock)

    svc.call(email: "alice@x.com")

    expect(notifier.sent.length).to eq(1)
    expect(notifier.sent.first[:event]).to eq("user.created")
  end
end
```

## Hard Rule 8 — Never test against the production backend

The DI principle above assumes the test passes a fake. But the project's production code MUST also use real implementations in production. The boundary:

| Layer | What the test injects | What production wires |
|---|---|---|
| HTTP handler | `FakeRequest`, `FakeResponse` | Real `Request`, `Response` |
| Service | `FakeClient`, `FakeRepo`, `FakeClock` | Real `HttpClient`, real `Repo`, real `Clock` |
| Repository | Real test-DB (in-memory or transaction-rolled-back) | Real prod-DB |
| External service (3rd party API) | `FakeApi` or `WireMock` | Real `HttpClient` + retry / circuit breaker |

The boundary between layers that NEED real I/O (repositories, external APIs) and layers that DON'T (pure logic, validation) is the seam where fakes go.

## Anti-patterns — REJECT

| Anti-pattern | Why bad | Replace with |
|---|---|---|
| Service calls `UserRepo.create()` directly | Tests cannot inject a fake | Service takes `repo` as constructor/method param |
| Service calls `getCurrentUser()` global | Same | Inject `current_user_provider` |
| Service reads `os.environ["API_KEY"]` | Tests pollute env, parallel tests conflict | Inject `api_key_provider` |
| Service calls `datetime.now()` | Tests cannot control time | Inject `Clock` |
| Test imports the module and monkey-patches `module.foo` | Brittle, drift-prone | Inject the dependency |
| Test uses real database "to be sure" | Pollutes prod, slow, fragile | Use a test-DB (in-memory or per-test schema) |

## Composition: fakes implement the same interface

The fake MUST implement the same interface (Protocol in Python, type in TypeScript, interface in Go). Otherwise the test doesn't prove the service works against a real implementation.

```python
# app/users/repo.py
from typing import Protocol
class UserRepo(Protocol):
    def insert(self, email: str) -> User: ...
    def list(self) -> list[User]: ...
    def get_by_id(self, user_id: int) -> User | None: ...

# tests/fakes/fake_user_repo.py
class FakeUserRepo:
    """Implements the UserRepo protocol for tests."""
    def __init__(self) -> None:
        self.users: list[User] = []
        self.inserted: list[NewUser] = []

    def insert(self, email: str) -> User:
        user = User(id=len(self.users) + 1, email=email)
        self.users.append(user)
        self.inserted.append(NewUser(email=email))
        return user

    def list(self) -> list[User]:
        return list(self.users)

    def get_by_id(self, user_id: int) -> User | None:
        return next((u for u in self.users if u.id == user_id), None)
```

If a service uses a method that the fake doesn't implement, the test will crash with `AttributeError` or type-check failure. That's a feature — it surfaces gaps in the fake's coverage of the interface.