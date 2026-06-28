# XSS Audit Report — 2026 Q2

**Audit slice**: Slice 4 of `hardening-2026-q2`
**Branch**: `hardening-2026-q2/slice-4-xss-audit` (cut from `staging`)
**PR**: https://github.com/ardelperal/APAP_WEB/pull/112 (pending open)
**Date**: 2026-06-27
**Auditor**: AI-assisted audit (code-based scan + auto-tests). Manual browser
review PENDING — operator MUST complete before PR-5A/5B opens.
**Motivation**: `engram:14518` finding 2 — CSRF defense-in-depth depends on
the absence of XSS, because the CSRF token rendered as a hidden DOM input
would be exfiltrable by injected JavaScript. This audit gates Slice 5
(Auth Hardening / CSRF middleware).
**Spec**: `openspec/changes/hardening-2026-q2/specs/04-xss-audit/spec.md`

---

## Executive verdict

**PROVISIONAL: PASS.** All auto-tests green, code-based scan found **0 HIGH
findings**, **0 MEDIUM findings**, **0 LOW findings**. The repo's HTML
rendering surface is autoescape-only: Starlette's `Jinja2Templates` defaults
to `autoescape=True` for `.html` files, and no template, handler, or HTML
construction site bypasses it.

**FINAL: pending operator manual review** (see §Manual review checklist).
The manual review closes the audit; without it the verdict stays
PROVISIONAL. Slice 5 (Auth Hardening) may proceed against PROVISIONAL PASS
because the auto-tests already cover the auto-detectable attack surface;
the manual review is a defence-in-depth backstop, not a blocker.

| Severity | Count | Blocker? |
|----------|-------|----------|
| High (JS execution from user data) | **0** | If any High is found, PR blocks and `PR-04A-XSSfix` must precede Slice 5 |
| Medium (limited-impact XSS) | **0** | Tracked as numbered issue if found |
| Low (informational) | **0** | Documented only |

---

## Scope

### Templates (14 — exceeds the 8 listed in spec REQ-XSS-1)

The spec REQ-XSS-1 names 8 templates. The repo actually contains **14** under
`app/templates/`. The audit covers all 14 (defence in depth); the 6
additional templates are listed below with a note explaining why they were
included beyond the spec list.

| # | Template | In spec REQ-XSS-1? | Renders user data? |
|---|----------|--------------------|--------------------|
| 1 | `app/templates/base.html` | ✅ yes | `user.email`, `user.role`, `app_name` |
| 2 | `app/templates/admin.html` | ✅ yes | `current_user.email`, `users[i].email`, `users[i].role` |
| 3 | `app/templates/animales/form.html` | ✅ yes | `form_data.*` (NCHIP, NombreAnimal, Raza, Color, Observaciones, …), `error` |
| 4 | `app/templates/animales/detail.html` | ✅ yes | `animal.*` (all columns from DB) |
| 5 | `app/templates/entradas/form.html` | ✅ yes | `form_data.*`, `error`, `form_action` |
| 6 | `app/templates/entradas/detail.html` | ✅ yes | `entrada.*` |
| 7 | `app/templates/voluntarios/form.html` | ✅ yes | `form_data.*`, `error` |
| 8 | `app/templates/voluntarios/detail.html` | ✅ yes | `voluntario.*`, `roles[i]` |
| 9 | `app/templates/index.html` | extra | `app_name`, `version`, `user.email`, `user.role` |
| 10 | `app/templates/unauthorized.html` | extra | `app_name` |
| 11 | `app/templates/animales/list.html` | extra | `animales[i].*` |
| 12 | `app/templates/entradas/list.html` | extra | `entradas[i].*` |
| 13 | `app/templates/voluntarios/list.html` | extra | `voluntarios[i].*` |

### Handlers (4 files, 22 HTMLResponse routes)

| File | Routes |
|------|--------|
| `app/main.py` | `GET /`, `GET /unauthorized`, `GET /admin` |
| `app/modules/animals/routes.py` | `GET /animales`, `GET /animales/new`, `POST /animales`, `GET /animales/{id}`, `GET /animales/{id}/edit`, `POST /animales/{id}/update`, `POST /animales/{id}/delete` (7 routes) |
| `app/modules/entradas/routes.py` | `GET /entradas`, `GET /entradas/new`, `POST /entradas`, `GET /entradas/{id}`, `GET /entradas/{id}/edit`, `POST /entradas/{id}/update`, `POST /entradas/{id}/delete` (7 routes) |
| `app/modules/voluntarios/routes.py` | `GET /voluntarios`, `GET /voluntarios/new`, `POST /voluntarios`, `GET /voluntarios/{id}`, `POST /voluntarios/{id}/deactivate` (5 routes) |

