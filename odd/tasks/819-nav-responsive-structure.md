# #819 — Single responsive nav (first half of #804, Phase B.1)

## Goal

Eliminar la duplicación estructural del shell: dos árboles de nav (`<details id="nav-burger">` para mobile + `<nav aria-label="Navegación principal">` para desktop) se vuelven un único `<nav id="nav-main" aria-label="Menú principal">` con un `<button id="nav-burger-toggle">` que controla la visibilidad vía CSS responsive. Sin JavaScript de toggle en este slice — eso llega en #820.

Slice B.1 del epic #817. Primera mitad del split de #804 (la segunda mitad es #820).

## Acceptance criteria (del issue #819)

1. El `<header>` tiene exactamente un `<nav id="nav-main">`.
2. El botón `<button id="nav-burger-toggle" aria-expanded="false" aria-controls="nav-main">Menú</button>` existe por debajo de `md` y se oculta en `md` o más.
3. La nav list está oculta por debajo de `md` por defecto. En `md` o más, se muestra inline.
4. Sin comportamiento JS — sin #820 el nav mobile queda oculto y el botón no hace nada.

## Scope (este slice = #819)

- `app/templates/base.html` — reemplazar el bloque `<details>/<summary>` mobile y el `<nav aria-label="Navegación principal">` desktop por: (a) un `<button id="nav-burger-toggle" aria-expanded="false" aria-controls="nav-main">` con SVG del burger, y (b) un `<nav id="nav-main" aria-label="Menú principal">` que contiene todos los items + el bloque user/login (movido dentro del nav para single source of truth).
- `app/templates/base_mobile.html` — el mismo cambio en la versión UA-selected.
- `app/static/css/output.css` — regenerado vía `make css` para incluir las utilities nuevas (`md:static`, `top-full`, `md:bg-transparent`, `md:border-t-0`, `md:border-l`).
- `tests/e2e/test_nav_responsive_structure.py` — nuevo. 3 tests Playwright que verifican la estructura y la respuesta a breakpoints.
- `tests/test_pages.py` — actualización del sentinel `test_base_template_collapses_mobile_nav_with_burger` (legacy `details#nav-burger` → nuevo `button#nav-burger-toggle` + `nav#nav-main`).
- `tests/test_template_selection.py` — actualización de los sentinels desktop/mobile (legacy `id="nav-burger"` → nuevo `id="nav-burger-toggle"`).
- `odd/tasks/819-nav-responsive-structure.md` — tracking del slice.

## Out of scope

