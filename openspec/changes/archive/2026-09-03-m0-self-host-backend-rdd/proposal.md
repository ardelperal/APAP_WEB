# Proposal: m0-self-host-backend-rdd

skill_resolution: paths-injected (sdd-propose, web-tdd-philosophy, codegraph-vba-upstream-sync)

## Why a fresh slice

The previous attempt at M0 (PR #643, branch `feat/641-self-host-backend-coolify`) accumulated **12 commits** of CI fixes in response to gate failures that surfaced late. Each fix exposed the next, producing a per-push CI loop where each run surfaced a different pre-existing rule violation. The cumulative cost was high (operator time + several merge-blockers like the mutation-sites ratchet) because the work was pushed without a full local-gate run.

This slice restarts M0 under strict SDD + TDD + RDD:

1. **Spec first** (`specs/m0-backend/spec.md`) with all 10 acceptance scenarios pinned before any code is written.
2. **Tests first** (TDD RED) so the gate that catches regressions is the same code that proves the feature.
3. **Local-gate run** (`ruff check`, `mypy`, `python scripts/check_*.py`, `pytest`) before commit. If a gate fails, fix locally; never push a failing gate.
4. **One commit per feature** (F1, F2, F3), each ≤400 lines, each independently reviewable.
5. **RDD lifecycle** — `gentle-ai review start` per feature; the receipt is burned by the approving capture; the human (or RDD-approved validator) acknowledges the burn before the next feature starts.

The kill switch is enabled globally before this work started (`gentle-ai review mode enable --scope global`); the wrapper is `gentle-pi@2.3.0` (latest stable, carries `gentle-ai v2.5.0`); the active binario is `gentle-ai v2.5.1` (latest main). Per the release notes, SDD slash commands carry the `gentle-sdd-` prefix in 2.5.0+.

## Causal authority and rollback

- **Invariant**: the local backend (FastAPI router + Postgres connection pool) substitutes the InsForge HTTP endpoints the application actually calls. The application-side `InsForgeClient` does not change — only the base URL when `APAP_LOCAL_BACKEND=true`.
- **Rollback**: revert the merge commit; the local backend modules are removed; `APAP_LOCAL_BACKEND` is unset by default so no production change.
- **Independent invariants**: M0 (this slice) is independent of M1 (classic auth) and M2 (Coolify deploy). M1 depends on M0; M2 depends on M0. Both M1 and M2 are out of scope and become separate slices after M0 merges.

## Operator flows that this slice proves

- **O1.** Operator sets `APAP_LOCAL_DB_URL=postgresql://...` and `APAP_LOCAL_BACKEND=true`; the app boots against the local backend instead of InsForge.
- **O2.** Operator runs `python -m migration.cli_verify_fallback_ready --ci-only`; the gate returns 0; the `web_to_legacy_check_only` check is green against the local backend.
- **O3.** Operator can run `curl http://localhost:8000/healthz` (when `APAP_LOCAL_BACKEND=true`); the response is `{"db": "up", "storage": "up", "oauth": "configured"}`.
- **O4.** Operator can run `curl http://localhost:8000/api/auth/oauth/google?code_challenge=abc&redirect_uri=http://x/cb`; the response is `{"authUrl": "https://accounts.google.com/..."}` — the stub.

Negative controls:
- The local backend factory MUST raise `RuntimeError` if `db_dsn` is empty — proves the gate cannot be bypassed.
- `POST /api/database/advance/rawsql` MUST reject unsafe identifiers (`DROP TABLE users; --`) — proves SQL injection is not possible through this surface.
- `POST /api/database/advance/rawsql` MUST reject multi-statement queries — proves statement injection is not possible.

## Decisions

1. **Three-feature chain (F1, F2, F3)** instead of a single 930-line PR — each feature fits the 400-line budget, has its own spec + tests + RDD lineage, and is independently reviewable. This is a chain candidate per the deterministic-quality-harness Rule 12.
2. **In-memory bucket stub for M0** — no real S3/MinIO. M2 ships the real MinIO adapter; M0 just needs the contract to be stable so the swap is transparent to `InsForgeClient`.
3. **Stub OAuth JWT in M0** — no real Google OAuth (the agent cannot run the interactive consent flow). The contract is stable so M3+ can swap in the real provider without touching the client.
4. **Test seam uses lazy imports inside helper bodies** — `LocalPostgresExecutor.execute` does `from migration.apply import compute_accdb_hash` inside the function body so `monkeypatch.setattr("migration.apply.compute_accdb_hash", ...)` (used by `tests/migration/test_apply_safety.py`) flows through. Hoisting the import at module level would freeze the binding to the production function and break the test seam.
5. **Safe-identifier regex applied to each dotted segment** of the query — `DROP TABLE users; --` is rejected because `users` matches but `; --` does not; multi-statement is rejected by counting top-level `;` outside string literals.

## What this slice does NOT do

- Real Google OAuth integration (requires interactive consent the agent cannot run unattended)
- Real SMTP for magic-link delivery (M1+)
- MinIO / S3 storage backend (M2)
- Coolify deployment manifest (M2)
- InsForge deprecation (a separate epic after M2)

## Scope of the chain

| Feature | Scope | Forecast | Dependencies |
|---|---|---|---|
| F1. M0-foundation | `LocalPostgresExecutor` + rawsql handler + factory + InsForgeClient URL switch + 4 tests | ~200 lines | None |
| F2. M0-routes | healthz + storage + oauth_google stubs + 5 tests | ~350 lines | F1 (needs the executor + factory) |
| F3. M0-client-switch | verify-fallback-ready local-backend spawn + 1 test | ~150 lines | F1, F2 (needs all the routers) |

Each feature carries its own spec + tasks + tests + RDD lineage. Each is independently reviewable.

## Verification (per the deterministic-quality-harness v1.5)

After all three features merge:

- [ ] `ruff check .` clean
- [ ] `mypy app/core/local_backend/ app/core/insforge.py` clean
- [ ] `python scripts/check_module_size.py` clean (each new file ≤700 lines)
- [ ] `python scripts/check_mutation_sites.py` clean (each new file ≤250 sites)
- [ ] `python scripts/check_complexity.py` clean (no function with CC>15)
- [ ] `python scripts/check_ruff_ratchet.py` clean (no rule count above its current baseline)
- [ ] `python scripts/check_rules.py` clean (no AGENTS-rules violations)
- [ ] `python scripts/check_layers.py` clean
- [ ] `python scripts/check_slice_completeness.py` clean
- [ ] `python scripts/check_alantyle.py` clean
- [ ] `uv run pytest tests/integration/test_local_backend.py tests/integration/test_insforge_client_url.py tests/migration/test_verify_fallback_local_backend.py` all green
- [ ] `python -m migration.cli_verify_fallback_ready --ci-only` exits 0 on the local backend

## Open decisions for the maintainer

- Approve the chain (F1 → F2 → F3) as a single slice chain with three receipts, OR treat each feature as a separate slice with its own issue and receipt? Default: chain (the features have a causal order — F1 builds the foundation F2 mounts onto, F3 verifies the whole).
- Accept the forecast overage on `oauth_google.py` (potentially 100 lines for the JWT helper + handler trio). Mitigation: split into `oauth_starts.py` + `oauth_callbacks.py` if the file exceeds 700 lines or 250 sites.
- Confirm the operator-delivery story for the magic-link tokens (M1) before M1 starts. Not in scope here.