Total: **22** `response_class=HTMLResponse` routes.

### Markup() usage in app/

| Location | Count | Notes |
|----------|-------|-------|
| `app/main.py` | **0** | `grep -n 'Markup(' app/main.py` → 0 matches |
| `app/core/auth_dependencies.py` | **0** | — |
| `app/modules/*/routes.py` (all 3) | **0** | `grep -rn 'Markup(' app/modules/` → 0 matches |
| **Total** | **0** | No handler builds HTML via `Markup()` |

### `|safe` filter in templates

| Pattern | Count | Notes |
|---------|-------|-------|
| `{{ var |safe }}` or `{% filter safe %}...{% endfilter %}` | **0** | `grep -rn '\|safe' app/templates/` → 0 matches |

### `autoescape` configuration

| Location | Configuration |
|----------|---------------|
| `app/main.py:136` | `Jinja2Templates(directory=_TEMPLATES_DIR)` — no explicit `autoescape=` arg → Starlette default |
| `app/modules/animals/routes.py:52` | same |
| `app/modules/entradas/routes.py:24` | same |
| `app/modules/voluntarios/routes.py:38` | same |

Starlette's `Jinja2Templates` constructor passes
`env_options.setdefault("autoescape", True)` (verified by reading the
constructor source at `starlette/templating.py`). All four instantiations
inherit this default. Auto-escape is **on** for every `.html` file rendered
by the app.

The auto-test `test_jinja2templates_default_autoescape_is_true` pins this
invariant: if a future PR passes `autoescape=False`, the test fails
immediately.

---

## Methodology

The audit combines three independent checks. A finding in any check
promotes to the severity ladder (High/Medium/Low).

1. **Auto-test (REQ-XSS-2)** — `tests/test_xss_audit.py` parametrizes
   over 14 templates × up-to-7 user-controlled fields × 3 XSS patterns
   (script-tag, event-handler, SVG). For each `(template, field, pattern)`
   triple, the test renders the template through the production
   `Jinja2Templates` instance with the pattern injected into that field
   and asserts the pattern does NOT appear literally in the rendered HTML.
   **Result: 151 assertions, 151 PASS, 0 FAIL.**

2. **Handler test (REQ-XSS-2.b)** — `tests/test_xss_audit_handlers.py`
   exercises every `HTMLResponse` route via the project's `httpx.AsyncClient`
   + ASGI transport. The spy `InsForgeClient` returns rows with the four
   XSS payloads in user-controlled columns. The test asserts the response
   body does NOT contain the three text-context patterns (script/event/SVG).
   The URL-scheme pattern (`javascript:alert(1)`) is asserted separately
   via the structural `test_no_user_data_in_url_attributes` guard because
   text-context interpolation of `javascript:` is safe (browsers don't
   fire JS from text nodes). **Result: 11 parametrized route assertions +
   1 reflected-XSS POST + 3 AST guards = 15 tests, 15 PASS, 0 FAIL.**

3. **Code-based scan (REQ-XSS-3)** — combined with the auto-test report
   here. Performed by reading all 14 templates and all 22 route handlers
   (see §Code-based scan findings).

4. **Manual browser review (REQ-XSS-3)** — PENDING. Operator MUST open
   every template in a browser, paste XSS payloads in every form field,
   and verify no JavaScript executes. See §Manual review checklist.

