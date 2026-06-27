# Tasks — hardening-2026-q2

## Overview
- 7 design slices → up to 11 PRs (slices 1, 5, 6 split for review budget)
- Each PR ≤400 LOC changed (HARD LIMIT per `review_budget_lines: 400`)
- Apply order: 1 → 2 → 3 → 4 → 5 (PR-A → PR-B) → 6 → 7
- Parallelizable: (2, 3), (7, 5), (7, 6)
- TDD-first: failing test before implementation for every behavior-introducing task

---

## Cross-cutting preflight (BEFORE any slice)

- [ ] **T-PRF-1**: Verify `ci-cd-foundation` change status — if not merged, Slice 1 lands as feature-branch-chain child and wires into the workflow when `ci-cd-foundation` lands
- [ ] **T-PRF-2**: Confirm staging deploy is healthy — run `make all` on staging HEAD; must pass before any slice lands
- [ ] **T-PRF-3**: Communicate SESSION_SECRET rotation (Slice 3) to stakeholders ≥24h before apply; confirm operator has generated a new secret

---

## Slice 1 — Dev tooling gate

**Estimated LOC**: ~550 total (~250 impl + ~300 tests)
**Decision**: SPLIT into two PRs. If either PR still exceeds 400 LOC after splitting, escalate to user before opening.

### PR-1A — AST linter + tests (≤400 LOC)

- [ ] **T-1A.1**: Create `scripts/check_rules.py` with `find_violations(repo_root: Path) -> list[Violation]` and `Violation` dataclass (fields: `file`, `line`, `rule_id`, `message`)
- [ ] **T-1A.2**: Implement Detector 1 (Rule 1): `route_uses_execute_sql` — AST scan for `client.execute_sql(...)` inside any function decorated with `@router.{post,put,patch,delete}` or `@application.{post,put,patch,delete}`; skip GET handlers
- [ ] **T-1A.3**: Implement Detector 2 (Rule 6): `auth_defaults_true` — `payload.get("is_authorized", True)` in `app/core/auth*.py`
- [ ] **T-1A.4**: Implement Detector 3 (Rule 7): `http_exception_redirect` — `HTTPException(status_code=302, ...)` anywhere in `app/`, resolve alias chains (e.g. `from fastapi import HTTPException as HE`)
- [ ] **T-1A.5**: Implement Detector 4 (Rule 4, partial): `hardcoded_role_check_in_ddl` — literal `CHECK (rol IN (` in any `app/**/*.py` string
- [ ] **T-1A.6**: Create `tests/_rule_helpers/fixtures/route_executes_sql.py` — a handler `@router.post("/x")` calling `client.execute_sql("SELECT 1", [])`; verify the script detects it
- [ ] **T-1A.7**: Create `tests/test_check_rules.py` — parametrized over 4 positive fixtures (one per detector) and 4 negative cases (clean code not flagged); assert exit code 1 on violations, 0 on clean
- [ ] **T-1A.8**: Modify `Makefile` — add `check-rules` target calling `python scripts/check_rules.py app/`; add comment explaining it runs AFTER `ruff check .`

### PR-1B — Ruff plugin + pytest coverage gate (≤400 LOC)

- [ ] **T-1B.1**: Create `scripts/ruff_plugin/apap_rules.py` with APAP001 (Rule 1 detector, AST-based, mirrors Detector 1 from T-1A.2)
- [ ] **T-1B.2**: Modify `pyproject.toml` — add `[tool.ruff.lint] select = [..., "APAP"]` and register the plugin in `[tool.ruff] plugin`; register APAP003 **plugin** here (T-5.4 will add it to the `select` list — do NOT add APAP003 to `select` in this task; CI between Slice 1 and Slice 5 must not break on raw `logger.*` calls)
- [ ] **T-1B.3**: Create `tests/_rule_helpers/critical_helpers_gate.py` — pytest plugin with `pytest_addoption` for `--coverage-gate-config` (default `pyproject.toml [tool.apap.coverage_gate]`)
- [ ] **T-1B.4**: Define `CRITICAL_HELPERS: frozenset[str]` with regex auto-discovery of `_row_to_*` plus the named list `{_redirect, _render_form, _is_duplicate_error, _validate_create_params, _build_insert_params}` — every `_row_to_*` added automatically
- [ ] **T-1B.5**: Implement coverage gate: after `pytest` produces `coverage.json`, parse and fail if any `CRITICAL_HELPERS` entry has <100% line coverage; emit warning (not fail) if `CRITICAL_HELPERS` is empty
- [ ] **T-1B.6**: Modify `pyproject.toml` — add `[tool.pytest.ini_options] addopts += ["-p", "tests._rule_helpers.critical_helpers_gate"]`
- [ ] **T-1B.7**: Create `tests/test_ruff_apap001.py` — exercises the ruff plugin via `ruff.api.run_check` or subprocess fallback; verify it detects the seeded violation and passes on clean code
- [ ] **T-1B.8**: Create `tests/test_coverage_gate.py` — synthetic `pytest --cov` run that forces one helper to 99% via `# pragma: no cover` on one line; assert the gate fires with the helper name in the message

