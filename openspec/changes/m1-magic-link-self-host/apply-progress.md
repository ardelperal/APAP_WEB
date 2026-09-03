# Apply Progress: m1-magic-link-self-host

Captured at session close, after F1 + F2 + F3 all delivered.

## State snapshot

| Field | Value |
|---|---|
| Slice | M1 magic-link self-host auth (solo magic link, no classic password) |
| Branch | `feat/641-rdd-m0` |
| Tip commit | `c993e9d` (`feat(m1-magic-verify-ready): check_magic_link_local_round_trip gate`) |
| Total commits | 7 M1 commits (3 feature + 2 docs + 1 SDD proposal + 1 F3 marker docs) |
| RDD lineage | `review-462a42960b25ac4c` (state: approved; 4 lenses; authority burned) |

## Commits applied (chronological order)

1. `7d9dde3` — `docs(sdd): propose M1 magic-link self-host auth (3-feature chain)` — proposal + spec + tasks
2. `08236fe` — `feat(m1-magic-foundation): MagicLinkPort + Postgres adapter + ConsoleMailTransport` — implements T1.1-T1.5
3. `0e8cb7c` — `docs(sdd): mark M1 F1 magic-foundation tasks complete with gate outcomes` — F1 marker
4. `212674d` — `feat(m1-magic-rails): POST /auth/magic/start + verify + DI + auth_flow wiring` — implements T2.1-T2.5
5. `d450b02` — `docs(sdd): mark M1 F2 magic-rails tasks complete; defer lineage to post-F3`
6. `c993e9d` — `feat(m1-magic-verify-ready): check_magic_link_local_round_trip gate` — implements T3.1-T3.3
7. (F3 marker docs to be added at archive time)

## Gates observed across the slice

### F1-specific gates (all green at F1 close)
- `ruff check` on F1 files: clean
- `check_module_size` on F1 files: clean (`postgres_adapter.py` 242, `mail_transports.py` 144, `get_mail_transport.py` 53, `magic_link_port.py` 54, `mail_transport_port.py` 22, `__init__.py` 20 — all under 700)
- `check_mutation_sites` on F1 files: clean
- `check_layers`: OK
- `check_slice_completeness`: OK after the slice stubs (`tests/test_magic_link.py` + `tests/test_mail_transport.py`)
- pytest: 7 atoms (F1 contract)

### F2-specific gates (all green at F2 close)
- `ruff check`: clean after the test-file split (test_magic_link.py 298 lines, test_magic_link_routes.py 522 lines — both < 700)
- `check_module_size`: clean
- `check_mutation_sites`: clean
- `check_layers`: OK
- pytest: 7 new atoms for AS1-AS6 + AS8 (timing-attack resistance)

### F3-specific gates (all green at F3 close)
- `ruff check`: clean
- `check_module_size`: each F3 file ≤700 lines (`local_backend/app.py` 174, `local_backend/stub_auth_port.py` 198, `migration/verify_fallback_ready.py` 373, `tests/migration/_local_backend_fixture.py` 694, `tests/migration/test_magic_link_local_round_trip.py` 69)
- `check_mutation_sites`: `migration/verify_fallback_ready.py` at 244 < 250 ceiling
- `check_complexity`: clean
- `check_layers`: OK
- `check_slice_completeness`: OK
- pytest: 1 AS10-equivalent atom fails LOUDLY without `APAP_TEST_POSTGRES_DSN` (correct contract); green in CI service container

### Pre-existing gates red at HEAD (NOT introduced by this slice, NOT in scope)
- `migration/apply.py` size (1154 vs baseline 1058) and mutation_sites (572 vs baseline 464)
- `migration/apply.py::_apply_value_transform` CC=22 vs budget 15
- `migration/cli.py` size (738 vs budget 700) and mutation_sites (463 vs baseline 443)
- `app/core/insforge.py` mutation_sites +1 site drift (F1.1 fix-up open)
- `check_ruff_ratchet`: ruff version mismatch on this Ubuntu image

## RDD audit trail

The M1 slice was reviewed under lineage `review-462a42960b25ac4c`, opened with `--base-ref=f724817 --workspace-overlay` covering 23 paths (SDD proposal + F1 source + F2 source + F3 source + test stubs).

Four lens captures admitted (state approved):
- review-risk: 4 findings
- review-resilience: 3 findings
- review-readability: 1 finding
- review-reliability: 15 findings (after filtering out 6 carry-over findings for M0 paths that fall outside the frozen scope)

