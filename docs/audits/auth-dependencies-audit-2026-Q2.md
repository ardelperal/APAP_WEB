# Auth Dependencies Audit — 2026 Q2

**Scope**: every public function in `app/core/auth_dependencies.py`
**Method**: code review + codegraph caller analysis + existing-test coverage check + pre-slice form audit
**Date**: 2026-06-27
**Verdict**: **PASS** — auth_dependencies.py is currently compliant with the rules
in scope (Rule 6 fixed in PR-3, Rule 7 already correct per current code;
SB-3 verified `PUBLIC_PATHS` includes `/auth/callback`). The single HIGH
finding is the absence of CSRF defense, addressed in PR-5B.

---

## Scope

| Item | Value |
|---|---|
| File audited | `app/core/auth_dependencies.py` |
| Lines audited | 142 |
| Public functions | 4 (`get_insforge_client_dep`, `get_current_user_optional`, `return_early_if_response`, `require_authorized_user`) |
| Cross-references | `app/main.py` (middleware + `_redirect` helper), `app/core/session.py` (`read_session`, `session_cookie_name`), `app/core/csrf.py` (PR-5B, planned) |
| Auditors | `sdd-apply` PR-5A on `hardening-2026-q2/slice-5a-audit-doc` from `staging` (bd8a98e) |

## Methodology

1. **Read** every line of `app/core/auth_dependencies.py` and the 4 caller files
   (`app/main.py`, `app/modules/animals/routes.py`, `app/modules/entradas/routes.py`,
   `app/modules/voluntarios/routes.py`).
2. **codegraph_explore** for cross-file caller analysis (blast radius per symbol).
3. **Existing test coverage check** — read `tests/test_auth_dependencies.py`,
   `tests/test_auth_session_is_authorized.py`, `tests/test_middleware_is_authorized.py`,
   `tests/test_animals_routes_redirects.py` to confirm Rule 7 behavior is pinned.
4. **Static grep audit** — confirm `HTTPException(status_code=302` returns 0
   matches in `app/`.
5. **Pre-slice form audit** (per round-2 fix `REG-S-2`) — enumerate all
   `<form method="post">` in `app/templates/`, count, map to handler routes,
   confirm none currently carry `<input type="hidden" name="csrf_token">`.
   Captured as the starting state for PR-5B's
   `tests/test_all_post_forms_have_csrf_input.py`.

---

## Functions

### `get_insforge_client_dep()` — line 40

| Aspect | Detail |
|---|---|
| **Signature** | `def get_insforge_client_dep():` (no annotation, generator) |
| **Returns** | `Iterator[InsForgeClient]` (implicit) |
| **Callers** | 5 sites in `app/modules/{animals,entradas,voluntarios}/routes.py`; tests via `app.dependency_overrides[...]` |
| **Test coverage** | Indirect — exercised by every route test that uses `app.dependency_overrides` |
| **Findings** | Missing return type annotation (LOW-2); resource-management contract correct |
| **Consolidation opportunities** | None — single responsibility (per-request client lifecycle) |

### `get_current_user_optional(request: Request) -> dict | None` — line 68

| Aspect | Detail |
|---|---|
| **Signature** | `def get_current_user_optional(request: Request) -> dict \| None` |
| **Returns** | session payload dict, or `None` if cookie missing/invalid |
| **Callers** | `require_authorized_user` (line 110), `app/main.py:208` (`/unauthorized` route) |
| **Test coverage** | Covered indirectly via `require_authorized_user` tests + `/unauthorized` route test |
| **Findings** | None functional |
| **Consolidation opportunities** | HIGH PRIORITY for PR-5B — the future `CsrfMiddleware.dispatch` in `app/core/csrf.py` will replicate this exact read-cookie-and-decode pattern. Extract `read_session_payload(request) -> dict \| None` and have both call it. Tracked as **MEDIUM-1** (extraction is larger than a one-line fix; ties into the "triple duplication" finding below). |

### `return_early_if_response(value: object) -> Response | None` — line 83

| Aspect | Detail |
|---|---|
| **Signature** | `def return_early_if_response(value: object) -> Response \| None` |
| **Returns** | the value if it's a `Response`; otherwise `None` |
| **Callers** | `app/main.py:193`, `app/main.py:343`; not used by module routes (which still expect `user` to be a dict and use other patterns) |
| **Test coverage** | Indirect (covered by route tests that exercise the auth guard) |
| **Findings** | **MEDIUM-1** — parameter type `object` is overly broad. The only callers pass `Response \| dict`; tightening to `Response \| dict` catches misuse at type-check time and makes the helper's purpose explicit. Touches callers in `app/main.py` (2 sites). |
| **Consolidation opportunities** | None — leaf helper, single responsibility |