---

## Slice 2 — Rule 4 DDL fix

**Estimated LOC**: ~110 total (~30 impl + ~80 tests)
**Decision**: SINGLE PR (well under budget)

### T-2.1 — Drop CHECK constraint

- [ ] **T-2.1**: Read `app/core/auth.py:55-64` — confirm current `CREATE_TABLE_SQL` includes `CHECK (rol IN ('developer', 'admin', 'key_user', 'reader'))`
- [ ] **T-2.2**: Modify `CREATE_TABLE_SQL` — remove the CHECK constraint clause; keep `rol TEXT NOT NULL`
- [ ] **T-2.3**: Verify `add_authorized_user` (`app/core/auth.py:132-145`) still raises `ValueError` on invalid role — regression check only

### T-2.2 — Migration script

- [ ] **T-2.4**: Create `migration/004_drop_rol_check.sql` with `ALTER TABLE usuarios_autorizados DROP CONSTRAINT IF EXISTS usuarios_autorizados_rol_check;`
- [ ] **T-2.5**: Register the migration in the existing migration loader (find the pattern in `app/core/migration/`)

### T-2.3 — Tests

- [ ] **T-2.6**: Create `tests/test_migration_004.py` — runs the migration forward + backward against a sandbox DB; verifies idempotency (exit 0 on second run)
- [ ] **T-2.7**: Verify existing `tests/test_auth.py` still passes
- [ ] **T-2.8**: Add `tests/test_auth.py::test_add_authorized_user_accepts_all_known_roles` — parametrized over `Rol` enum members

### T-2.4 — Migration safety check (CRITICAL — blocking)

- [ ] **T-2.9**: **BLOCKER** — Before opening the PR, run `psql -c "\d usuarios_autorizados"` against staging. If the constraint name is NOT `usuarios_autorizados_rol_check`, abort with `MIGRATION_CONSTRAINT_NAME_UNEXPECTED` and report to user. Do not open the PR until this passes.

---

## Slice 3 — Rule 6 cookie rotation + flip default (P0)

**Estimated LOC**: ~215 total (~15 impl + ~120 tests + ~80 runbook)
**Decision**: SINGLE PR (under budget)

### T-3.1 — Flip default

- [ ] **T-3.1**: Modify `app/main.py:165` — `payload.get("is_authorized", True)` → `payload.get("is_authorized", False)`
- [ ] **T-3.2**: Modify `app/core/auth_dependencies.py:130` — same flip; update docstring at lines 110-127 to reflect new semantics
- [ ] **T-3.3**: Verify both call sites — `grep -n 'payload.get("is_authorized"' app/` should return 0 `True` defaults

### T-3.2 — Runbook

- [ ] **T-3.4**: Create `docs/runbooks/cookie-rotation.md` with sections: (a) When to rotate, (b) Pre-deploy checklist, (c) Deploy steps (staging first), (d) Verification (`/healthz` + log `BadSignature` rate), (e) Production steps, (f) Rollback
- [ ] **T-3.5**: Modify `README.md` — add "Session secret rotation" section pointing to the runbook

### T-3.3 — Tests

- [ ] **T-3.6**: Update `tests/test_auth_dependencies.py::test_require_authorized_user_default_false` — verify default is now `False`
- [ ] **T-3.7**: Create `tests/test_auth_dependencies.py::test_require_rechaza_sesion_sin_flag` — session without `is_authorized` flag redirects to `/unauthorized`
- [ ] **T-3.8**: Create `tests/test_middleware_is_authorized.py::test_middleware_default_false` — same for middleware path
- [ ] **T-3.9**: Create `tests/test_session_rotation.py::test_rotation_invalidates_old_cookies` — sign cookie with `secret="v1"`, read with `secret="v2"`, assert `None`