- Toggle JS (`aria-expanded` se actualiza, Escape cierra, outside-click cierra, route-change cierra) → #820.
- Renombrar items largos del nav (#806), agrupar dropdown (#809), iconos lucide (#808), `aria-current="page"` (#805) — Phase B posterior.
- Reducción del listado de nav (algunos items podrían colapsar a un dropdown de módulo «Acogida» con Casas / Estancias / Animales) — #809.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking (este documento) + rama `feat/819-nav-responsive-structure` | en curso |
| WU-2 | Burger button + single nav en `base.html` y `base_mobile.html`; regenerar CSS | pendiente |
| WU-3 | Actualizar sentinels en `tests/test_pages.py` y `tests/test_template_selection.py` | pendiente |
| WU-4 | `tests/e2e/test_nav_responsive_structure.py` con 3 tests | pendiente |
| WU-5 | Gates locales + commit + push + CI + merge | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `ruff check .` sin findings nuevos.
- `python scripts/check_rules.py .` exit code cero.
- `python -m mypy` sin errores nuevos.
- `pytest tests/test_pages.py tests/test_template_selection.py tests/test_template_migration.py -q` verde (36 tests).
- `pytest tests/e2e/test_nav_responsive_structure.py -q` verde bajo chromium (auto-skip si no).
- `pytest tests/e2e/test_a11y_skip_link.py tests/e2e/test_a11y_main_landmark.py tests/e2e/test_a11y_brand_tabindex.py -q` verde — los slices de a11y previos siguen funcionando con la nueva estructura.
- Issue-spec: el body del #819 ya está en castellano (preparado antes de la rama), pasa el check.
- Budget ≤ 350 líneas (diff esperado: ~70 de templates + ~85 de test e2e + ~70 de test sentinels actualizados + ~100 de task file).

## Legacy fidelity (P1)

N/A — el slice sólo toca el shell web.

## Estrategia de implementación

1. **Templates** — reemplazar el bloque `<details>/<summary>` + `<nav aria-label="Navegación principal">` en `base.html` por el nuevo patrón: botón burger + single nav con todos los items + bloque user/login dentro. Mismo cambio en `base_mobile.html`.
2. **CSS** — `make css` regenera `app/static/css/output.css` con las utilities nuevas. La lista de items usa clases responsive (`px-4 md:px-3`, `py-2.5 md:py-2`) que ya existían o son variantes naturales.
3. **Sentinels existentes** — actualizar `tests/test_pages.py` (1 test) y `tests/test_template_selection.py` (2 tests) para reflejar el nuevo contrato `id="nav-burger-toggle"` y `id="nav-main"`. Sin estos cambios CI rojo por regresión legítima.
4. **E2E nuevo** — `tests/e2e/test_nav_responsive_structure.py` con 3 tests: (a) el header tiene exactamente un `<nav>`; (b) el burger button es visible en mobile y oculto en desktop; (c) el nav es oculto en mobile (hasta #820) e inline en desktop.
5. **Verificación local** — `make css` + ruff/mypy/check_rules/pytest → commit → push → CI → merge.

## Riesgos identificados

1. **Mobile users no pueden abrir el menú hasta #820** — el slice ships dead-in-the-water en mobile por diseño. El PR lo documenta explícitamente para que el revisor no se sorprenda. Mitigación: #820 entra inmediatamente en este epic.
2. **Tests E2E previos con selectores `details#nav-burger`** — `tests/e2e/test_nav_layout.py` y otros usan selectores que cambian. Verificado que `test_nav_layout.py` no menciona `nav-burger` (los sentinels viven en `tests/`, no en `tests/e2e/`). El nuevo `tests/e2e/test_nav_responsive_structure.py` reemplaza la cobertura de los selectores viejos.
3. **CSS utilities nuevas** — `md:static`, `md:bg-transparent`, `md:border-t-0`, `md:border-l` se generan vía `make css` (Tailwind JIT) automáticamente al aparecer en los templates. Si falta alguna, los estilos no se aplican y la nav queda malformada visualmente. Mitigación: pre-commit visual check no aplica acá; CI no renderiza browser. Confiamos en que `make css` genera lo necesario (verificado manualmente con `grep` post-build).
4. **Compatibilidad con el slice #818 (`tabindex="-1"` en brand)** — el primer Tab stop en mobile sigue siendo el skip link (#812), luego el burger button (nuevo), luego los items del nav (cuando se abra). El brand sigue fuera del orden Tab. Sin conflicto.

## Criterios de cierre del slice

- [ ] Branch `feat/819-nav-responsive-structure` con WU-2, WU-3, WU-4 mergeados.
- [ ] `base.html` y `base_mobile.html` con un único `<nav id="nav-main">` y un `<button id="nav-burger-toggle">`.
- [ ] Sentinels actualizados: `test_pages.py` y `test_template_selection.py` pasan.
- [ ] `tests/e2e/test_nav_responsive_structure.py` agregado y verde bajo chromium.
- [ ] Gates locales verdes.
- [ ] PR abierto contra `origin/main`, CI en verde, merge con `--admin`.
- [ ] Issue #804 cerrada (split en #819 + #820; #804 absorbe ambas).
- [ ] Memoria de sesión guardada con `mem_session_summary`.