### `require_authorized_user(request, payload=Depends(get_current_user_optional)) -> Response | dict` — line 108

| Aspect | Detail |
|---|---|
| **Signature** | `def require_authorized_user(request: Request, payload: dict \| None = Depends(get_current_user_optional)) -> Response \| dict` |
| **Returns** | `RedirectResponse` (no session OR not authorized) or payload dict (authorized) |
| **Callers** | 23 production usages across `app/main.py` (4 sites), `app/modules/animals/routes.py` (7), `app/modules/entradas/routes.py` (7), `app/modules/voluntarios/routes.py` (5) |
| **Test coverage** | Direct: `tests/test_auth_dependencies.py::test_require_authorized_user_default_false`, `::test_pre_fix_cookie_redirects_to_unauthorized`. Indirect: route tests in `tests/test_animals_routes_redirects.py`, `tests/test_entradas_routes.py`, `tests/test_auth_session_is_authorized.py` |
| **Findings** | Rule 7 compliant: returns `RedirectResponse` (not `HTTPException`); default-flip to `False` confirmed (PR-3); docstring already explains Rule 6 + Rule 7 lineage |
| **Consolidation opportunities** | **LOW-1** (triple duplication) — the middleware in `app/main.py:147-175` (`protect_user_facing_routes`) ALSO reads the session cookie, decodes the payload, and checks `is_authorized`. After PR-5B, `CsrfMiddleware` will be a third copy of this same pattern. The middleware copies can't import this dependency (they run before FastAPI's dep injection), so the consolidation must be a leaf helper (`read_session_payload(request)`) that all three call. Tracked as **MEDIUM-2** because it crosses file boundaries and benefits from being done together with PR-5B's `CsrfMiddleware` (the new call site is the strongest motivator). |

---

## Findings