### T-3.4 — AGENTS.md cleanup

- [ ] **T-3.10**: Modify `AGENTS.md:307` — mark Rule 6 row DONE; remove "Deliberate" note and pre-fix session note

---

## Slice 4 — XSS Audit

**Estimated LOC**: ~300 total (~180 impl/doc + ~120 tests)
**Decision**: SINGLE PR (audit-only, well under budget; only blocks if High findings found)

### T-4.1 — Audit document

- [ ] **T-4.1**: Create `docs/audits/xss-audit-2026-Q2.md` — scope (8 templates), methodology, findings table (severity | location | description | resolution), verdict PASS/FAIL
- [ ] **T-4.2**: For each of the 8 templates — enumerate all `{{ var }}`, `|safe`, `Markup()`, and `response_class=HTMLResponse` routes; document each potential injection point in the report

### T-4.2 — Auto-tests

- [ ] **T-4.3**: Create `tests/test_xss_audit.py` — parametrized over 8 templates × 2 patterns (`<script>alert(1)</script>`, `<img src=x onerror=alert(1)>`); for each pair, render template and assert the pattern is HTML-escaped (not raw in output)
- [ ] **T-4.4**: Run `pytest tests/test_xss_audit.py`; if any test fails, classify the finding and update the audit report accordingly (High → fix in this PR; Medium/Low → numbered issue)

### T-4.3 — Manual review backstop

- [ ] **T-4.5**: Open each of the 8 templates in a browser; paste test inputs in every form field; verify no JS executes; document results in `xss-audit-2026-Q2.md`
- [ ] **T-4.6**: If manual review finds additional High/Medium findings, update the audit report and open numbered issues; PR cannot merge with unfixed High findings

### T-4.4 — Verdict

- [ ] **T-4.7**: Finalize `docs/audits/xss-audit-2026-Q2.md` — write final verdict: PASS (0 High) or FAIL (1+ High, with fix list required before chain continues)
- [ ] **T-4.8**: If verdict is FAIL: open `PR-04A-XSSfix` before continuing; block Slice 5 until `PR-04A-XSSfix` lands

---

## Slice 5 — Auth hardening (MERGED: Rule 7 verify + audit + CSRF defense)

**Estimated LOC**: ~1020 total (~500 impl + ~400 tests + ~120 audit doc)
**Decision**: MUST SPLIT into PR-A (audit doc, ≤120 LOC) and PR-B (CSRF middleware, ~900 LOC). If PR-B still exceeds 400 LOC after the split below, split further into PR-B1 (middleware + tests) and PR-B2 (template edits + test migration).

### PR-A — Audit doc only (≤400 LOC)

#### T-5A.1 — Auth audit document

- [x] **T-5A.1**: Create `docs/audits/auth-dependencies-audit-2026-Q2.md` — scope, methodology, findings table (ID | Severity | Location | Description | Resolution), resolution log
- [x] **T-5A.2**: For cada función pública en `app/core/auth_dependencies.py` — documentar firma, callers (usar `codegraph_explore`), cobertura de tests, oportunidades de consolidación con `app/core/csrf.py`
- [x] **T-5A.3**: Clasificar cada finding: Low → resuelto en PR-B; Medium → follow-up issue numerado; High → fixed in PR-B
- [x] **T-5A.4**: Crear `tests/test_rule_7_compliance.py::test_uses_redirectresponse_not_http_exception` — `inspect.getsource(require_authorized_user)` asserts no `HTTPException(status_code=302`
- [x] **T-5A.5**: Modificar `AGENTS.md:308` — marcar Rule 7 row DONE; referenciar el audit doc

#### Pre-slice form audit (before any code)

- [x] **T-5A.6**: Run `grep -rn 'method="post" action=' app/templates/ | sort` contra main actual — capturar output; assert exactamente 10 forms; mapear cada uno a su handler route

### PR-B — CSRF middleware + SameSite=Strict + tests (may split further)

#### T-5B.1 — SameSite=Strict