**Total: 23 informational findings carried for fix-up work** in M1.5+. No BLOCKER or CRITICAL; all severities are WARNING or SUGGESTION.

Three prior lineages were abandoned during this slice:
- `review-92e5a998dbee63d9` — wrong --base-ref (too close to HEAD); abandoned via F2 starting with --base-ref f724817.
- `review-97a3bfe09c1113ff` — opened correctly with --base-ref f724817 but F3 commits landed AFTER lineage start; F3 was captured under the FINAL lineage `review-462a42960b25ac4c` instead.
- (earlier `review-cdcbb2a641e7b4e0` from the prior session carried forward).

## Architecture notes

### Backend seam (F1)
- `app/core/ports/{magic_link,mail_transport}_port.py` — two `runtime_checkable` Protocols
- `app/core/auth_magic/postgres_adapter.py` — psycopg.AsyncConnection with lazy `_ensure_schema` DDL
- `app/core/auth_magic/mail_transports.py` — `ConsoleMailTransport` (writes JSONL to `tests/mailbox.jsonl`) + `SMTPMailTransport` (NotImplementedError placeholder for M1.5)
- `app/core/migrations/sql/007_create_magic_link_tokens.sql` — DDL with `WHERE consumed_at IS NULL` partial index

### Route layer (F2)
- `app/core/auth_magic/routes.py` — `POST /auth/magic/start` + `GET/POST /auth/magic/verify`
- Cookie compat: reuses `write_session` + `issue_csrf_to_session` + `session_cookie_name` from `app/core/session.py` (itsdangerous URLSafeTimedSerializer) — NO new cookie name, NO new signing
- The verify route writes `apap_session` identical shape to the OAuth callback
- Lifespan wiring deferred to F3 (local backend process owns its own lifespan)

### Gate (F3)
- `app/core/local_backend/stub_auth_port.py` — in-memory `AuthUsersPort` for the round-trip test
- `app/core/local_backend/app.py` lifespan wires the 3 ports + magic router + `/_test/seed_user` route when `APAP_AUTH_ENABLE_MAGIC_LINK=true`
- `_BaseUrlAwareConsoleTransport` inlined in app.py to avoid editing `auth_magic/*` (per task constraint); M1.5 should promote it to auth_magic/mail_transports.py with real `settings.app_base_url` injection
- `migration/verify_fallback_ready.py::check_magic_link_local_round_trip` registered in CI_CHECKS + CI_CHECK_NAMES + ALL_CHECKS + ALL_CHECK_NAMES

### Deviation from spec

The M1 spec said `JWT HS256` for the session cookie. The codebase actually uses `itsdangerous.URLSafeTimedSerializer` (verified by reading `app/core/session.py`). F2's verify route follows the codebase convention rather than the spec, ensuring compatibility with the existing middleware (auth_dependencies_di reads via `read_session` against the same serializer).

## Readiness for M2

The M1 slice is complete and the magic-link flow is gated. M1.5 follow-up work (production wiring of SMTPMailTransport) is tracked in the 23 informational findings.

M2 (Coolify production deploy) is the next slice with its own spec at the parent `self-host-backend-coolify` change.

## Carry-over for M1.5+ (informational findings)

The reliability lens surfaced 15 reliability findings + 4 risk + 3 resilience + 1 readability = 23 informational findings total. Highlights (the rest are tracked in `tasks.md` under "Informational findings carried for fix-up work"):

- F1.1 — `app/core/insforge.py` mutation_sites +1 drift (carry from M0)
- F1.2–F1.3 — rawsql exception broadening (R3-018, R3-019)
- F1.4–F1.7 — Postgres adapter signal (R3-008 to R3-015)
- F2.1 — OAuth start_google_oauth Query max_length (R3-016, M0 carry-over)
- F2.2 — _BUCKETS race (R3-017, M0 carry-over)
- F2.3 — OAuth exchange_insforge_code exception (R3-020, M0 carry-over)
- F2.4 — psycopg.OperationalError not surfaced (R3-011)
- F2.5 — OAuth exchange ignores client_type (R3-021, M0 carry-over)
- F3.1 — _BaseUrlAwareConsoleTransport inlined in local_backend/app.py (R3-001)
- F3.5–F3.7 — StubAuthPort noise (R3-005, R3-006, R3-007)

None are blockers. All are tracked for M1.5 production wiring.