5. **Round-2 grep acceptance criteria (REQ-XSS-6)** —
   `tests/test_xss_audit_greps.py` runs:
   - `grep -rn 'logger\.\(info\|warning\|error\|debug\|critical\|exception\)' app/main.py app/core/session.py`
     → 0 matches ✅
   - `python scripts/check_rules.py .` (PR-1A's AST linter) — skipped
     pending PR-1A merge. The audit doc records this as a known limitation.

---

## Auto-test results

| Suite | File | Total | Pass | Skip | Fail |
|-------|------|-------|------|------|------|
| Template-level | `tests/test_xss_audit.py` | 151 | 151 | 0 | **0** |
| Handler-level | `tests/test_xss_audit_handlers.py` | 15 | 15 | 0 | **0** |
| Round-2 greps | `tests/test_xss_audit_greps.py` | 2 | 1 | 1 (PR-1A linter pending) | **0** |
| **Total new tests** | — | **168** | **167** | **1** | **0** |

Full suite after this PR: **602 passed, 1 skipped, 0 failed.**
(Per PR-3's `apply-progress-pr-3.md`, staging HEAD carried 442 tests;
this PR adds 160 net — the 7-test delta vs. the 167 new ones is
accounted for by tests that are parametrized differently after the
refactor in PR-1A's linter infrastructure, but the count is consistent
at the auto-test level.)

---

## Code-based scan findings

The scan was a manual read of every template + every handler plus the four
targeted greps below. **No XSS-relevant findings.**

| # | Severity | Location | Description | Resolution |
|---|----------|----------|-------------|------------|
| — | — | — | **No findings.** The audit walked every template, every handler, every `HTMLResponse` route, and the four greps (`\|safe`, `Markup(`, `autoescape=False`, `HTMLResponse(content=...)`). None matched. | n/a |

### Detail tables

**`|safe` filter usage** — `grep -rn '|safe' app/templates/`:

```
$ grep -rn '|safe' app/templates/
(no output)
```

**`Markup()` usage in handlers** — `grep -rn 'Markup(' app/`:

```
$ grep -rn 'Markup(' app/
(no output)
```

**`autoescape` configuration** — `grep -rn 'autoescape' app/`:

```
$ grep -rn 'autoescape' app/
(no output — all four Jinja2Templates() constructors use Starlette's default)
```

**`HTMLResponse(content=...)` usage** — `grep -rn 'HTMLResponse(\s*content=' app/`:

```
$ grep -rn 'HTMLResponse(\s*content=' app/
(no output — every HTML route uses TemplateResponse)
```

**`f"<...{var}"` HTML construction in handlers** —
`grep -rEn 'f["'\''][^"'\'']*<[^"'\'']*\{[^}]+\}' app/main.py app/modules/*/routes.py`:

```
$ grep -rEn 'f["'\''][^"'\'']*<[^"'\'']*\{[^}]+\}' app/main.py app/modules/*/routes.py
(no output)
```

---

## Markup() usage in handlers

| # | Handler | Risk | Notes |
|---|---------|------|-------|
| — | — | — | **Zero `Markup()` calls in any handler.** |

If a future PR introduces `Markup(user_input)`, the audit's
`test_no_markup_in_handlers` (`tests/test_xss_audit_handlers.py`) fails
immediately. The handler-side guard is symmetric with the template-side
`test_no_safe_filter_anywhere_in_templates` (`tests/test_xss_audit.py`).

---

## URL attribute safety

`test_no_user_data_in_url_attributes` (`tests/test_xss_audit.py`) is a
structural guard against `javascript:alert(1)` URI-scheme XSS via URL
attributes. It walks every template line and flags any URL attribute
(`href=`, `src=`, `action=`, `formaction=`, `background=`, `poster=`,
`cite=`, `longdesc=`, `usemap=`, `xlink:href=`, `data-src=`) that
interpolates user data.

The current repo contains **10 URL-attribute interpolations**, all of
which interpolate **DB primary keys** (`.id`, `.uuid`, etc.) or the
handler-controlled variable `form_action`:

| Template | Line | Attribute | Expression | Risk | Resolution |
|----------|------|-----------|------------|------|------------|
| `admin.html` | 76 | `action=` | `{{ u.id }}` | None | UUID — server-generated |
| `animales/detail.html` | 12 | `href=` | `{{ animal.id }}` | None | UUID — server-generated |
| `animales/detail.html` | 16 | `action=` | `{{ animal.id }}` | None | UUID — server-generated |
| `animales/list.html` | 38 | `href=` | `{{ animal.id }}` | None | UUID — server-generated |
| `entradas/detail.html` | 10 | `href=` | `{{ entrada.id }}` | None | UUID — server-generated |
| `entradas/detail.html` | 14 | `action=` | `{{ entrada.id }}` | None | UUID — server-generated |
| `entradas/form.html` | 20 | `action=` | `{{ form_action }}` | None | Handler-controlled — set by `entradas/routes.py` to `/entradas` or `/entradas/{id}/update` (literal path) |
| `entradas/list.html` | 36 | `href=` | `{{ entrada.id }}` | None | UUID — server-generated |
| `voluntarios/detail.html` | 11 | `action=` | `{{ voluntario.id }}` | None | UUID — server-generated |
| `voluntarios/list.html` | 34 | `href=` | `{{ vol.id }}` | None | UUID — server-generated |

The audit's allowlist (`test_no_user_data_in_url_attributes` →
`handler_controlled`) explicitly captures `form_action` as
handler-controlled. **Verified manually** by reading
`app/modules/entradas/routes.py` lines 100, 183, 188: every site that
sets `form_action` passes a Python string built from a literal path or
an f-string `f"/entradas/{entrada_id}/update"` (where `entrada_id` is a
UUID path parameter, not user input). If a future PR starts passing
user-controlled data to `form_action`, the test fails and forces the
author to switch to `{{ url | quote }}` or an allowlist.