- [ ] **T-5B.1**: Modificar `app/main.py:307` — `apap_session` cookie: `samesite="lax"` → `samesite="strict"`
- [ ] **T-5B.2**: Modificar `app/main.py:253` — `apap_pkce` cookie: `samesite="lax"` → `samesite="strict"`
- [ ] **T-5B.3**: Modificar `app/core/session.py:73` (`clear_session_cookie_params`) — `samesite="lax"` → `samesite="strict"`

#### T-5B.2 — CSRF token generation and session injection

- [ ] **T-5B.4**: Create `app/core/csrf.py` with `generate_csrf_token()`, `issue_csrf_to_session(payload)`, `validate_csrf(request, payload)`, `CSRFValidationError`, `CsrfMiddleware(BaseHTTPMiddleware)` — per design contract in `design.md:258-340`
- [ ] **T-5B.5**: Modificar `/auth/callback` handler in `app/main.py` — generate `csrf_token = secrets.token_urlsafe(32)` and add to session payload under `"csrf_token"`
- [ ] **T-5B.6**: Modificar `app/main.py` context for all `TemplateResponse` calls (~10 sites) — inject `csrf_token` from `request.state.csrf_token` into each template context dict
- [ ] **T-5B.7**: Registrar `CsrfMiddleware` in `app/main.py:create_app` AFTER session middleware but BEFORE route handling; wrap in `if settings.csrf_enabled:` for feature-flag rollback
- [ ] **T-5B.8**: Add `Settings.csrf_enabled: bool = True` to `app/core/config.py`

#### T-5B.3 — Template injection (the 10 POST forms)

- [ ] **T-5B.9**: Modificar `templates/admin/admin.html` — add `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">` to: (a) the add-user form (action `/admin/users`), (b) the deactivate form (action `/admin/users/{id}/deactivate`)
- [ ] **T-5B.10**: Modificar `templates/animales/form.html` — add hidden CSRF input (covers both create `/animales` and update `/animales/{id}/update` routes — same template)
- [ ] **T-5B.11**: Modificar `templates/animales/detail.html` — add hidden CSRF input to delete form (action `/animales/{id}/delete`)
- [ ] **T-5B.12**: Modificar `templates/entradas/form.html` — add hidden CSRF input (covers create + update)
- [ ] **T-5B.13**: Modificar `templates/entradas/detail.html` — add hidden CSRF input to delete form (action `/entradas/{id}/delete`)
- [ ] **T-5B.14**: Modificar `templates/voluntarios/form.html` — add hidden CSRF input to create form (action `/voluntarios`)
- [ ] **T-5B.15**: Modificar `templates/voluntarios/detail.html` — add hidden CSRF input to deactivate form (action `/voluntarios/{id}/deactivate`)
- [ ] **T-5B.16**: Modificar `templates/base.html` — add `{% block csrf_token %}{% endblock %}` for global injection; add the hidden input inside the block

#### T-5B.4 — Test infrastructure

- [ ] **T-5B.17**: Add `make_csrf_request(client, method, url, *, csrf_token=None, form_data=None, headers=None)` to `tests/conftest.py:50-90` — reads session cookie, decodes payload, attaches `X-CSRFToken` header; explicit `csrf_token` override for cross-session adversarial tests
- [ ] **T-5B.18**: Create `tests/test_make_csrf_request.py` — parametrized; verifies the helper attaches the right header and form field

#### T-5B.5 — New middleware tests

- [ ] **T-5B.19**: Create `tests/test_csrf_middleware.py` — parametrized over: happy path (valid token via header), happy path (valid token via form field), missing token (403), wrong token (403), session A cookie + session B token (403), GET request bypassed, `csrf_enabled=False` skips middleware
- [ ] **T-5B.20**: Create `tests/test_all_post_forms_have_csrf_input.py` — parametrized over the 10 handlers; fetches rendered HTML; asserts hidden input `name="csrf_token"` is present
- [ ] **T-5B.21**: Create `tests/test_csrf.py::test_callback_emits_csrf_token` — full OAuth roundtrip; decode session cookie; assert `csrf_token` present and ≥32 chars
- [ ] **T-5B.22**: Add cookie SameSite assertions to `tests/test_session.py` — verify `SameSite=Strict` on `apap_session` and `apap_pkce` cookies

#### T-5B.6 — Existing test migration to `make_csrf_request`

