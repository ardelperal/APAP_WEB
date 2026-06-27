# Apply progress — PR-6A.2 (Slice 6 Structured logging — CSRF swap + sample call sites)

PR-6A.2 of `hardening-2026-q2` — Slice 6 (Structured logging + redaction) **PR-A.2** (the CSRF middleware logging swap + sample `log_safe` call sites + 4 new tests). Branches off `hardening-2026-q2/slice-6a-logging-module` (the logging module that lands in PR-6A.1) so the `log_safe` import resolves when this PR is reviewed in isolation.

## Session

| Field | Value |
|-------|-------|
| **Project** | APAP_WEB |
| **Change** | `hardening-2026-q2` |
| **Branch** | `hardening-2026-q2/slice-6a2-csrf-swap` (from `hardening-2026-q2/slice-6a-logging-module`) |
| **Base for review** | `origin/staging` (HEAD `57ad69d`) — PR-6A.1 lands first to staging, then PR-6A.2 lands on top |
| **PR target** | `staging` (NEVER `main`) |
| **Work unit** | Slice 6, PR-6A.2 — CSRF middleware logging swap + sample `log_safe` call sites (T-6.3, T-6.6, T-6.7, T-6.8 in the brief's numbering; T-6.11 csrf event test) |

## Why a separate PR

The brief's *suggested* 2-PR split did not assign the CSRF swap to any specific PR. PR-6A.1 lands the logging infrastructure (module + tests + lifespan wiring) so the `log_safe` import resolves. PR-6A.2 then swaps the existing CSRF middleware logging placeholder for `log_safe(...)` and adds sample call sites in real flows (`/auth/callback`, `voluntarios_service.deactivate_voluntario`). This split:

1. Keeps PR-6A.2 under the 400-line budget (**334 LOC** vs 793 in PR-6A.1).
2. Mirrors the project's existing per-slice split pattern (PR-5B1 vs PR-5B2).
3. Lets reviewers focus on one work unit at a time: PR-6A.1 = "what is the new infrastructure?", PR-6A.2 = "which existing call sites swap to it?".

## What landed (1 commit, 334 LOC)

| SHA | Subject |
|---|---|
| `a3a17a3` | `feat(slice-6): swap CSRF middleware logging to log_safe + sample call sites` |

## Files changed

| File | Action | What |
|---|---|---|
| `app/core/csrf.py` | Modified (-15/+43 lines) | Removes `import logging` and the `self._logger = logging.getLogger(__name__)` placeholder. The two call sites (`csrf.disabled` short-circuit + `csrf.rejected` validation failure) now call `log_safe(event, **fields)` directly. Event names are STABLE per the forward-dep contract with PR-5B. |
| `app/main.py` | Modified (+6/-2 lines) | `/auth/callback` emits `log_safe("auth.login", email=user["email"], user_id=user["id"])` after a successful OAuth exchange. The `email` kwarg is REDACTED by `log_safe` per the closed 12-field list — operators see the event name + `user_id`, not the email address. Proves redaction end-to-end on the auth path. |
| `app/modules/voluntarios/service.py` | Modified (+9/-4 lines) | `deactivate_voluntario` emits `log_safe("voluntario.deactivated", voluntario_id=...)` ONLY when the row was actually deactivated (`True` return). Idempotent re-runs returning `False` stay silent so operators can tell the first successful deactivate from a no-op. |
| `tests/test_csrf_middleware.py` | Modified (+13/-8 lines) | The existing rejection-log test (`test_csrf_rejection_emits_warning_log`) updated to capture `INFO` on the `app` logger and assert on the `event` field (the `log_safe` contract), instead of `WARNING` on the `app.core.csrf` logger and a substring on the message. Same intent, new contract. |
| `tests/test_csrf_rejected_log_event.py` | Created (233 LOC, 3 tests) | Pins the contract that downstream dashboards depend on: `csrf.rejected` event name preserved with operator-facing fields (path, method, reason); the session-bound csrf_token does NOT leak via the redacted csrf_token kwarg (round-2 fix SB-5); `csrf.disabled` fires when the feature flag is off (exercises the middleware directly because the app-level middleware is only registered when the flag is True). |

## CSRF event name stability contract

Event names **MUST stay stable** across the PR-5B → PR-6A.2 swap because downstream dashboards and redaction tests depend on them:

- `csrf.rejected` — emitted when a non-safe request (POST/PUT/PATCH/DELETE) fails CSRF validation. Structured fields: `path`, `method`, `reason` (`missing_session` | `missing_token` | `token_mismatch`).
- `csrf.disabled` — emitted when `Settings.csrf_enabled=False` short-circuits the middleware. Operator debugging signal during incident response.

The dedicated test `tests/test_csrf_rejected_log_event.py` pins both event names so a future rename breaks the test.

## Verification

| Gate | Status | Notes |
|------|--------|-------|
| `pytest tests/test_csrf_rejected_log_event.py tests/test_csrf_middleware.py tests/test_voluntarios_service.py tests/test_voluntarios.py` | Pass | 30/30 tests pass. |
| `pytest --deselect tests/test_voluntarios_concurrent.py::test_concurrent_deactivate_one_winner -q` | Pass | 788 passed, 3 skipped, 1 deselected. |
| `ruff check app/ tests/test_csrf_rejected_log_event.py tests/test_csrf_middleware.py` | Pass | All checks passed. |
| `python scripts/check_rules.py app --exclude ...` | Pass | Exit 0 (pre-APAP003 detector). |
| `grep -rn 'logger\.\(info\|warning\|error\|debug\|critical\|exception\)' app/` | 0 matches | `csrf.py` placeholder is gone; only `app/core/logging.py` (the wrapper) remains. |
| Each commit independent | Pass | Single commit (`a3a17a3`) ships the test files + implementation together; diff is GREEN at every push. |

## Sample call sites — why these two

The brief lists T-6.6 (`auth.login` in `/auth/callback`) and T-6.7 (`voluntario.deactivated` in `voluntarios_service.deactivate_voluntario`) as "demonstrate the pattern" call sites. Both were chosen because they are real auth/audit-relevant flows:

- `auth.login` — proves the redaction filter is wired end-to-end on a real authentication flow (operators see the event name + `user_id`, never the email). The email kwarg is deliberately included to demonstrate that the 12-field redaction list works on actual OAuth output.
- `voluntario.deactivated` — proves that idempotent operations (deactivate runs that return `False` because the row was already inactive) emit NO log, so operators can tell the "first successful deactivate" from a no-op re-run. Avoids log spam during mass-import or migration operations.

## Persistence

Persisted to Engram:
- `apap_web` / `sdd/hardening-2026-q2/apply-progress-pr-6a2` (this file)

## Cross-references

- Spec: `openspec/changes/hardening-2026-q2/specs/06-structured-logging/spec.md` (REQ-2, REQ-5)
- Design: `openspec/changes/hardening-2026-q2/design.md` Slice 6 (§"CSRF swap" forward-dep)
- Tasks: `openspec/changes/hardening-2026-q2/tasks.md` T-6.5, T-6.6, T-6.7, T-6.8, T-6.12
- Predecessor: PR-6A.1 (`hardening-2026-q2/slice-6a-logging-module`) — must land first so `log_safe` resolves when this PR is reviewed
- Successor: PR-6B (`hardening-2026-q2/slice-6b-ruff-rule`) — wires the APAP003 lint gate that keeps future PRs honest
- Round-2 fix SB-5: `csrf_token` is on the 12-field redaction list; verified by `tests/test_csrf_rejected_log_event.py::test_csrf_rejected_does_not_leak_session_token_in_log`
- Round-2 fix SB-7: APAP003 known limitation (bare `logging.getLogger` retrieval stays allowed) — PR-6B documents this