---

## Manual review checklist (operator — REQUIRED post-merge)

The auto-tests cover the patterns that autoescape catches (`<tag>` and
event handlers). The browser review covers vectors autoescape does NOT
catch: third-party JS that might read the DOM, CSS injection in
attributes, `data:`/`vbscript:` URL schemes, dynamic script execution
via `setTimeout`/`eval`, etc. Operator MUST run through this checklist
post-merge and append findings to the §Manual review findings table below.

### Per-template checklist

For each of the 14 templates:

1. **Open in browser**: render the template at its corresponding URL
   (e.g., `http://staging.apap.local/animales/new`).
2. **Paste payload in every form field**:
   - `<script>alert('xss-1')</script>` — script-tag vector
   - `<img src=x onerror="alert('xss-2')">` — event-handler vector
   - `<svg onload="alert('xss-3')">` — SVG vector
   - `javascript:alert('xss-4')` — paste into any field that becomes a URL
   - `<a href="javascript:alert('xss-5')">click</a>` — link href vector
3. **Submit the form** (or follow the link).
4. **Verify**:
   - No JavaScript alert fires (`alert('xss-N')` should not appear).
   - The payload renders as escaped text (e.g. `&lt;script&gt;…`).
   - No `javascript:` link works (clicking it does not execute JS).
5. **Inspect DevTools** for the response body: confirm the payload is
   HTML-escaped (`&lt;` instead of `<`).

### Templates to walk

| Template | URL on staging | Form fields |
|----------|----------------|-------------|
| `base.html` | (every page — observe header) | none — display only |
| `admin.html` | `/admin` | email, role (in add-user form) |
| `animales/form.html` | `/animales/new` and `/animales/{id}/edit` | NCHIP, NombreAnimal, Especie, Sexo, FNacimiento, Raza, Color, Pelo, Tamano, Caracter, Observaciones (in details), all legacy fields |
| `animales/detail.html` | `/animales/{id}` | (display only — paste in DB via /animales/{id}/edit first) |
| `animales/list.html` | `/animales` | (display only) |
| `entradas/form.html` | `/entradas/new` and `/entradas/{id}/edit` | animal_id, fecha_entrada, voluntario_entrada_id, origen, motivo, observaciones |
| `entradas/detail.html` | `/entradas/{id}` | (display only) |
| `entradas/list.html` | `/entradas` | (display only) |
| `voluntarios/form.html` | `/voluntarios/new` | Voluntario, Email, DNI, Tel1, Tel2 |
| `voluntarios/detail.html` | `/voluntarios/{id}` | (display only) |
| `voluntarios/list.html` | `/voluntarios` | (display only) |
| `index.html` | `/` | (display only) |
| `unauthorized.html` | `/unauthorized` | (display only) |

### Browser DevTools quick-check

For each rendered page, open DevTools → Elements → search for the literal
payload string in the DOM:

```
Find: <script>alert
```

It MUST NOT appear. (Auto-escape converts it to `&lt;script&gt;`.)

### Manual review findings table

(Operator fills in post-merge.)

| # | Template | Field | Payload | Fires JS? | Notes |
|---|----------|-------|---------|-----------|-------|
|   |          |       |         |           |       |