| # | Severity | Location | Description | Current behavior | Proposed resolution | Status |
|---|---|---|---|---|---|---|
| F-1 | **HIGH** | `app/core/auth_dependencies.py` + `app/main.py` (cookies) + 8 templates | **No CSRF defense** on any POST form. A stolen or replayed `apap_session` cookie (e.g. via XSS, log leak) lets an attacker impersonate the user in POSTs to all 10 handlers. | `apap_session` and `apap_pkce` cookies carry `samesite="lax"` (app/main.py:261, :307). No token validation. | **PR-5B** — implement `app/core/csrf.py::CsrfMiddleware`, set `samesite="strict"`, inject `<input type="hidden" name="csrf_token">` into all 8 form templates. Spec REQ-AH-5 through REQ-AH-10. | **TRACKED** — PR-5B (this change's next slice) |
| F-2 | **MEDIUM** | `app/core/auth_dependencies.py:83` (`return_early_if_response`) | Parameter typed `object`; should be `Response \| dict` for type-safety. Currently the helper accepts anything and only checks `isinstance(value, Response)`. | Helper accepts any value; misuse surfaces as runtime `AttributeError` only when the caller tries to treat the response as a dict. | Tighten annotation to `Response \| dict`; update the 2 call sites in `app/main.py` to pass only `Response \| dict`. Pure type tightening, no behavior change. | **FOLLOW-UP #1** — to open after PR-5B merges |
| F-3 | **MEDIUM** | `app/core/auth_dependencies.py` + `app/main.py:147-175` + `app/core/csrf.py` (planned) | Triple duplication of "read session cookie + decode payload" pattern. Same 4-line snippet copy-pasted across three locations. | Each call site reads `request.cookies.get(session_cookie_name())`, calls `read_session(token, secret=...)`, returns `None` or dict. | Extract leaf helper `read_session_payload(request) -> dict \| None` in `app/core/auth_dependencies.py` (or `app/core/session.py`); have `get_current_user_optional`, `protect_user_facing_routes` middleware, and `CsrfMiddleware` call it. **Best done together with PR-5B** since that's when the third copy appears. | **FOLLOW-UP #2** — to open after PR-5B merges (or co-shipped with PR-5B as a small extra commit) |
| F-4 | **MEDIUM** | `app/core/auth_dependencies.py:40` (`get_insforge_client_dep`) | Missing return type annotation on the generator (should be `Iterator[InsForgeClient]`). | Type checkers (mypy/pyright) treat return type as `Any`; downstream type inference degrades. | Add `from collections.abc import Iterator` and annotate as `Iterator[InsForgeClient]`. One-line change, zero behavior delta. | **FOLLOW-UP #1** (bundle with F-2) — same follow-up issue |
| F-5 | **LOW** | `app/main.py:115` (`_redirect`) | Local helper `def _redirect(path: str) -> RedirectResponse: return RedirectResponse(url=path, status_code=302)`. Redundant with `RedirectResponse(url=path, status_code=302)` inline usage (3 sites in `auth_dependencies.py`). | Two ways to spell the same redirect. Mild cognitive cost. | Consolidate into a single `app/core/redirects.py::redirect(path: str) -> RedirectResponse` and import from both `auth_dependencies.py` and `main.py`. Out of scope for Slice 5 (spec §Out of scope explicitly defers this). | **DOCUMENTED ONLY** — spec §"Out of scope" defers; revisit if usage grows past 5 sites |
| F-6 | **LOW** | `app/core/auth_dependencies.py:108-141` (`require_authorized_user`) | Two near-identical `RedirectResponse` calls (lines 139, 141) with different URLs. Could be a single dispatch, but the current form is more readable. | Two early-return statements; readability OK. | Leave as-is. Mentioned for completeness. | **NO ACTION** |
| F-7 | **LOW** | `tests/test_auth_session_is_authorized.py:52` | Test imports `require_authorized_user` from `app.modules.animals.routes` (legacy path); the canonical import is now `app.core.auth_dependencies`. Stale duplicate. | Old test still passes because `animals/routes.py` re-exports the symbol. Mild maintenance debt. | Update import to `app.core.auth_dependencies`. Trivial cleanup, deferred to a tests-cleanup pass. | **DOCUMENTED ONLY** |

---

## Pre-slice form audit (per round-2 fix REG-S-2)

### Form enumeration

Grep of `<form method="post">` across `app/templates/`:

| # | Template | Line | Action attribute | Maps to handler |
|---|---|---|---|---|
| 1 | `admin.html` | 19 | `/admin/users` | `app/main.py:366` (`@application.post("/admin/users")`) |
| 2 | `admin.html` | 76 | `/admin/users/{{ u.id }}/deactivate` | `app/main.py:393` (`@application.post("/admin/users/{user_id}/deactivate")`) |
| 3 | `animales/detail.html` | 16 | `/animales/{{ animal.id }}/delete` | `app/modules/animals/routes.py:357` |
| 4 | `animales/form.html` | 20 | `""` (self-submit) | `app/modules/animals/routes.py:144` (create) AND `:282` (update) — same template reused |
| 5 | `entradas/detail.html` | 14 | `/entradas/{{ entrada.id }}/delete` | `app/modules/entradas/routes.py:244` |
| 6 | `entradas/form.html` | 20 | `"{{ form_action }}"` (Jinja var) | `app/modules/entradas/routes.py:103` (create) AND `:192` (update) — same template reused |
| 7 | `voluntarios/detail.html` | 11 | `/voluntarios/{{ voluntario.id }}/deactivate` | `app/modules/voluntarios/routes.py:177` |
| 8 | `voluntarios/form.html` | 18 | `""` (self-submit) | `app/modules/voluntarios/routes.py:103` |

**Counts**: 8 distinct `<form method="post">` tags, **10 POST handlers** (the two form.html files are reused for both create and update). The spec's "10 forms" refers to handlers, not form tags. The audit parametrized test (PR-5B, T-5B.20) will parametrize over the 10 handlers.

### CSRF coverage check

Grep for `csrf_token` in `app/templates/` returns **0 matches** (confirmed). All 8 form tags are vulnerable to cross-site form submission until PR-5B lands.

### Starting state for PR-5B

When PR-5B lands and runs `pytest tests/test_all_post_forms_have_csrf_input.py`, the test will:

- Iterate over the 10 handlers
- Fetch each rendered form (via authenticated GET)
- Assert `<input type="hidden" name="csrf_token">` is present

**Before PR-5B**: 10/10 fail. This audit captures that starting state.

---

## Resolution log

| Finding | Resolution path |
|---|---|
| F-1 (HIGH) | PR-5B (this change's next slice) implements the CSRF middleware, SameSite=Strict cookies, and template injections. Spec REQ-AH-5..10. **Open `PR-5B` immediately after this PR-5A merges.** |
| F-2 (MEDIUM) | Follow-up issue #1 — tighten `return_early_if_response` parameter type to `Response \| dict`. Bundle with F-4. |
| F-3 (MEDIUM) | Follow-up issue #2 — extract `read_session_payload(request)` leaf helper to consolidate the triple duplication. **Recommended to co-ship with PR-5B** since the new `CsrfMiddleware` is the third copy; doing the extraction in PR-5B keeps the helper from being added before its callers. |
| F-4 (MEDIUM) | Follow-up issue #1 (same as F-2) — add `Iterator[InsForgeClient]` annotation to `get_insforge_client_dep`. |
| F-5 (LOW) | Documented. Spec §"Out of scope" defers `app/core/redirects.py` extraction. Revisit if usage exceeds 5 sites. |
| F-6 (LOW) | No action. |
| F-7 (LOW) | Documented. Trivial test import cleanup, defer. |

---

## Verdict

**PASS** (with one HIGH finding tracked for PR-5B).

`app/core/auth_dependencies.py` is currently compliant with every rule in
scope for this audit:

- **Rule 6** — default-deny: `payload.get("is_authorized", False)` confirmed
  via `tests/test_auth_dependencies.py::test_require_authorized_user_default_false`
  (PR-3).
- **Rule 7** — `RedirectResponse`, not `HTTPException`: confirmed via static
  grep (`HTTPException(status_code=302` returns 0 matches in `app/`) and
  pinned by the new `tests/test_rule_7_compliance.py` added in this PR.
- **SB-3** — `PUBLIC_PATHS` includes `/auth/callback`: confirmed via the
  slice-3 resolution (engram:14531). `/auth/callback` is at
  `app/main.py:63-70` in the public-paths set.

The single HIGH finding (F-1, missing CSRF defense) is the explicit scope
of PR-5B, which follows immediately. The MEDIUM findings are deferred to
numbered follow-up issues to be opened after PR-5B merges.

---

## Cross-references

- Spec: `openspec/changes/hardening-2026-q2/specs/05-auth-hardening/spec.md` (REQ-AH-1..4 cover this PR; REQ-AH-5..10 cover PR-5B)
- Design: `openspec/changes/hardening-2026-q2/design.md` §Slice 5 (PR-A subsection)
- Tasks: `openspec/changes/hardening-2026-q2/tasks.md` T-5A.1..6
- Related audit: `docs/audits/xss-audit-2026-Q2.md` (PR-XSS, must precede PR-5B)
- Related PRs: PR-3 (Rule 6, merged), PR-XSS (XSS audit, OPEN #112), PR-7 (TOCTOU, OPEN #113)
- Motivation: engram:14518 (security audit — CSRF defense-in-depth + admin endpoints), engram:14516 (rule-compliance audit)
- SB-3 resolution: engram:14531 (design; `/auth/callback` already in `PUBLIC_PATHS`)

---

## Issue #226 Addendum — 2026-07-20

### Scope

Structural extraction of the authorization `Rol` enum from `app/core/auth.py`
to dependency-free `app/core/roles.py`, plus import updates in `config.py` and
`auth_dependencies.py`.

### Methodology

CodeGraph caller/impact analysis, import-order smoke checks, focused auth tests,
and static inspection for remaining function-local role imports.

### Findings

| Severity | Finding | Resolution |
|---|---|---|
| INFO | The prior lazy `Rol` import masked an `auth.py` / `config.py` cycle. | `Rol` now has one dependency-free module home. |
| INFO | The lazy `get_user_by_email` import was no longer necessary once the role cycle was removed. | Promoted to a module-level import; focused authorization tests remain green. |

### Verdict

**PASS** — no authorization behavior, role value, default-deny rule, cookie,
session, CSRF, or logging contract changed.

---

## Issue #229 Addendum — 2026-07-20

### Scope

Deduplication of the developer-role decision shared by
`require_developer_user` and `require_developer_user_redirect`.

### Methodology

CodeGraph caller analysis, focused dependency tests, denial-log verification,
and static review of default-deny and redirect propagation paths.

### Findings

| Severity | Finding | Resolution |
|---|---|---|
| INFO | The two public dependencies repeated the same role decision and could drift. | A private helper now owns the role check and denial audit event. |
| INFO | The public failure signals intentionally differ. | Wrappers preserve the existing 403 and 302 contracts respectively. |

### Verdict

**PASS** — developer access remains default-deny, upstream redirects are
propagated unchanged, and denial logging continues through `log_safe` only.