- [ ] **T-5B.23**: Migrate `tests/test_admin.py` POST calls to `make_csrf_request` (~30 LOC)
- [ ] **T-5B.24**: Migrate `tests/test_animals_routes.py` POST calls to `make_csrf_request` (~30 LOC)
- [ ] **T-5B.25**: Migrate `tests/test_entradas_routes.py` POST calls to `make_csrf_request` (~25 LOC)
- [ ] **T-5B.26**: Migrate `tests/test_voluntarios_routes.py` POST calls to `make_csrf_request` (~25 LOC)

#### T-5B.7 — Logging placeholder (forward-dep on Slice 6)

- [ ] **T-5B.27**: In `app/core/csrf.py` `dispatch()` — on CSRF rejection, log via `logging.getLogger(__name__).warning("csrf.rejected", extra={"path": request.url.path, "reason": ...})` — NOT `log_safe()` yet (Slice 6 swaps this); also log `"CSRF middleware disabled by settings"` when `csrf_enabled=False`

### PR-B split check

> **APPLY GATE**: Count actual LOC after T-5B.3 (SameSite) + T-5B.4 (CSRF module) + T-5B.5 (token generation) are implemented. If the diff for PR-B (before templates + test migration) exceeds 400 LOC, split PR-B into:
> - **PR-B1**: T-5B.1 + T-5B.2 + T-5B.3 + T-5B.4 + T-5B.5 + T-5B.7 (SameSite + CSRF module + token generation + logging placeholder)
> - **PR-B2**: T-5B.6 + T-5B.8 + T-5B.9-16 + T-5B.17-26 (template injection + test helper + new tests + test migration)
> Document the actual LOC count in the PR description.

---

## Slice 6 — Structured logging + redaction

**Estimated LOC**: ~450 total (~120 impl + ~300 tests + ~30 ruff plugin)
**Decision**: SPLIT into PR-6A (logging module + tests, ~420 LOC) and PR-6B (ruff APAP003 rule, ~30 LOC)

### T-6.1 — Logging module

- [ ] **T-6.1**: Create `app/core/logging.py` with `configure_logging(settings)`, `log_safe(event: str, **fields)`, `JsonFormatter`, `RedactionFilter` — per design contract in `design.md:396-482`
- [ ] **T-6.2**: Modify `app/main.py:97` (lifespan) — first line: `configure_logging(settings)`; must run BEFORE any `ensure_schema_and_seed` or client init

### T-6.2 — Ruff rule APAP003

- [ ] **T-6.3**: Add APAP003 to `scripts/ruff_plugin/apap_rules.py` — bans raw `logger.{info,warning,error,debug,critical,exception}(...)` in `app/**` except `app/core/logging.py`
- [ ] **T-6.4**: Modify `pyproject.toml` to add `APAP003` to the `select = [...]` list (enables the lint gate in CI); APAP003 plugin was already registered in T-1B.2

### T-6.3 — Swap Slice 5 logging placeholder for `log_safe`

- [ ] **T-6.5**: Modify `app/core/csrf.py` — replace `logging.getLogger(__name__).warning(...)` from T-5B.27 with `log_safe("csrf.rejected", path=..., reason=...)`
- [ ] **T-6.6**: Modify `app/core/csrf.py` — replace the `"CSRF middleware disabled by settings"` placeholder with `log_safe("csrf.disabled")`

### T-6.4 — Add log call sites (demonstrate the pattern)

- [ ] **T-6.7**: Add `log_safe("auth.login", email=user["email"])` in `/auth/callback` after successful login (email WILL be redacted — proves redaction works)
- [ ] **T-6.8**: Add `log_safe("voluntario.deactivated", voluntario_id=...)` in `voluntarios_service.deactivate_voluntario` after success

### T-6.5 — Tests

- [ ] **T-6.9**: Create `tests/test_logging.py` — parametrized over redaction cases: email redacted, `session_token` redacted, case-insensitive match, `_`/`-` equivalent, non-PII passes through; JSON format validation; `configure_logging` idempotent
- [ ] **T-6.10**: Create `tests/test_logging_redaction_adversarial.py` — 10+ cases: `Session-Token`, `JWT`, `OAuth_Code`, `pkce_verifier`, `csrf_token`, `pkce_challenge`, `authorization`, `cookie`, `referer`, `ip_address`, `x_forwarded_for` (uppercase), `Session_Token` (mixed), `user_email_address` NOT redacted (descriptive name), `e_mail` NOT redacted (orthographic split)
- [ ] **T-6.11**: Create `tests/test_apap003.py` — ruff rule exercise; violating file fails `ruff check --select APAP003`, clean file passes
- [ ] **T-6.12**: Create `tests/test_log_safe_event_name_match.py` — verify `csrf.rejected` event name is preserved after the Slice 5 → Slice 6 swap (T-6.5)