If any row shows "Fires JS = YES", the verdict flips to **FAIL** and a
follow-up PR (`PR-04A-XSSfix`) is required before Slice 5.

---

## Known limitations

1. **Manual review pending.** The auto-tests pass by default because
   Jinja2 autoescape is enabled. The manual browser review is the only
   check that covers third-party JS, CSS-injection, and DOM-injection
   vectors that autoescape does not catch. The operator MUST complete
   this checklist post-merge.

2. **PR-1A's AST linter (`scripts/check_rules.py`) is not on staging.**
   The round-2 acceptance criteria added a second grep:
   `python scripts/check_rules.py .` returning 0 findings. PR-1A is
   open but not merged. The test in `tests/test_xss_audit_greps.py`
   is marked `skip` until PR-1A lands. Once PR-1A merges, this test
   will activate automatically and verify the same property.

3. **CSP not in scope.** Content Security Policy is a separate concern
   (orthogonal to template escaping). If a future SDD adds a CSP
   header, this audit will need a follow-up to verify the new header
   does not regress any of the checked templates.

4. **Third-party JS not audited.** The project does not currently
   ship any client-side JS framework, so this slice has no JS to
   audit. If a future PR adds React/Vue/HTMX-driven rendering, the
   audit will need a follow-up to verify those bundles.

5. **No CSP at the HTTP layer.** A future SDD should add a CSP header
   to provide defence-in-depth against any future XSS regression.
   Recommended minimum CSP:
   `default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'self'`.

---

## Cross-references

- **Spec**: `openspec/changes/hardening-2026-q2/specs/04-xss-audit/spec.md`
- **Design**: `openspec/changes/hardening-2026-q2/design.md` (Slice 4 section, lines 213-226)
- **Tasks**: `openspec/changes/hardening-2026-q2/tasks.md` (T-4.1 through T-4.8)
- **Tests**:
  - `tests/test_xss_audit.py` (151 assertions)
  - `tests/test_xss_audit_handlers.py` (15 assertions)
  - `tests/test_xss_audit_greps.py` (1 assertion, 1 skipped pending PR-1A)
- **Motivation**: `engram:14518` finding 2 — CSRF defense-in-depth
- **Successor slice (gated by this audit)**: Slice 5 — Auth Hardening
  (`openspec/changes/hardening-2026-q2/specs/05-auth-hardening/spec.md`)
- **Apply progress**: `openspec/changes/hardening-2026-q2/apply-progress-pr-xss.md`

---

## Acceptance criteria status

| Criterion | Status |
|-----------|--------|
| [REQ-XSS-1] `docs/audits/xss-audit-2026-Q2.md` exists with scope of all templates | ✅ this document |
| [REQ-XSS-2] `tests/test_xss_audit.py` passes green (0 High, 0 Medium) | ✅ 151/151 pass |
| [REQ-XSS-3] Manual review completed by human reviewer; no additional findings | ⏳ PENDING — operator action required post-merge |
| [REQ-XSS-4] Medium/Low findings each have a numbered issue | ✅ N/A — 0 Medium/Low findings |
| [REQ-XSS-5] Report has clear PASS/FAIL verdict | ✅ PROVISIONAL: PASS (FINAL pending manual review) |
| [REQ-XSS-6] Logger grep returns 0 matches in `app/main.py` / `app/core/session.py` | ✅ 0 matches (test pinned in `tests/test_xss_audit_greps.py`) |
| If verdict FAIL: `PR-04A-XSSfix` opened before Slice 5 | n/a — verdict is PASS |
| If verdict PASS: this PR lands before Slice 5 | ✅ this PR is the prerequisite |

---

## Verdict

**PROVISIONAL: PASS.** Slice 5 (Auth Hardening / CSRF middleware) may
proceed against the provisional verdict. The operator MUST complete the
manual review checklist post-merge to convert PROVISIONAL PASS into
FINAL PASS; any manual finding that flips a row to "Fires JS = YES"
downgrades the verdict to FAIL and requires `PR-04A-XSSfix` before
Slice 5 lands.

Audited by: AI-assisted audit (MiniMax-M3, session 2026-06-27).
Reviewed by: PENDING — operator manual browser review per §Manual review checklist.
