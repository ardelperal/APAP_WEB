# E2E Coverage Audit — 2026 Q3

**Audit slice**: partial work for GitHub issue #206
**Branch**: `test/issue-206-e2e-coverage` (cut from `main@9b45cd5`)
**Date**: 2026-07-30
**Auditor**: AI-assisted (code-based analysis + Playwright E2E patterns)
**Motivation**: Issue #206 blocked by OAuth secrets in CI. This audit documents
the partial-work scope: E2E coverage added for public flows that require no
OAuth secrets, expanding the test inventory from 2 files to 6.
**Spec**: GitHub issue #206 acceptance criteria

---

## Executive verdict

**PASS — partial scope.** All new E2E tests added under `tests/e2e/` are
public-route flows that require no OAuth configuration. The CI `e2e` job
remains skipped until `APAP_OAUTH_CLIENT_ID` is provisioned; this partial
work does not change that gate. When OAuth lands, the expanded e2e inventory
will provide continuous real-browser regression coverage for the public surface.

| Severity | Count | Blocker? |
|----------|-------|----------|
| OAuth-gated flows not covered | 6+ | ❌ Expected blocker; documented in follow-up |
| Public-route regressions introduced | 0 | ✅ All new tests are additive |

---

## Scope

### New E2E test files added

| File | Tests | Public route? | OAuth required? |
|------|-------|--------------|-----------------|
| `tests/e2e/test_public_redirects.py` | 5 | Yes (`/healthz`, `/auth/google`) | No |
| `tests/e2e/test_login_form.py` | 6 | Yes (`/login`) | No |
| `tests/e2e/test_logout.py` | 3 | Yes (`/logout`) | No |
| `tests/e2e/test_layout_responsive_extended.py` | 5 | Yes (`/login`) | No |

### Routes covered by new tests

| Route | Method | Auth required? | Test module |
|-------|--------|----------------|-------------|
| `/healthz` | GET | No | `test_public_redirects.py` |
| `/auth/google` | GET | Public (returns 503 if unconfigured) | `test_public_redirects.py` |
| `/logout` | GET | No | `test_logout.py`, `test_public_redirects.py` |
| `/` | GET | Yes → redirects | `test_public_redirects.py` |
| `/animales` | GET | Yes → redirects | `test_public_redirects.py` |
| `/login` form | GET/POST | No | `test_login_form.py`, `test_layout_responsive_extended.py` |

### Routes NOT covered (OAuth-gated — follow-up #206)

| Route | Reason blocked |
|-------|---------------|
| `/` (authenticated dashboard) | Requires session cookie from OAuth |
| `/animales` (authenticated list) | Requires session cookie from OAuth |
| `/entradas`, `/voluntarios`, `/admin` | Requires session cookie from OAuth |
| `/auth/callback` | OAuth code exchange |
| POST `/logout` variant (issue #124) | Requires auth + POST form submission |

---

## Methodology

1. **Route enumeration**: Read `app/main.py` to enumerate all public and
   auth-gated routes.
2. **Auth-guard analysis**: Confirmed which routes redirect without session
   (auth middleware) vs. return 200 without session.
3. **Existing coverage audit**: Read all 3 pre-existing e2e files to avoid
   duplication (`test_landing.py`, `test_nav_layout.py`, `test_security_headers.py`).
4. **Test pattern matching**: Followed the established fixture conventions from
   `conftest.py` and the preflight-skip pattern used in all existing tests.
5. **Viewport coverage gap analysis**: `test_nav_layout.py` covers 375/768/1280;
   added 1024 and 1920 in `test_layout_responsive_extended.py`.
6. **CSRF surface audit**: Verified that `test_login_form.py` asserts
   `input[name=csrf_token]` presence per AGENTS.md §10.

---

## Findings

### Finding 1: `/logout` is GET not POST (issue #124)

**Severity**: Informational
**Location**: `app/main.py:523`
**Description**: The task description references "POST /logout" per issue #124,
but the current implementation uses `GET /logout` which redirects to `/`.
The POST variant is a separate feature request not yet implemented.
**Impact**: `test_logout.py` pins the current GET behaviour. Any future POST
variant will require a separate test addition.
**Action**: Issue #124 should be clarified: is the POST variant a new feature
or an existing expectation?

### Finding 2: Playwright ViewportSize type mismatch (pre-existing pattern)

**Severity**: Informational
**Location**: `tests/e2e/test_nav_layout.py`, `tests/e2e/test_layout_responsive_extended.py`
**Description**: `page.set_viewport_size()` expects `ViewportSize` (TypedDict)
but is called with `dict[str, int]`. This is a pre-existing pattern in
`test_nav_layout.py` (5 occurrences). The new `test_layout_responsive_extended.py`
replicates the same pattern.
**Impact**: mypy reports type errors for these calls. CI mypy gate does not
run on `tests/` (only `app/` + `migration/`).
**Action**: No immediate action. Could be fixed by casting or updating the
playwright stubs, but out of scope for this partial-work slice.

### Finding 3: CI `e2e` job remains skipped

**Severity**: Informational
**Location**: `.github/workflows/ci.yml` (not modified per constraint)
**Description**: The `e2e` job gate `vars.APAP_OAUTH_CLIENT_ID != ''` is
unchanged. New e2e tests will only run in CI when OAuth secrets are provisioned.
**Impact**: New tests will be collected and skipped at runtime by
`pytest_collection_modifyitems` in `conftest.py` when chromium is missing,
but will execute in any environment with `playwright install chromium`.
**Action**: Follow-up: provision OAuth secrets in GitHub repo to unblock CI.

---

## Verdict

**PASS — partial scope.** The e2e inventory grew from 2 to 6 test files,
covering all public routes without OAuth dependencies. No regressions introduced.
The OAuth-gated flows remain documented as follow-up work.

### Follow-up actions required (outside this slice)

| Action | Owner | Issue |
|--------|-------|-------|
| Provision `APAP_OAUTH_CLIENT_ID` + `APAP_OAUTH_CLIENT_SECRET` in GitHub repo | Operator | #206 |
| Verify `e2e` CI job runs and passes after OAuth provisioning | Operator | #206 |
| Implement POST `/logout` variant + tests | Agent | #124 |
| Add authenticated-flow E2E tests (dashboard, animales, entradas) | Agent | #206 |
| Fix `ViewportSize` TypedDict stubs in e2e tests | Agent | backlog |

---

## References

- Issue #206: `https://github.com/ardelperal/APAP_WEB/issues/206`
- PR for this slice: pending
- Pre-existing e2e files: `test_landing.py`, `test_nav_layout.py`, `test_security_headers.py`
- `tests/e2e/conftest.py` — fixture + collection infrastructure
- AGENTS.md §10 (CSRF), §12 (audit doc), §23 (E2E expectation per slice)
