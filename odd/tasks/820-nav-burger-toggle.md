# #820 — Hamburger toggle JS controller (Phase B.2)

## Goal

Encender el comportamiento del botón burger que el slice #819 dejó estructural pero sin JS: el click togglea `aria-expanded` + `nav.hidden`, atrapa foco dentro del menú abierto, cierra en Escape / click fuera / click sobre link interno (route-change), y devuelve foco al botón al cerrar.

Slice B.2 del epic #817. Segunda mitad del split de #804.

## Acceptance criteria (del issue #820)

1. Click en el botón toggle flips `aria-expanded`; `<nav id="nav-main">` se vuelve visible.
2. Al abrir, foco se mueve al primer focusable del nav.
3. Tab / Shift+Tab quedan atrapados dentro del nav mientras está abierto.
4. Al cerrar (por cualquier razón), foco vuelve al botón.
5. Escape cierra.
6. Click fuera del nav + botón cierra.
7. Click sobre cualquier `<a>` interno cierra el menú antes de navegar.
8. Usuario de teclado puro puede abrir / navegar todos los links / cerrar / devolver foco al toggle sin usar el ratón.

## Scope (este slice = #820)

- `app/static/js/nav-burger.js` — nuevo. IIFE vanilla JS, ~70 líneas. Sin framework, sin build step, sin nuevas dependencias npm.
- `app/templates/base.html` — añade `<script src="/static/js/nav-burger.js" defer></script>` antes de `</body>`.
- `app/templates/base_mobile.html` — mismo cambio.
- `tests/e2e/test_nav_burger_toggle.py` — nuevo. 6 tests Playwright que cubren las ACs 1-7.
- `odd/tasks/820-nav-burger-toggle.md` — tracking del slice.

## Out of scope

- Colapso estructural → #819 (mergeado).
- `aria-current="page"` → #805 (Phase B).
- Iconos lucide → #808 (Phase B).
- Agrupar items en dropdowns → #809 (Phase B).

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + rama `feat/820-nav-burger-toggle` | en curso |
| WU-2 | `app/static/js/nav-burger.js` con IIFE vanilla JS | pendiente |
| WU-3 | `<script src=...>` en `base.html` y `base_mobile.html` | pendiente |
| WU-4 | `tests/e2e/test_nav_burger_toggle.py` con 6 tests | pendiente |
| WU-5 | Gates locales + commit + push + CI + merge | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` exit code cero.
- `python -m mypy` sin errores nuevos.
- `pytest tests/test_pages.py tests/test_template_selection.py tests/test_template_migration.py -q` verde (36 tests).
- `pytest tests/e2e/test_nav_burger_toggle.py -q` verde bajo chromium (auto-skip si no).
- `pytest tests/e2e/test_nav_responsive_structure.py -q` verde — la estructura #819 sigue intacta.
- `pytest tests/e2e/test_a11y_skip_link.py tests/e2e/test_a11y_main_landmark.py tests/e2e/test_a11y_brand_tabindex.py -q` verde.
- Issue-spec: el body del #820 ya está en castellano, pasa el check.
- Budget ≤ 350 líneas (diff esperado: ~80 de js + ~5 de templates + ~180 de test + ~85 de task file).

## Legacy fidelity (P1)

N/A — el slice sólo agrega JS al shell web.

## Estrategia de implementación

1. **JS** — `app/static/js/nav-burger.js`:
   - IIFE vanilla JS con `"use strict"`.
   - Lee `btn` y `nav` desde DOM. Si no existen, no-op (fail-safe).
   - Estado inicial: `open = btn.getAttribute("aria-expanded") === "true"`.
   - `setOpen(next)`: actualiza `aria-expanded` + `nav.hidden` + foco.
   - Listener `click` en btn → `setOpen(!open)`.
   - Listener `keydown` en document → Escape cierra; Tab/Shift+Tab hacen wrap dentro del nav.
   - Listener `click` en document → cierra si target no está dentro de `#nav-burger-toggle` o `#nav-main`.
   - Listener `click` en nav → cierra si target es `<a>` (route-change close, sin HTMX).
   - Listener `popstate` → cierra (browser back/forward).
2. **Templates** — `<script src="/static/js/nav-burger.js" defer></script>` antes de `</body>`. `defer` para que corra después de DOMContentLoaded. CSP `script-src 'self'` (definido en `SecurityHeadersMiddleware`) acepta el mismo-origen.
3. **Tests E2E** — `tests/e2e/test_nav_burger_toggle.py` con 6 tests Playwright. Patrón de skip por OAuth 503. Mismas fixtures que los otros tests E2E.
4. **Verificación local** — ruff/mypy/check_rules/pytest → commit → push → CI → merge.

## Riesgos identificados

1. **Script CSP** — el CSP baseline declara `'script-src 'self'`. El script es same-origin, así que cumple. Sin scripts inline, sin `unsafe-eval`.
2. **Foco fuera del nav tras cerrar** — si el usuario abrió el nav desde el botón y presiona Escape antes de cualquier Tab, el foco vuelve al botón (`btn.focus()`). Si después hace click en un link interno, el menú cierra y la navegación default del browser ocurre — el foco en el browser es responsabilidad del browser, no del script.
3. **HTMX ausente** — el proyecto no usa HTMX, confirmado por `grep -r "htmx" app/templates` (vacío). El route-change close se implementa vía `click` listener en el nav. La navegación full-page del browser cierra el menú naturalmente porque el DOM se reconstruye.
4. **`tabindex="-1"` en el brand (#818)** — el brand queda fuera del selector de focusables (excluye `[tabindex="-1"]`), así que no entra al focus trap. Sin conflicto.
5. **Tests E2E flaky** — los tests dependen de Playwright, chromium, y de la respuesta del server en :8000. Si la página redirige a `/login` por auth, algunos tests podrían fallar. Mitigación: preflight ya hace skip en ese caso; si no hay auth, el click sobre `/animales` redirige y el assertion de `aria-expanded='false'` se hace ANTES de la navegación (no_wait_after=True).
