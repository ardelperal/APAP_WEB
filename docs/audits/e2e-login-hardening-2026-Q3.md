[← Back to README](../../README.md)

# e2e-login-hardening-2026-Q3.md

This audit documents the scope, threat model, controls, decisions, and verdict for the hardening of the E2E mock login (`/e2e/login`) — issue #904 (epic #909, optional B hardened), delivered in PR #1006 across commits `836c3bc`, `23d7cce`, and `6c99f9f` in 2026 Q3.

| Section | Description |
|---|---|
| [Scope](#scope) | What changed and what did not. |
| [Threat model](#threat-model) | Risks of exposing `/e2e/login` in production as a release gate. |
| [Controls verified](#controls-verified) | Each control traced to the issue's acceptance criteria and commits. |
| [Design decisions](#design-decisions) | Deliberate choices with their rationale. |
| [Findings](#findings) | Severity, title, form, and details of each finding. |
| [Verdict](#verdict) | Final state of the E2E login surface. |
| [Residual risks and future hardening](#residual-risks-and-future-hardening) | Open risks and optional follow-ups. |
| [References](#references) | Files reviewed, tests, and related docs. |

## Scope

| Item | Value |
|---|---|
| Feature | E2E login hardening — audit event, IP rate limit, composition-level flag-off pin |
| Issue | #904 (epic #909, optional B hardened) |
| Pull request | #1006 (`836c3bc`, `23d7cce`, `6c99f9f`) |
| Datos sensibles | `APAP_E2E_AUTH_SECRET` (shared secret, primary gate), `target_email`, `client_ip` (audit fields) |
| Ficheros revisados | `app/core/e2e_auth.py`, `app/core/rate_limit_middleware.py`, `docs/codebase/logging-conventions.md`, `tests/test_e2e_auth.py`, `tests/test_rate_limit_middleware.py` |
| Controles principales | `log_safe("e2e.login", …)` on every attempt, `E2E_LOGIN_RATE_LIMIT_PER_MIN` IP bucket with shared 429 shape, flag-off 404 pinned against the real `create_app` |
| Fecha | 2026-09-26 |

Out of scope: the session minting performed by `app/core/session.py` (unchanged), the CSRF middleware (the route mints sessions with `write_session`; no form posts are involved), the OAuth callback rate-limit bucket (pre-existing, untouched except for the dispatch refactor that routes unprotected methods through `_handle_unprotected`), and the operator rotation runbook (tracked as sub-issue #907, see #905).

## Threat model

`/e2e/login` is enabled in production only as a release gate: setting `APAP_E2E_AUTH_ENABLED=true` registers a route that mints a valid session for `APAP_E2E_AUTH_DEFAULT_EMAIL` when a caller presents the shared secret in `X-E2E-Secret`. An attacker who obtains the secret obtains a full session; an attacker who does not can still probe the endpoint. The layered posture is:

1. **Secret as primary gate.** The route requires an exact, constant-time match (`hmac.compare_digest`) against `APAP_E2E_AUTH_SECRET`; a missing or wrong header answers `401` before any session is written. This control pre-exists (#598) and is unchanged by this audit.
2. **Rate limit as backstop.** A per-IP sliding-window bucket (5 attempts/minute) bounds online guessing of the secret and turns brute-force into a logged, throttled, and observable activity. The secret remains the actual authentication decision; the bucket never grants access.
3. **Audit for forensics.** Every attempt emits one structured `e2e.login` entry (outcome, target email, origin IP) so that probing, credential-stuffing attempts against the gate, and legitimate release-gate usage are distinguishable from stdout logs after the fact.

## Controls verified

1. **C1 — Audit event on every attempt (AC1, `836c3bc`).** Both the rejected path (`_audit_rejected_attempt`, outcome `invalid_secret`) and the success path (outcome `ok`) emit `log_safe("e2e.login", outcome=…, target_email=…, client_ip=…)` via `tests/test_e2e_auth.py::test_audit_log_emitted_on_success` and `::test_audit_log_emitted_on_invalid_secret`. The tests assert the raw secret never appears in the record.
2. **C2 — Rate limit 5/min/IP with 429 (AC2, `23d7cce`).** `RateLimitMiddleware._handle_e2e_login` hits the `e2e_login` scope of the shared `InProcessRateLimitBackend` sliding window. The 6th request from the same IP within 60 seconds gets the shared 429 shape (`Retry-After` + `X-RateLimit-*` headers) and a `log_safe("ratelimit.rejected", scope="e2e_login", …)` entry with no IP kwarg (REQ-5/D6). Verified by `TestE2ELoginRateLimit` in `tests/test_rate_limit_middleware.py`, including per-IP bucket isolation.
3. **C3 — Flag-off 404 pinned at composition level (AC3, `6c99f9f`).** Against the real `create_app`: with `APAP_E2E_AUTH_ENABLED` absent the app answers `404`; with the flag and secret set the route exists and answers `401` without the header (positive control). Verified by `test_production_app_answers_404_when_flag_absent` and `test_production_app_registers_route_when_flag_enabled` in `tests/test_e2e_auth.py`. The 404 behaviour itself pre-exists from #598 (`register_e2e_auth_routes` no-ops when disabled); the commit pins it so a future wiring regression fails CI.

## Design decisions

1. **Audit field names sit outside the closed redaction list.** The issue mandates recording the requested email and origin IP, but `email` and `ip_address` are two of the twelve fields redacted by `log_safe`. Rather than weakening the closed list, the events use the semantically distinct names `target_email` and `client_ip`. This policy is documented cross-ref in `docs/codebase/logging-conventions.md` ("Eventos de auditoría con PII exigida por un issue", added in `836c3bc`): the closed list does not change, and extending it remains a deliberate, reviewed change. The secret value is never a field of the event.
2. **Rate-limit state is worker-local in-process.** The bucket lives in the in-process backend installed by `install_rate_limit_middleware` — the same state scope as the auth cache per §29/#262. With the current single Coolify worker this is exact; if workers or replicas are ever added, the bucket becomes per-worker (each worker enforces its own 5/min) and the same TTL-0 / multi-worker review as `docs/runbooks/auth-cache-multi-worker.md` applies before scaling. As a backstop that never grants access, per-worker state is an acceptable precision trade for zero shared-infrastructure dependency.
3. **404 probes count toward the limit.** The bucket is checked in the middleware before route dispatch, so requests to `/e2e/login` consume bucket state even when the flag is off and the route answers `404`. This is deliberate: it prevents free enumeration of whether the release gate is enabled and keeps probe volume observable and bounded in both configurations.
4. **Ceiling is a module constant, not a `Settings` field.** `E2E_LOGIN_RATE_LIMIT_PER_MIN = 5` keeps the guard autonomous from configuration: the limit cannot be relaxed per-environment without a code change, which matches its role as an unconfigurable backstop. The shared secret remains the primary gate and is the only knob intended for operators.
5. **Secret rotation is an operator runbook, not this audit.** Rotation of `APAP_E2E_AUTH_SECRET` is tracked as the runbook sub-issue #907 (see #905). This audit records the pointer; the runbook will own trigger conditions, the rotation procedure, and rollback.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| HIGH | Probes of `/e2e/login` in production were neither bounded nor observable | fixed | Before `836c3bc`/`23d7cce`, unlimited unauthenticated attempts against the gate left no audit trail and no throttle. Now every attempt is logged (C1) and the 6th within a minute is rejected with 429 (C2). |
| MEDIUM | Flag-off behaviour was pinned only at module level, not against the real composition | fixed | `register_e2e_auth_routes` tests proved the no-op, but nothing pinned the `create_app` wiring. `6c99f9f` adds the composition-level 404 pin (C3). |
| LOW | Pre-existing test seam leak: `e2e_module.get_settings` replacements were never restored | fixed | Exposed by the new composition test in `6c99f9f`: earlier tests patched the seam with a lambda, so later readers inherited the mock settings. Fixed with an autouse fixture restoring the seam after every test. |
| INFO | Origin-IP resolution duplicated between audit and rate limit | fixed | `_origin_ip` reuses the rate limiter's `_extract_identity` seam, so the audit entry and the `e2e_login` bucket agree on what "origin IP" means (honouring `Settings.trust_xff` behind the Coolify reverse proxy). |

## Verdict

**PASS for the audited scope.** The E2E login surface now fails closed (flag absent → 404, pinned at composition level), fails slow (5/min/IP backstop with the shared 429 shape), and leaves one structured `log_safe` entry per attempt for forensics — with the secret as the sole authentication decision and never a log field. The dispatch refactor in `23d7cce` also improved the CRAP ratchet (15.16 → 14.07) instead of growing it.

## Residual risks and future hardening

- **IP extraction depends on proxy configuration.** With `Settings.trust_xff` enabled, a spoofed `X-Forwarded-For` from an untrusted hop could rotate bucket identity. Acceptable today because the Coolify reverse proxy is the only ingress; re-review if the topology changes.
- **Worker-local state resets on deploy/restart.** A restart clears bucket state, so a window boundary grants a brief extra allowance. Accepted: the secret, not the bucket, is the gate.
- **Shared egress IPs.** Several legitimate clients behind the same shared egress address share a bucket and can exhaust the 5/min ceiling. Accepted for a release-gate tool that is not user-facing.
- **No IP allowlist.** An allowlist restricting `/e2e/login` to known runner IPs is recorded as optional future hardening; the rate limit and the secret were chosen as the #904 scope.
- **Rotation runbook pending.** Secret rotation currently relies on the sub-issue #907 runbook (#905) landing before the gate is used for a real release cycle.

## References

- `app/core/e2e_auth.py` (`_origin_ip`, `_audit_rejected_attempt`, `register_e2e_auth_routes`).
- `app/core/rate_limit_middleware.py` (`E2E_LOGIN_RATE_LIMIT_PER_MIN`, `_handle_e2e_login`, `_handle_unprotected`, `_is_e2e_login_request`).
- `tests/test_e2e_auth.py` (`test_audit_log_emitted_on_success`, `test_audit_log_emitted_on_invalid_secret`, `test_production_app_answers_404_when_flag_absent`, `test_production_app_registers_route_when_flag_enabled`).
- `tests/test_rate_limit_middleware.py` (`TestE2ELoginRateLimit`).
- `docs/codebase/logging-conventions.md` (audit-event field-name policy, added by `836c3bc`).
- `docs/codebase/security.md` §29 / `docs/runbooks/auth-cache-multi-worker.md` (in-process state scope, issues #262/#287).
- `docs/audits/secret-startup-validation-2026-Q3.md` (startup secret-validation posture, retained as historical format reference).
- Commits `836c3bc`, `23d7cce`, `6c99f9f`; issues #904, #905, #907, #909, #262; PR #1006.