---

## Slice 7 — TOCTOU fix

**Estimated LOC**: ~150 total (~30 impl + ~120 tests)
**Decision**: SINGLE PR (under budget)

### T-7.1 — Service method

- [ ] **T-7.1**: Add `_DEACTIVATE_VOLUNTARIO_SQL` constant and `deactivate_voluntario(client, voluntario_id) -> bool` to `app/modules/voluntarios/service.py` — `UPDATE...WHERE id=$1 AND activo=true RETURNING id` pattern; returns `True` if row deactivated, `False` if nonexistent or already inactive
- [ ] **T-7.2**: Verify the pattern matches `app/modules/animals/service.py` (delete pattern already in codebase)

### T-7.2 — Route handler

- [ ] **T-7.3**: Modify `app/modules/voluntarios/routes.py:177-195` — collapse existence check + UPDATE into a single call to `voluntarios_service.deactivate_voluntario(client, voluntario_id)`; return 404 via `HTTPException(status_code=404)` if it returns `False`

### T-7.3 — Tests

- [ ] **T-7.4**: Add `tests/test_voluntarios_service.py::test_deactivate_idempotent` — call twice; first returns `True`, second returns `False`
- [ ] **T-7.5**: Add `tests/test_voluntarios_routes.py::test_deactivate_routes_404_on_second_call` — first POST returns 303, second returns 404
- [ ] **T-7.6**: Add `tests/test_voluntarios_routes.py::test_deactivate_routes_invoca_execute_sql_una_vez` — mock counts calls; assert exactly one
- [ ] **T-7.7**: Add `tests/test_voluntarios_concurrent.py::test_concurrent_deactivate_one_winner` — platform-gated to PostgreSQL (skip on SQLite via `APAP_E2E_BASE_URL`); `asyncio.gather` two concurrent POSTs; mock simulates row lock: first returns `[{"id": "v-1"}]`, second returns `[]`; assert exactly one 303, exactly one 404, no 500

---

## Apply order & dependencies

| Order | PR | Depends on | Parallel with |
|-------|----|------------|---------------|
| 1 | PR-1A + PR-1B (Slice 1) | — | — |
| 2 | PR-2 (Slice 2) | PR-1A, PR-1B | PR-3 |
| 3 | PR-3 (Slice 3) | PR-1A, PR-1B | PR-2 |
| 4 | PR-4 (Slice 4 XSS audit) | PR-1A, PR-1B | — |
| 5 | PR-5A + PR-5B (Slice 5 Auth hardening) | PR-3, PR-4 | PR-7 |
| 6 | PR-6A + PR-6B (Slice 6 Structured logging) | PR-5B | PR-7 |
| 7 | PR-7 (Slice 7 TOCTOU fix) | PR-1A, PR-1B | PR-5, PR-6 |

**Chain strategy**: `stacked-to-main` — each PR targets `staging`; one PR per slice; all merge to `staging` before promotion.

**Parallel-safe pairs**: (PR-2, PR-3), (PR-7, PR-5), (PR-7, PR-6)

---

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~2,900 (all slices combined) |
| 400-line budget risk | **High** — 3 slices (1, 5, 6) require splitting |
| Chained PRs recommended | Yes |
| Suggested split | 11 PRs total (1A, 1B, 2, 3, 4, 5A, 5B, 5B1*, 5B2*, 6A, 6B, 7) — *if PR-B split needed |
| Delivery strategy | `force-chained` |
| Chain strategy | `stacked-to-main` |

```
Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High
```

---

## Implementation commits (per PR, filled by sdd-apply)

Each PR: 1 failing test → implementation → refactor/docs. Every commit must pass `make all` independently.

## Persistence

Persisted to Engram:
- `project: apap_web`
- `topic_key: sdd/hardening-2026-q2/tasks`
- `type: architecture`
- `capture_prompt: false`
