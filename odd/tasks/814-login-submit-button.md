# #814 — Login submit button: discernible name + no empty `name` (Phase A.3)

## Goal

Eliminar el fallo de accesibilidad que axe-core reporta sobre el botón de envío del formulario de magic-link en `/login`: históricamente el botón tenía `name=""` (atributo vacío, rechazado por WCAG 4.1.2) y/o carecía de texto visible. El slice fija el botón a un contrato verificable y agrega un E2E que pincha la regresión.

Slice A.3 del epic #817. Issue encadenada conceptualmente a #812 y #813 (suite a11y baseline): tras etiquetar el skip link y el `<main>`, este cierre elimina la última violación de axe-core reportada sobre `/login`.

## Acceptance criteria (del issue #814)

1. El botón submit del formulario magic-link tiene texto visible («Enviar enlace» o equivalente) o un `aria-label` no vacío.
2. El botón tiene un atributo `name` no vacío, o bien carece de atributo `name` (no debe estar vacío).
3. La auditoría axe-core `button-name` sobre `/login` devuelve cero violaciones.

## Scope (este slice = #814)

- `app/templates/login.html` — añadir `name="submit"` al botón del formulario `magic-link-form`. El texto visible «Enviar enlace» ya está presente; el atributo `name` se añade como cinturón y tirantes para que el contrato verificable no dependa sólo del texto.
- `tests/e2e/test_login_submit_button.py` — nuevo. 6 tests (3 individuales + 3 parametrizados) que verifican: texto visible no vacío, atributo `name` no ausente-o-vacío, accessible name derivado de texto o `aria-label`.
- `odd/tasks/814-login-submit-button.md` — tracking del slice.

## Out of scope

- El campo email ya tiene label y pasa el chequeo — se mantiene como está.
- El token CSRF es intencionalmente oculto y queda fuera del audit.
- El botón de Google OAuth se removió en `1763323 fix(m3-login)`; este slice aplica sólo al botón magic-link.
- `axe-core` como gate transversal de CI — issue pendiente en epic #817.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + rama `chore/814-login-submit-button` | en curso |
| WU-2 | `name="submit"` en el botón de `/login` | pendiente |
| WU-3 | `tests/e2e/test_login_submit_button.py` con 6 tests | pendiente |
| WU-4 | Gates locales + commit + push + CI + merge | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` exit code cero.
- `python -m mypy` sin errores nuevos.
- `pytest tests/test_pages.py tests/test_template_selection.py tests/test_template_migration.py -q` verde.
- `pytest tests/e2e/test_login_submit_button.py -q` verde bajo chromium (auto-skip si no).
- Issue-spec: el body del #814 ya está en castellano (preparado antes de la rama), pasa el check.
- Budget ≤ 200 líneas (diff esperado ~30 líneas de template + ~110 de test + ~80 de task file).

## Legacy fidelity (P1)

N/A — el slice sólo toca el template de login web.

## Estrategia de implementación

1. **Botón** — añadir `name="submit"` al `<button type="submit">` existente en `app/templates/login.html`. Edit manual de 1 línea + comentario Jinja documentando el contrato.
2. **E2E** — `tests/e2e/test_login_submit_button.py` sigue el patrón de `tests/e2e/test_a11y_skip_link.py`: preflight de `/login` (503 → skip con razón), tres tests individuales (texto, atributo `name`, accessible name derivado) + un parametrised que repite las tres aserciones para detectar regresión de un contrato individual sin romper los otros dos.
3. **axe-core** — no se inyecta en este slice. El textual + accessible-name check cubre el contrato funcional; la inyección de axe-core queda para el gate transversal del epic #817 (issue pendiente).
4. **Verificación local** — `make css` no aplica (no hay nuevas utilities Tailwind). Edit → ruff/mypy/check_rules/pytest → commit → push → CI → merge.

## Riesgos identificados

1. **Solapamiento con `tests/e2e/test_login_form.py`** — ese archivo ya tiene `test_login_form_submit_button_is_accessible` que sólo verifica que existe un submit button. El nuevo test es más estricto (texto + name + accessible name), así que ambos pueden coexistir: el viejo pasa, el nuevo pinea. Sin conflicto.
2. **Issue body H2 vs H3** — el checker `scripts/check_issue_specs.py` busca `### ` (H3) por sección, no `## ` (H2). El body original del #814 venía con `## Problem` (H2); arreglado proactivamente vía `gh api PATCH` antes de la rama, así el check pasa sin re-trigger manual.
3. **Login con Google OAuth** — el botón OAuth se removió en commit `1763323 fix(m3-login)`. El selector `form#magic-link-form button[type="submit"]` apunta exclusivamente al botón magic-link. Si en el futuro vuelve a haber OAuth button, el selector podría ambigüar; mitigación: añadir `id="magic-link-submit"` al botón en una iteración futura si el conflicto se materializa.

## Criterios de cierre del slice

- [ ] Branch `chore/814-login-submit-button` con WU-2 y WU-3 mergeados.
- [ ] `app/templates/login.html` con `<button type="submit" name="submit">`.
- [ ] `tests/e2e/test_login_submit_button.py` agregado y verde bajo chromium.
- [ ] Gates locales verdes.
- [ ] PR abierto contra `origin/main`, CI en verde, merge con `--admin`.
- [ ] Issue #814 cerrada vía `Fixes #814` keyword.
- [ ] Memoria de sesión guardada con `mem_session_summary`.

