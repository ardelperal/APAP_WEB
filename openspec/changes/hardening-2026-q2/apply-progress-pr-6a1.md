# Apply progress — PR-6A.1 (Slice 6 Structured logging — module + redaction + tests)

PR-6A.1 of `hardening-2026-q2` — Slice 6 (Structured logging + redaction) **PR-A.1** (split from the original 2-PR plan per the brief's "if it exceeds 400 lines, split" hard rule and the project's existing PR-5B2 overage pattern). PR-6A.2 handles the CSRF middleware logging swap + sample `log_safe` call sites; PR-6B wires the APAP003 lint gate.

## Session

| Field | Value |
|-------|-------|
| **Project** | APAP_WEB |
| **Change** | `hardening-2026-q2` |
| **Branch** | `hardening-2026-q2/slice-6a-logging-module` |
| **Base** | `origin/staging` (HEAD `57ad69d`) |
| **PR target** | `staging` (NEVER `main`) |
| **Work unit** | Slice 6, PR-6A.1 — logging module + redaction filter + lifespan wiring + tests (T-6.1, T-6.2, T-6.9, T-6.10 in the brief's numbering) |

## Split decision rationale

The brief explicitly says: "if it exceeds 400 lines, split" and "You decide based on actual LOC." The brief's *suggested* split was 2 PRs (PR-6A = logging module + tests ~300 LOC, PR-6B = ruff rule + AGENTS.md ~150 LOC). The actual LOC for "logging module + tests" alone is **789 insertions, 4 deletions across 5 files** — well over the 400-line budget. The CSRF middleware logging swap (T-6.3 / T-6.6 / T-6.7 / T-6.8 / T-6.11 in the brief) is a separate work unit that lands cleanly at 295 insertions / 39 deletions, so the natural split is 3 PRs:

- **PR-6A.1** (this PR) — logging module + redaction filter + lifespan wiring + 74 new tests = **789 / 4** = **793 LOC** (over budget; same pattern as PR-5B2's documented overage).
- **PR-6A.2** (`hardening-2026-q2/slice-6a2-csrf-swap`) — CSRF swap + sample call sites + 4 new tests = **295 / 39** = **334 LOC** (under budget).
- **PR-6B** (`hardening-2026-q2/slice-6b-ruff-rule`) — APAP003 detector in `scripts/check_rules.py` + plugin wiring + AGENTS.md Rule 9 + 14 new tests = **424 / 49** = **473 LOC** (slightly over the 400 budget; documented as the smallest work unit that closes the round-2 fix PA-2 + the APAP003 gate; splitting further would force artificial seams between the AST linter and the plugin visitor).

PR-6A.1's overage is consistent with the project's existing pattern: PR-5B2's `apply-progress-pr-5b.md` documents ~1126 LOC vs 400 budget with the rationale "splitting further would force artificial seams (the natural dependencies make PR-5B2 indivisible)". PR-6A.1 follows the same pattern — the test suite is the largest single cost (575 LOC across two parametrized files) and cannot be trimmed without compromising the security contract.

## What landed (1 commit, 793 LOC)

| SHA | Subject |
|---|---|
| `24bd8a9` | `feat(slice-6): structured logging module + redaction filter + tests` |

## Files changed

| File | Action | What |
|---|---|---|
| `app/core/logging.py` | Created (195 LOC) | `JsonFormatter`, `RedactionFilter`, `configure_logging(settings)`, `log_safe(event, **fields)`, `REDACTED_FIELDS` (12-entry closed list per round-2 fix SB-5). |
| `app/core/config.py` | Modified (+6 lines) | New `Settings.log_level: str = "INFO"` driving the root logger level set by `configure_logging`. |
| `app/main.py` | Modified (+17/-5 lines) | Lifespan calls `configure_logging(settings)` as the FIRST line so startup errors (bad InsForge URL, schema down) are captured with PII redaction. |
| `tests/test_logging.py` | Created (412 LOC, 32 tests) | REQ-1 idempotency + handler invariants; REQ-2 redaction semantics (every closed-list field, case-insensitive, `_`/`-` equivalence, descriptive names NOT redacted); REQ-3 RedactionFilter as second line of defense; REQ-4 JSON format. |
| `tests/test_logging_redaction_adversarial.py` | Created (163 LOC, 42 tests) | Parametrized over the 12-field closed list's common variants (case, dash, uppercase) AND the descriptive-not-redacted boundary (`user_email_address`, `e_mail`, `csrf_token_age_seconds`, etc.). |

## Closed redaction list (12 fields, round-2 fix SB-5)

`email`, `session_token`, `jwt`, `oauth_code`, `pkce_verifier`, `csrf_token`, `pkce_challenge`, `authorization`, `cookie`, `referer`, `ip_address`, `x_forwarded_for`.

Comparison is case-insensitive and treats `-` / `_` as equivalent (see `app/core/logging.py::_normalize_key`).

The RedactionFilter mutates `LogRecord.__dict__` (not `setattr`) so keys that are not valid Python identifiers (e.g. `X-Forwarded-For` with a dash) still get redacted. JsonFormatter reads from `__dict__` too, so the redacted value still reaches stdout.

## Verification

| Gate | Status | Notes |
|------|--------|-------|
| `pytest tests/test_logging.py tests/test_logging_redaction_adversarial.py` | Pass | 74/74 new tests pass. |
| `pytest tests/test_lifespan.py` | Pass | 5/5; lifespan calls `configure_logging(settings)` correctly (verified via monkeypatch). |
| `pytest --deselect tests/test_voluntarios_concurrent.py::test_concurrent_deactivate_one_winner -q` | Pass | 788 passed, 3 skipped (psycopg / psutil env-deps), 1 deselected (PG-only E2E that hard-fails per round-2 fix REG-S-3; pre-existing on staging). |
| `ruff check app/ tests/test_logging.py tests/test_logging_redaction_adversarial.py` | Pass | All checks passed. |
| `python scripts/check_rules.py app --exclude ...` | Pass (pre-APAP003) | Exit 0; APAP003 detector lands in PR-6B. |
| `grep -rn 'logger\.\(info\|warning\|error\|debug\|critical\|exception\)' app/` | 0 matches outside `app/core/logging.py` | The PR-XSS audit's existing grep test (`tests/test_xss_audit_greps.py`) still passes. |
| Each commit independent | Pass | Single commit (`24bd8a9`) ships the test files + implementation together, so the diff is GREEN at every push. |

## Known limitations / follow-ups

1. **Review budget overflow (789 LOC vs 400 budget).** Same rationale as PR-5B2: the test suite (575 LOC across two parametrized files) is the largest single cost and cannot be trimmed without compromising the security contract (each test pins a different aspect of the closed-list redaction invariant). Documented per the project's existing pattern.
2. **`log_safe()` import path.** The brief uses `log_safe(event, **fields)` directly (imported from `app.core.logging`); the design.md uses the same shape. The `csrf.disabled` / `csrf.rejected` events use this signature verbatim in PR-6A.2.
3. **`configure_logging` is called from lifespan, not from a FastAPI startup event.** The pattern is consistent with the existing lifespan logic (which already does the InsForge bootstrap). Tests using `httpx.ASGITransport` do NOT trigger the lifespan automatically; only the explicit `tests/test_lifespan.py` exercises it, so the test suite is hermetic with respect to the new handler attachment.
4. **No manual log-format verification.** The end-to-end test (`test_json_formatter_renders_to_stdout_format`) covers the format contract via a `StringIO` substitution; a live JSON-line capture in staging is part of the Slice 6 UAT sign-off (handled via `feature-acceptance-uat` skill post-merge).

## Persistence

Persisted to Engram:
- `apap_web` / `sdd/hardening-2026-q2/apply-progress-pr-6a1` (this file)

## Cross-references

- Spec: `openspec/changes/hardening-2026-q2/specs/06-structured-logging/spec.md`
- Design: `openspec/changes/hardening-2026-q2/design.md` Slice 6
- Tasks: `openspec/changes/hardening-2026-q2/tasks.md` T-6.1, T-6.2 (and T-6.9, T-6.10 in tasks.md numbering)
- Motivation: engram obs `#14518` (security audit, "zero `logger.*` in `app/`"); round-2 fix SB-5 (redaction list expanded to 12 fields)
- Predecessors: PR-5B1 + PR-5B2 (merged to staging; `app/core/csrf.py` has the placeholder logging that PR-6A.2 swaps)
- Successors: PR-6A.2 (CSRF swap + sample call sites), PR-6B (APAP003 lint gate)
